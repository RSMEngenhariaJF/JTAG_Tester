"""Interrupção externa (EXTI) de um pino: pendência no EXTI e no NVIC.

Caminho testado: pino → SYSCFG.EXTICR → EXTI (borda) → pendência EXTI → NVIC.
O núcleo pode ser parado durante a medida para o firmware não tratar (e limpar)
a interrupção antes da leitura.
"""

from __future__ import annotations

from dataclasses import dataclass

from hal.common import enable_clock, has_register

NVIC_ISPR = 0xE000E200
NVIC_ICPR = 0xE000E280
# Número do IRQ por linha EXTI — igual no F4 e no H7 (tabela de vetores)
_IRQ = {0: 6, 1: 7, 2: 8, 3: 9, 4: 10}


def irq_of_line(line: int) -> int:
    if line in _IRQ:
        return _IRQ[line]
    return 23 if line <= 9 else 40           # EXTI9_5 / EXTI15_10


@dataclass
class _Regs:
    rtsr: str
    ftsr: str
    swier: str
    imr: str
    pr: str


class Exti:
    def __init__(self, pal) -> None:
        self.pal = pal
        self.h7 = has_register(pal, "EXTI", "CPUPR1")
        self.r = (_Regs("RTSR1", "FTSR1", "SWIER1", "CPUIMR1", "CPUPR1") if self.h7
                  else _Regs("RTSR", "FTSR", "SWIER", "IMR", "PR"))
        self._saved: dict[tuple[str, str], int] = {}

    def setup(self, port: str, line: int, rising: bool, falling: bool) -> None:
        enable_clock(self.pal, "SYSCFG")
        cr = f"EXTICR{line // 4 + 1}"
        port_idx = ord(port[-1].upper()) - ord("A")
        self._save("SYSCFG", cr)
        for reg in (self.r.rtsr, self.r.ftsr, self.r.imr):
            self._save("EXTI", reg)
        self.pal.modify_field("SYSCFG", cr, f"EXTI{line}", port_idx)
        self._set_bit(self.r.rtsr, line, rising)
        self._set_bit(self.r.ftsr, line, falling)
        self._set_bit(self.r.imr, line, True)
        self.clear(line)

    def software_trigger(self, line: int) -> None:
        self.pal.write_reg("EXTI", self.r.swier, 1 << line)

    def pending(self, line: int) -> bool:
        return bool(self.pal.read_reg("EXTI", self.r.pr) >> line & 1)

    def nvic_pending(self, line: int) -> bool:
        irq = irq_of_line(line)
        return bool(self.pal.mem.read_mem32(NVIC_ISPR + 4 * (irq // 32)) >> (irq % 32) & 1)

    def clear(self, line: int) -> None:
        self.pal.write_reg("EXTI", self.r.pr, 1 << line)            # escrever 1 limpa
        irq = irq_of_line(line)
        self.pal.mem.write_mem32(NVIC_ICPR + 4 * (irq // 32), 1 << (irq % 32))

    def restore(self) -> None:
        for (periph, reg), value in self._saved.items():
            self.pal.write_reg(periph, reg, value)
        self._saved = {}

    def _save(self, periph: str, reg: str) -> None:
        self._saved.setdefault((periph, reg), self.pal.read_reg(periph, reg))

    def _set_bit(self, reg: str, bit: int, on: bool) -> None:
        v = self.pal.read_reg("EXTI", reg)
        self.pal.write_reg("EXTI", reg, v | 1 << bit if on else v & ~(1 << bit))
