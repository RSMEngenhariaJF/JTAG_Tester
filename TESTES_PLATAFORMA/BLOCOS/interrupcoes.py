"""Bloco de interrupção externa (EXTI): pino → EXTI → NVIC.

Estímulo por software (SWIER) valida a configuração EXTI/NVIC sem tocar no
pino; "borda real" usa o próprio pino como saída e gera a borda, validando
também o caminho de entrada do pino. Com "parar o núcleo", o firmware não trata
(e não limpa) a interrupção antes da leitura; ele volta a rodar no fim.
"""

import time

from hal.common import restore_pin, set_input, set_output, snapshot_pin
from hal.exti import Exti, irq_of_line
from tests_builtin.base import BuiltinTest, TestResult
from tests_builtin.params import Bool, Choice, Signals


class InterrupcaoExterna(BuiltinTest):
    name        = "Interrupção — EXTI de um pino"
    category    = "Interrupções"
    description = "Dispara a linha EXTI do pino e confere a pendência no EXTI e no NVIC."
    params = {
        "pino":     Signals("Pino", types=("GPIO", "EXTI"), max_count=1),
        "borda":    Choice("Borda", ("subida", "descida", "ambas")),
        "estimulo": Choice("Estímulo", ("software (SWIER)", "borda real no pino (vira saída)")),
        "parar_nucleo": Bool("Parar o núcleo durante a medida", True,
                             help="Evita que o firmware trate e limpe a interrupção"),
    }

    def _run(self, pal) -> TestResult:
        s = self.p.pino[0]
        line = s.pin
        mem = pal.mem
        halted_here = False
        if self.p.parar_nucleo and hasattr(mem, "halt") and not mem.is_halted():
            mem.halt()
            halted_here = True
        snap = snapshot_pin(pal, s.port, s.pin)
        exti = Exti(pal)
        try:
            exti.setup(s.port, line, rising=self.p.borda in ("subida", "ambas"),
                       falling=self.p.borda in ("descida", "ambas"))
            if self.p.estimulo.startswith("software"):
                set_input(pal, s.port, s.pin)
                exti.software_trigger(line)
            else:
                inicial = 1 if self.p.borda == "descida" else 0
                set_output(pal, s.port, s.pin, inicial)
                time.sleep(0.001)
                exti.clear(line)
                set_output(pal, s.port, s.pin, 1 - inicial)        # a borda
            time.sleep(0.001)
            pend_exti, pend_nvic = exti.pending(line), exti.nvic_pending(line)
            exti.clear(line)
        finally:
            exti.restore()
            restore_pin(pal, snap)
            if halted_here:
                mem.resume()
        irq = irq_of_line(line)
        msg = (f"{s} EXTI{line} ({self.p.borda}, {self.p.estimulo.split(' (')[0]}): "
               f"pendência EXTI={'sim' if pend_exti else 'não'}, "
               f"NVIC IRQ{irq}={'sim' if pend_nvic else 'não'}")
        if pend_exti and pend_nvic:
            return self._pass(msg)
        return self._fail(msg)
