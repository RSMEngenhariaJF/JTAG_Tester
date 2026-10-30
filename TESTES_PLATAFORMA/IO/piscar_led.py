"""Teste genérico — pisca saídas digitais escolhidas no "Plano de testes" do projeto.

Montado como bancada modular (src/testbench):
    estímulo  Toggle          — liga/desliga N vezes (um pino por vez ou todos juntos)
    driver    GpioOutputDriver — um por pino: aplica o nível (respeita ativo-baixo)
    monitor   GpioLatchMonitor — um por pino: lê o ODR a cada passo
    decisão   FollowsDrive     — o ODR acompanhou o que foi aplicado?

A lógica não conhece nenhum pino: os sinais (ex.: "led", "rele_1") vêm do plano,
resolvidos pelo Pinout do projeto ativo. Os pinos são restaurados no fim.
"""

from testbench import ComposedTest, Testbench
from testbench.decision import FollowsDrive
from testbench.gpio import GpioLatchMonitor, GpioOutputDriver
from testbench.stimulus import Toggle
from tests_builtin.params import Bool, Int, Signals


class PiscarLed(ComposedTest):
    name        = "Piscar LED"
    category    = "GPIO"
    description = "Pisca as saídas escolhidas (conferindo o ODR) e restaura os pinos."
    params = {
        "pinos":      Signals("Pinos", types=("GPIO",),
                              help="Saídas digitais do projeto que vão piscar"),
        "ciclos":     Int("Ciclos", 3, minimum=1, maximum=50),
        "periodo_ms": Int("Período", 250, minimum=20, maximum=5000, unit="ms",
                          help="Duração de um ciclo aceso + apagado"),
        "sequencial": Bool("Um pino por vez", True,
                           help="Desmarcado: todos piscam juntos"),
    }

    def build(self) -> Testbench:
        drivers = [GpioOutputDriver(s, initial=False) for s in self.p.pinos]
        monitors = [GpioLatchMonitor(s) for s in self.p.pinos]
        return Testbench(
            drivers=drivers,
            monitors=monitors,
            stimulus=Toggle([d.name for d in drivers], self.p.ciclos,
                            self.p.periodo_ms / 1000, self.p.sequencial),
            decisions=[FollowsDrive(m.name, d.name, label=s.name)
                       for d, m, s in zip(drivers, monitors, self.p.pinos, strict=True)],
        )

    def summary(self, trace, verdicts) -> str:
        if all(v.ok for v in verdicts):
            nomes = ", ".join(s.name for s in self.p.pinos)
            return f"{len(self.p.pinos)} saída(s) piscaram {self.p.ciclos}x: {nomes}"
        return "; ".join(v.message for v in verdicts if v.ok is False)
