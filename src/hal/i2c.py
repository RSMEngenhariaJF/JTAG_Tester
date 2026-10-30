"""I2C mestre — varredura de endereços (quem responde com ACK).

v2 (F7/H7/G0): CR2 com SADD/NBYTES/AUTOEND/START; NACKF/STOPF no ISR.
v1 (F4): START → SB → endereço → ADDR (ACK) ou AF (NACK) → STOP.
Clock: H7 usa HSI no kernel (TIMINGR calculado para ~100 kHz); F4 usa o PCLK1.
"""

from __future__ import annotations

import math

from hal.common import (
    enable_clock,
    family,
    has_register,
    restore_regs,
    save_regs,
    select_hsi_kernel,
    wait,
)

# v2
V2_PE = 1 << 0
V2_START, V2_STOP, V2_AUTOEND = 1 << 13, 1 << 14, 1 << 25
V2_NACKF, V2_STOPF, V2_BUSY = 1 << 4, 1 << 5, 1 << 15
V2_ICR_ALL = 0x3F38
# v1
V1_PE, V1_START, V1_STOP, V1_SWRST = 1 << 0, 1 << 8, 1 << 9, 1 << 15
V1_SB, V1_ADDR, V1_AF = 1 << 0, 1 << 1, 1 << 10
V1_BUSY = 1 << 1          # SR2


def timingr_100k(f_ck: int) -> int:
    """TIMINGR para ~100 kHz (modo padrão) com tick de 250 ns.

    SCLL = 5 µs, SCLH = 4 µs, SDADEL = 0,5 µs, SCLDEL = 1,25 µs (I2C-bus spec,
    folgados). PRESC é escolhido para o tick ficar perto de 250 ns.
    """
    presc = max(0, min(15, math.ceil(f_ck * 250e-9) - 1))
    t = (presc + 1) / f_ck
    scll = max(1, min(255, round(5e-6 / t) - 1))
    sclh = max(1, min(255, round(4e-6 / t) - 1))
    sdadel = max(0, min(15, round(0.5e-6 / t)))
    scldel = max(1, min(15, round(1.25e-6 / t) - 1))
    return presc << 28 | scldel << 20 | sdadel << 16 | sclh << 8 | scll


class I2c:
    def __init__(self, pal, name: str) -> None:
        self.pal = pal
        self.name = name
        self.v2 = has_register(pal, name, "TIMINGR")
        self.family = family(pal)
        self._saved: dict[str, int] = {}
        self._kernel_restore: tuple[str, str, int] | None = None

    def __enter__(self) -> I2c:
        return self

    def __exit__(self, *_exc) -> None:
        self.restore()

    def setup(self) -> None:
        enable_clock(self.pal, self.name)
        if self.v2:
            self._saved = save_regs(self.pal, self.name, ("CR1", "CR2", "TIMINGR"))
            self.pal.write_reg(self.name, "CR1", 0)
            f = self._kernel_hz()
            self.pal.write_reg(self.name, "TIMINGR", timingr_100k(f))
            self.pal.write_reg(self.name, "CR1", V2_PE)
        else:
            from instruments.rcc_helper import detect_pclk1
            self._saved = save_regs(self.pal, self.name, ("CR1", "CR2", "CCR", "TRISE"))
            f = detect_pclk1(self.pal)
            self.pal.write_reg(self.name, "CR1", V1_SWRST)
            self.pal.write_reg(self.name, "CR1", 0)
            mhz = max(2, min(50, f // 1_000_000))
            self.pal.write_reg(self.name, "CR2", mhz)
            self.pal.write_reg(self.name, "CCR", max(4, f // (2 * 100_000)))
            self.pal.write_reg(self.name, "TRISE", mhz + 1)
            self.pal.write_reg(self.name, "CR1", V1_PE)

    def bus_busy(self) -> bool:
        if self.v2:
            return bool(self.pal.read_reg(self.name, "ISR") & V2_BUSY)
        return bool(self.pal.read_reg(self.name, "SR2") & V1_BUSY)

    def probe(self, addr: int, timeout_s: float = 0.05) -> bool:
        """True se o endereço de 7 bits responde com ACK (escrita de 0 bytes)."""
        if self.v2:
            self.pal.write_reg(self.name, "ICR", V2_ICR_ALL)
            self.pal.write_reg(self.name, "CR2", (addr & 0x7F) << 1 | V2_AUTOEND | V2_START)
            wait(lambda: self.pal.read_reg(self.name, "ISR") & V2_STOPF, timeout_s,
                 f"{self.name}: STOP não ocorreu (SCL/SDA presos? pull-ups?)")
            nack = bool(self.pal.read_reg(self.name, "ISR") & V2_NACKF)
            self.pal.write_reg(self.name, "ICR", V2_ICR_ALL)
            return not nack
        cr1 = self.pal.read_reg(self.name, "CR1")
        self.pal.write_reg(self.name, "CR1", cr1 | V1_START)
        wait(lambda: self.pal.read_reg(self.name, "SR1") & V1_SB, timeout_s,
             f"{self.name}: START não gerado (barramento ocupado?)")
        self.pal.write_reg(self.name, "DR", (addr & 0x7F) << 1)
        wait(lambda: self.pal.read_reg(self.name, "SR1") & (V1_ADDR | V1_AF), timeout_s,
             f"{self.name}: sem ADDR/AF após o endereço")
        sr1 = self.pal.read_reg(self.name, "SR1")
        self.pal.read_reg(self.name, "SR2")                      # limpa ADDR
        self.pal.write_reg(self.name, "CR1", self.pal.read_reg(self.name, "CR1") | V1_STOP)
        self.pal.write_reg(self.name, "SR1", sr1 & ~V1_AF)       # limpa AF
        return bool(sr1 & V1_ADDR)

    def scan(self, first: int = 0x08, last: int = 0x77) -> list[int]:
        return [a for a in range(first, last + 1) if self.probe(a)]

    def restore(self) -> None:
        if self._saved:
            self.pal.write_reg(self.name, "CR1", 0)
            restore_regs(self.pal, self.name, {k: v for k, v in self._saved.items() if k != "CR1"})
            self.pal.write_reg(self.name, "CR1", self._saved["CR1"])
            self._saved = {}
        if self._kernel_restore:
            reg, field, old = self._kernel_restore
            self.pal.modify_field("RCC", reg, field, old)
            self._kernel_restore = None

    def _kernel_hz(self) -> int:
        if self.family != "H7" or self.name.upper() == "I2C4":
            from instruments.rcc_helper import detect_pclk1
            return detect_pclk1(self.pal)
        f, old = select_hsi_kernel(self.pal, "D2CCIP2R", "I2C123SEL", 0b10)
        self._kernel_restore = ("D2CCIP2R", "I2C123SEL", old)
        return f
