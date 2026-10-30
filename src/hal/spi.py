"""SPI mestre: v1 (F4 — CR1/SR/DR) e v2 (H7 — CFG1/CFG2/TXDR/RXDR), palavra a palavra.

No v2 o quadro é de 32 bits (DSIZE=31): cada escrita de 32 bits do PAL em TXDR
é exatamente um quadro (sem empacotamento). No v1, quadros de 8 bits.

Observado na NUCLEO-H753ZI: o SPI v2 mestre só gera clock com o pino SCK em
função alternativa — sem isso o dado entra na FIFO e a transferência não anda.
Os blocos configuram os pinos antes de chamar setup().
"""

from __future__ import annotations

import logging

from hal.common import (
    enable_clock,
    family,
    has_register,
    restore_regs,
    save_regs,
    select_hsi_kernel,
    wait,
)

log = logging.getLogger("hal.spi")

# v1 (F4)
V1_SPE, V1_MSTR, V1_SSM, V1_SSI = 1 << 6, 1 << 2, 1 << 9, 1 << 8
V1_TXE, V1_RXNE, V1_BSY = 1 << 1, 1 << 0, 1 << 7
# v2 (H7)
V2_SPE, V2_CSTART, V2_SSI = 1 << 0, 1 << 9, 1 << 12
V2_MASTER, V2_SSM = 1 << 22, 1 << 26
V2_RXP, V2_TXP, V2_EOT = 1 << 0, 1 << 1, 1 << 3
V2_MBR_SHIFT = 28

_H7_KERNEL = {"123": ("D2CCIP1R", "SPI123SEL", 0b100),   # per_ck (HSI por padrão)
              "45": ("D2CCIP1R", "SPI45SEL", 0b011)}     # hsi_ker


class Spi:
    """Uso: with Spi(pal, "SPI1") as s: s.setup(divisor_log2=7); s.transfer(0xA5)"""

    def __init__(self, pal, name: str) -> None:
        self.pal = pal
        self.name = name
        self.v2 = has_register(pal, name, "CFG1")
        self.family = family(pal)
        self._saved: dict[str, int] = {}
        self._kernel_restore: tuple[str, str, int] | None = None
        self.bits = 32 if self.v2 else 8

    def __enter__(self) -> Spi:
        return self

    def __exit__(self, *_exc) -> None:
        self.restore()

    def setup(self, divisor_log2: int = 7, mode: int = 0) -> None:
        """Mestre, NSS por software. divisor = 2^(divisor_log2+1) (0 → /2 ... 7 → /256)."""
        enable_clock(self.pal, self.name)
        cpol, cpha = mode >> 1 & 1, mode & 1
        if self.v2:
            self._saved = save_regs(self.pal, self.name, ("CR1", "CR2", "CFG1", "CFG2"))
            self._select_kernel()
            # SSI=1 antes de MASTER: com SSM=1 e SSI=0 o SPI acusa MODF e derruba o mestre
            self.pal.write_reg(self.name, "CR1", V2_SSI)
            self.pal.write_reg(self.name, "IFCR", 0xFFF8)
            self.pal.write_reg(self.name, "CFG1", (divisor_log2 & 7) << V2_MBR_SHIFT | 31)
            self.pal.write_reg(self.name, "CFG2", V2_MASTER | V2_SSM | cpol << 25 | cpha << 24)
            self.pal.write_reg(self.name, "CR2", 0)                 # TSIZE=0: contínuo
            self.pal.write_reg(self.name, "CR1", V2_SSI | V2_SPE)
            if not self.pal.read_reg(self.name, "CFG2") & V2_MASTER:
                raise RuntimeError(f"{self.name}: modo mestre não ficou ativo (MODF?)")
            self.pal.write_reg(self.name, "CR1", V2_SSI | V2_SPE | V2_CSTART)
            log.info("%s: mestre, divisor /%d, modo %d, %d bits", self.name,
                     2 << divisor_log2, mode, self.bits)
        else:
            self._saved = save_regs(self.pal, self.name, ("CR1", "CR2"))
            # NSS interno alto (SSI) antes de MSTR, senão MODF derruba o mestre
            self.pal.write_reg(self.name, "CR1", V1_SSM | V1_SSI)
            self.pal.write_reg(self.name, "CR2", 0)
            self.pal.write_reg(self.name, "CR1", (divisor_log2 & 7) << 3 | V1_MSTR | V1_SSM
                               | V1_SSI | cpol << 1 | cpha)
            self.pal.write_reg(self.name, "CR1", self.pal.read_reg(self.name, "CR1") | V1_SPE)

    def transfer(self, word: int, timeout_s: float = 0.2) -> int:
        mask = (1 << self.bits) - 1
        if self.v2:
            wait(lambda: self._sr() & V2_TXP, timeout_s, f"{self.name}: TXP não subiu")
            self.pal.write_reg(self.name, "TXDR", word & mask)
            wait(lambda: self._sr() & V2_RXP, timeout_s, f"{self.name}: nada recebido (MISO?)")
            return self.pal.read_reg(self.name, "RXDR") & mask
        wait(lambda: self._sr() & V1_TXE, timeout_s, f"{self.name}: TXE não subiu")
        self.pal.write_reg(self.name, "DR", word & mask)
        wait(lambda: self._sr() & V1_RXNE, timeout_s, f"{self.name}: nada recebido (MISO?)")
        return self.pal.read_reg(self.name, "DR") & mask

    def restore(self) -> None:
        if self._saved:
            self.pal.write_reg(self.name, "CR1", 0)
            if self.v2:
                self.pal.write_reg(self.name, "IFCR", 0xFFF8)
            restore_regs(self.pal, self.name, {k: v for k, v in self._saved.items() if k != "CR1"})
            cr1 = self._saved["CR1"] & ~(V2_CSTART if self.v2 else 0)
            self.pal.write_reg(self.name, "CR1", cr1)
            self._saved = {}
        if self._kernel_restore:
            reg, field, old = self._kernel_restore
            self.pal.modify_field("RCC", reg, field, old)
            self._kernel_restore = None

    def _sr(self) -> int:
        return self.pal.read_reg(self.name, "SR")

    def _select_kernel(self) -> None:
        if self.family != "H7":
            return
        group = "45" if self.name.upper() in ("SPI4", "SPI5") else "123"
        if self.name.upper() == "SPI6":
            return                           # SPI6 no D3: clock padrão (pclk4)
        reg, field, code = _H7_KERNEL[group]
        _f, old = select_hsi_kernel(self.pal, reg, field, code)
        self._kernel_restore = (reg, field, old)
