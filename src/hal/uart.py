"""USART/UART: v1 (F4 — SR/DR) e v2 (H7 — ISR/TDR/RDR), byte a byte via PAL.

Clock: F4 usa o PCLK do barramento (lido do RCC); H7 troca a fonte do kernel
para o HSI (64 MHz / HSIDIV) durante o teste e restaura no fim.

RS485 (só v2): setup(..., de=True) liga o Driver Enable por hardware (CR3.DEM)
no pino DE do periférico; DEAT/DEDT dão a antecedência/atraso do DE em
amostras de 1/16 de bit (RM0433 §48.5.20).
"""

from __future__ import annotations

import logging
import re
import time

from hal.common import (
    enable_clock,
    family,
    has_register,
    restore_regs,
    save_regs,
    select_hsi_kernel,
    wait,
)

log = logging.getLogger("hal.uart")

# Bits comuns (RM0390 / RM0433)
CR1_UE_V1, CR1_UE_V2 = 1 << 13, 1 << 0
CR1_TE, CR1_RE = 1 << 3, 1 << 2
CR3_HDSEL = 1 << 3
CR3_DEM, CR3_DEP = 1 << 14, 1 << 15
CR1_DEDT_SHIFT, CR1_DEAT_SHIFT = 16, 21
ST_TXE, ST_TC, ST_RXNE = 1 << 7, 1 << 6, 1 << 5
ST_ORE, ST_NF, ST_FE, ST_PE = 1 << 3, 1 << 2, 1 << 1, 1 << 0
ISR_TEACK, ISR_REACK = 1 << 21, 1 << 22

_H7_KERNEL = {"16": ("D2CCIP2R", "USART16SEL"), "other": ("D2CCIP2R", "USART234578SEL")}
_HSI_CODE = 0b011


class Uart:
    """Uso: with Uart(pal, "USART3") as u: u.setup(115200); u.write(0x55); u.read()"""

    def __init__(self, pal, name: str) -> None:
        self.pal = pal
        self.name = name
        self.v2 = has_register(pal, name, "ISR")
        self.family = family(pal)
        self._saved: dict[str, int] = {}
        self._kernel_restore: tuple[str, str, int] | None = None
        self.f_ck = 0
        self.errors = {"overrun": 0, "framing": 0, "noise": 0, "parity": 0}

    # ── Ciclo de vida ─────────────────────────────────────────────────────

    def __enter__(self) -> Uart:
        return self

    def __exit__(self, *_exc) -> None:
        self.restore()

    def setup(self, baud: int, *, half_duplex: bool = False, de: bool = False,
              de_active_low: bool = False, de_time: int = 8) -> float:
        """Configura 8N1 com OVER16; retorna o baud real (divisor inteiro).

        de: Driver Enable de RS485 por hardware (pino DE em AF); de_time em
        1/16 de bit, usado para DEAT e DEDT (0 a 31).
        """
        if de and not self.v2:
            raise ValueError(f"{self.name}: DE por hardware só existe na USART v2 (H7/G4/L4)")
        enable_clock(self.pal, self.name)
        self._saved = save_regs(self.pal, self.name, ("CR1", "CR2", "CR3", "BRR", "PRESC"))
        self.pal.write_reg(self.name, "CR1", 0)
        self.f_ck = self._kernel_hz()
        div = round(self.f_ck / baud)
        if div < 16:
            raise ValueError(f"{baud} baud acima do máximo ({self.f_ck // 16}) "
                             f"com f_ck={self.f_ck}")
        self.pal.write_reg(self.name, "BRR", div)
        self.pal.write_reg(self.name, "CR2", 0)
        cr3 = (CR3_HDSEL if half_duplex else 0) | (CR3_DEM if de else 0) \
            | (CR3_DEP if de and de_active_low else 0)
        self.pal.write_reg(self.name, "CR3", cr3)
        if self.v2 and has_register(self.pal, self.name, "PRESC"):
            self.pal.write_reg(self.name, "PRESC", 0)
        ue = CR1_UE_V2 if self.v2 else CR1_UE_V1
        t = (de_time & 31) if de else 0
        timing = t << CR1_DEAT_SHIFT | t << CR1_DEDT_SHIFT
        self.pal.write_reg(self.name, "CR1", timing)        # DEAT/DEDT só com UE=0
        self.pal.write_reg(self.name, "CR1", timing | ue | CR1_TE | CR1_RE)
        if self.v2:
            wait(lambda: self._status() & (ISR_TEACK | ISR_REACK) == ISR_TEACK | ISR_REACK,
                 0.2, f"{self.name}: TEACK/REACK não subiram")
        # Ao ligar TE a UART envia um quadro ocioso (10 bits em 1, sem DE). O 1º byte
        # escrito durante ele se perde/corrompe no half-duplex (visto na placa CT, UART5)
        # e o DE não aparece. O TC já vem em 1 do reset (não serve para esperar esse
        # quadro): espera o tempo de um quadro (11 bits) antes de liberar a UART.
        time.sleep(11 / (self.f_ck / div) + 0.0005)
        self.flush()
        log.info("%s: %.0f baud (f_ck %.0f Hz, BRR %d)%s%s", self.name, self.f_ck / div,
                 self.f_ck, div, ", half-duplex" if half_duplex else "",
                 f", DE por hardware ({'ativo-baixo' if de_active_low else 'ativo-alto'})"
                 if de else "")
        return self.f_ck / div

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

    # ── Dados ─────────────────────────────────────────────────────────────

    def write(self, byte: int, timeout_s: float = 0.2) -> None:
        wait(lambda: self._status() & ST_TXE, timeout_s, f"{self.name}: TXE não subiu")
        self.pal.write_reg(self.name, "TDR" if self.v2 else "DR", byte & 0xFF)

    def read(self, timeout_s: float = 0.2) -> int:
        wait(lambda: self._status() & ST_RXNE, timeout_s,
             f"{self.name}: nenhum byte recebido em {timeout_s * 1000:.0f} ms")
        st = self._status()
        self._count_errors(st)
        value = self.pal.read_reg(self.name, "RDR" if self.v2 else "DR") & 0xFF
        if self.v2 and st & (ST_ORE | ST_NF | ST_FE | ST_PE):
            self.pal.write_reg(self.name, "ICR", st & (ST_ORE | ST_NF | ST_FE | ST_PE))
        return value

    def wait_tc(self, timeout_s: float = 0.5) -> None:
        """Espera o fim da transmissão (TC): último stop bit saiu e o DE caiu."""
        wait(lambda: self._status() & ST_TC, timeout_s, f"{self.name}: TC não subiu")

    def flush(self) -> None:
        for _ in range(32):
            if not self._status() & ST_RXNE:
                break
            self.pal.read_reg(self.name, "RDR" if self.v2 else "DR")
        if self.v2:
            self.pal.write_reg(self.name, "ICR", ST_ORE | ST_NF | ST_FE | ST_PE)

    # ── Internos ──────────────────────────────────────────────────────────

    def _status(self) -> int:
        return self.pal.read_reg(self.name, "ISR" if self.v2 else "SR")

    def _count_errors(self, st: int) -> None:
        for bit, key in ((ST_ORE, "overrun"), (ST_FE, "framing"), (ST_NF, "noise"),
                         (ST_PE, "parity")):
            if st & bit:
                self.errors[key] += 1

    def _kernel_hz(self) -> int:
        if self.family == "H7":
            n = re.search(r"\d+", self.name).group()
            reg, field = _H7_KERNEL["16" if n in ("1", "6") else "other"]
            f, old = select_hsi_kernel(self.pal, reg, field, _HSI_CODE)
            self._kernel_restore = (reg, field, old)
            return f
        from instruments.rcc_helper import detect_pclk1, detect_pclk2
        apb2 = self.name.upper() in ("USART1", "USART6")
        return detect_pclk2(self.pal) if apb2 else detect_pclk1(self.pal)
