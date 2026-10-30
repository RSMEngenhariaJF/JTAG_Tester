"""Núcleo do testbench: Driver, Monitor, Estímulo, Decisão e o teste composto.

Um teste composto separa quatro papéis:

    Estímulo  — o QUE fazer, passo a passo (independe de hardware)
    Driver    — aplica o valor do passo no hardware (ex.: saída GPIO)
    Monitor   — observa o hardware a cada passo (ex.: entrada GPIO, ODR)
    Decisão   — compara o observado com o esperado e dá o veredito

Fluxo de Testbench.run():
    setup dos drivers → setup dos monitores → para cada passo do estímulo:
    aplica os valores nos drivers, espera, amostra os monitores (Observation)
    → teardown dos monitores → teardown dos drivers (restaura o hardware)
    → cada Decisão avalia o Trace e devolve um Verdict (com métricas).

ComposedTest é um BuiltinTest comum: Plano de testes, parâmetros, relatório e
perfil de critérios funcionam sem mudança.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from tests_builtin.base import BuiltinTest, TestResult

# ── Componentes ───────────────────────────────────────────────────────────────


class Driver(ABC):
    """Aplica valores no hardware. Deve restaurar o estado em teardown()."""

    name: str = ""

    def setup(self, pal) -> None:  # noqa: B027 — opcional nas subclasses
        """Prepara o hardware (salva o estado original)."""

    @abstractmethod
    def apply(self, pal, value: Any) -> None:
        """Aplica um valor do estímulo."""

    def teardown(self, pal) -> None:  # noqa: B027
        """Restaura o hardware."""


class Monitor(ABC):
    """Observa o hardware. Deve restaurar o estado em teardown()."""

    name: str = ""

    def setup(self, pal) -> None:  # noqa: B027
        """Prepara a observação (salva o estado original)."""

    @abstractmethod
    def sample(self, pal) -> Any:
        """Lê o valor observado neste instante."""

    def teardown(self, pal) -> None:  # noqa: B027
        """Restaura o hardware."""


@dataclass
class Step:
    """Um passo do estímulo: valores por driver, espera e se amostra os monitores."""

    drive:  dict[str, Any] = field(default_factory=dict)   # nome do driver → valor
    wait_s: float = 0.0
    label:  str = ""
    sample: bool = True


class Stimulus(ABC):
    @abstractmethod
    def steps(self) -> Iterable[Step]:
        """Passos do estímulo, em ordem."""


@dataclass
class Observation:
    index:    int
    label:    str
    t_s:      float                       # instante desde o início do estímulo
    driven:   dict[str, Any]              # valores aplicados neste passo
    observed: dict[str, Any]              # leitura de cada monitor


class Trace:
    """Histórico do estímulo: o que foi aplicado e o que foi observado."""

    def __init__(self) -> None:
        self.observations: list[Observation] = []

    def __len__(self) -> int:
        return len(self.observations)

    def series(self, monitor: str) -> list[Any]:
        return [o.observed[monitor] for o in self.observations if monitor in o.observed]

    def pairs(self, driver: str, monitor: str) -> list[tuple[Any, Any, Observation]]:
        """(valor aplicado, valor observado, observação) dos passos em que o driver atuou."""
        return [(o.driven[driver], o.observed[monitor], o) for o in self.observations
                if driver in o.driven and monitor in o.observed]


@dataclass
class Verdict:
    """Resultado de uma decisão. ok=None: só informativo (não reprova)."""

    ok:           bool | None
    message:      str
    measurements: list = field(default_factory=list)        # Measurement


class Decision(ABC):
    name: str = ""

    @abstractmethod
    def evaluate(self, trace: Trace) -> Verdict:
        """Avalia o histórico e devolve o veredito."""


# ── Bancada ───────────────────────────────────────────────────────────────────


class Testbench:
    __test__ = False

    def __init__(self, drivers: Iterable[Driver] = (), monitors: Iterable[Monitor] = (),
                 stimulus: Stimulus | None = None, decisions: Iterable[Decision] = ()) -> None:
        self.drivers = {d.name: d for d in drivers}
        self.monitors = {m.name: m for m in monitors}
        self.stimulus = stimulus
        self.decisions = list(decisions)

    def run(self, pal) -> tuple[Trace, list[Verdict]]:
        trace = Trace()
        ready: list[Driver | Monitor] = []
        try:
            for comp in (*self.drivers.values(), *self.monitors.values()):
                comp.setup(pal)
                ready.append(comp)
            t0 = time.perf_counter()
            for i, step in enumerate(self.stimulus.steps() if self.stimulus else ()):
                for name, value in step.drive.items():
                    self.drivers[name].apply(pal, value)
                if step.wait_s:
                    time.sleep(step.wait_s)
                if step.sample:
                    observed = {n: m.sample(pal) for n, m in self.monitors.items()}
                    trace.observations.append(Observation(
                        i, step.label, time.perf_counter() - t0, dict(step.drive), observed))
        finally:
            for comp in reversed(ready):          # monitores, depois drivers
                comp.teardown(pal)
        return trace, [d.evaluate(trace) for d in self.decisions]


class ComposedTest(BuiltinTest):
    """BuiltinTest montado por estímulo + drivers + monitores + decisões.

    Subclasses implementam build() (e, se quiserem, summary()). Parâmetros do
    Plano de testes chegam em self.p, como em qualquer BuiltinTest.
    """

    @abstractmethod
    def build(self) -> Testbench:
        """Monta a bancada para esta execução."""

    def summary(self, trace: Trace, verdicts: list[Verdict]) -> str:
        """Mensagem do resultado. Padrão: mensagens das decisões."""
        return "; ".join(v.message for v in verdicts if v.message) or f"{len(trace)} amostra(s)"

    def _run(self, pal) -> TestResult:
        from core.analysis import MeasurementSet

        self.trace, verdicts = self.build().run(pal)
        from tests_builtin.audit import trace_rows
        audit = self.__dict__.setdefault("audit", {})       # registro para auditoria
        audit["passos"] = trace_rows(self.trace)
        audit["decisoes"] = [
            ["INFO" if v.ok is None else ("PASS" if v.ok else "FAIL"), v.message]
            for v in verdicts]
        ms = MeasurementSet()
        for v in verdicts:
            for m in v.measurements:
                ms.add(m)                      # aplica o perfil de critérios
        # O perfil pode ter mudado limites: a métrica vence o veredito da decisão
        failed = [v for v in verdicts if v.ok is False and not v.measurements]
        msg = self.summary(self.trace, verdicts)
        kwargs = {"measurements": ms} if ms else {}
        if failed or not ms.all_within_limits():
            return self._fail(msg, **kwargs)
        return self._pass(msg, **kwargs)
