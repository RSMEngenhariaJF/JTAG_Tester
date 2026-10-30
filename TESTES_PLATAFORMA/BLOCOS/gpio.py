"""Blocos de GPIO — nível de entrada, pull-up/pull-down (curto) e loopback saída→entrada.

Cada bloco é uma bancada modular (src/testbench): estímulo + drivers + monitores
+ decisões. Os pinos vêm do Pinout do projeto (sinais escolhidos no Plano de
testes) e o estado original de cada pino é restaurado no fim.
"""

from testbench import ComposedTest, Step, Stimulus, Testbench
from testbench.decision import Expect, FollowsDrive, Report
from testbench.gpio import GpioInputMonitor, GpioOutputDriver, GpioPullDriver
from testbench.stimulus import Levels, Sample
from tests_builtin.params import Bool, Choice, Signals


def _ativo(v) -> str:
    return "ativo" if v else "inativo"


class NivelEntrada(ComposedTest):
    """Monitor de entrada por pino + decisão de nível esperado (ou só registro)."""

    name        = "GPIO — Nível de entrada"
    category    = "GPIO"
    description = "Lê as entradas escolhidas e compara com o nível esperado (respeita ativo-baixo)."
    params = {
        "pinos":    Signals("Pinos", types=("GPIO", "EXTI")),
        "esperado": Choice("Esperado", ("ativo", "inativo", "qualquer (só registra)")),
        "pull":     Choice("Pull durante a leitura", ("manter", "nenhum", "pull-up", "pull-down")),
        "forcar_entrada": Bool("Configurar como entrada", True,
                               help="Desmarcado: lê o IDR sem mexer no modo do pino"),
    }

    def build(self) -> Testbench:
        monitors = [GpioInputMonitor(s, configure=self.p.forcar_entrada, pull=self.p.pull)
                    for s in self.p.pinos]
        if self.p.esperado.startswith("qualquer"):
            decisions = [Report(m.name, _ativo, label=s.name)
                         for m, s in zip(monitors, self.p.pinos, strict=True)]
        else:
            alvo = self.p.esperado == "ativo"
            decisions = [Expect(m.name, alvo, label=s.name, describe=_ativo,
                                metric="gpio_nivel_divergente")
                         for m, s in zip(monitors, self.p.pinos, strict=True)]
        return Testbench(monitors=monitors, stimulus=Sample(1), decisions=decisions)

    def summary(self, trace, verdicts) -> str:
        falhas = [v.message for v in verdicts if v.ok is False]
        if falhas:
            return f"esperado {self.p.esperado}: " + "; ".join(falhas)
        return ", ".join(v.message for v in verdicts)


class _PullUpDown(Stimulus):
    """Todos os pinos com pull-up, depois todos com pull-down."""

    def __init__(self, drivers, wait_s: float = 0.002) -> None:
        self.drivers, self.wait_s = drivers, wait_s

    def steps(self):
        for pull in ("pull-up", "pull-down"):
            yield Step({d: pull for d in self.drivers}, self.wait_s, pull)


class PullCurto(ComposedTest):
    """Driver de pull + monitor de entrada; decisão: o nível segue o pull."""

    name        = "GPIO — Pull-up/pull-down (curto)"
    category    = "GPIO"
    description = ("Com pull-up interno o pino deve ler 1; com pull-down, 0. Acusa curto a "
                   "GND/VCC ou driver externo forte. Use em pinos sem carga forte.")
    params = {
        "pinos": Signals("Pinos",
                         types=("GPIO", "EXTI", "UART", "SPI", "I2C", "CAN", "PWM", "TIM")),
    }

    def build(self) -> Testbench:
        drivers = [GpioPullDriver(s) for s in self.p.pinos]
        monitors = [GpioInputMonitor(s, configure=False, raw=True) for s in self.p.pinos]
        return Testbench(
            drivers=drivers,
            monitors=monitors,
            stimulus=_PullUpDown([d.name for d in drivers]),
            decisions=[Expect(m.name, lambda o: 1 if o.label == "pull-up" else 0,
                              label=s.name, metric="gpio_pull_divergente")
                       for m, s in zip(monitors, self.p.pinos, strict=True)],
        )

    def summary(self, trace, verdicts) -> str:
        ok, falhas = [], []
        for s in self.p.pinos:
            up, down = trace.series(f"in:{s.name}")
            if (up, down) == (1, 0):
                ok.append(s.name)
            else:
                causa = ("preso em 0 (curto a GND?)" if (up, down) == (0, 0) else
                         "preso em 1 (curto a VCC?)" if (up, down) == (1, 1) else "invertido")
                falhas.append(f"{s} {causa}")
        if falhas:
            return "; ".join(falhas)
        return f"{len(ok)} pino(s) seguem o pull: {', '.join(ok)}"


class LoopbackGpio(ComposedTest):
    """Driver de saída + monitor de entrada; decisão: a entrada acompanha a saída."""

    name        = "GPIO — Loopback saída→entrada"
    category    = "GPIO"
    description = "Aciona a saída em 0 e 1 e confere a entrada ligada a ela (fio ou circuito)."
    params = {
        "saida":   Signals("Saída", types=("GPIO",), max_count=1),
        "entrada": Signals("Entrada", types=("GPIO", "EXTI"), max_count=1),
        "invertido": Bool("Circuito inverte o nível", False),
    }

    def build(self) -> Testbench:
        out, inp = self.p.saida[0], self.p.entrada[0]
        drv = GpioOutputDriver(out, raw=True)
        mon = GpioInputMonitor(inp, configure=True, pull="nenhum", raw=True)
        return Testbench([drv], [mon], Levels(drv.name, [0, 1, 0]),
                         [FollowsDrive(mon.name, drv.name, invert=self.p.invertido,
                                       label=f"{out.name}→{inp.name}",
                                       metric="gpio_loopback_divergente")])

    def summary(self, trace, verdicts) -> str:
        out, inp = self.p.saida[0], self.p.entrada[0]
        lido = {d: o for d, o, _ in trace.pairs(f"out:{out.name}", f"in:{inp.name}")}
        texto = f"{out.name}→{inp.name}: 0→{lido.get(0)}, 1→{lido.get(1)}"
        if verdicts[0].ok:
            return texto
        esp = (1, 0) if self.p.invertido else (0, 1)
        return f"{texto} (esperado 0→{esp[0]}, 1→{esp[1]})"
