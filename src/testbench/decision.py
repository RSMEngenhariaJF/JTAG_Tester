"""Blocos de decisão — comparam o observado com o esperado.

Cada decisão registra a contagem de divergências como métrica (limite padrão 0).
O perfil de critérios do projeto pode trocar esse limite pelo nome da métrica
(ex.: "gpio_divergencias" vale para "gpio_divergencias_led").
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.analysis.metrics import Measurement
from testbench.core import Decision, Observation, Trace, Verdict


def _measure(metric: str, bad: int, total: int, what: str) -> Measurement:
    return Measurement(metric, float(bad), "amostras", limit_max=0.0,
                       description=f"{bad} de {total} amostras {what}")


class FollowsDrive(Decision):
    """O monitor acompanha o valor aplicado pelo driver (opcionalmente invertido)."""

    def __init__(self, monitor: str, driver: str, *, invert: bool = False,
                 metric: str = "gpio_divergencias", label: str = "") -> None:
        self.monitor, self.driver, self.invert = monitor, driver, invert
        self.metric, self.label = metric, label or monitor.split(":")[-1]
        self.name = f"{driver}→{monitor}"

    def evaluate(self, trace: Trace) -> Verdict:
        pairs = trace.pairs(self.driver, self.monitor)
        bad = [(d, o) for d, o, _ in pairs if bool(o) != (bool(d) ^ self.invert)]
        m = _measure(f"{self.metric}_{self.label}", len(bad), len(pairs),
                     "fora do valor aplicado")
        if not pairs:
            return Verdict(False, f"{self.label}: nenhuma amostra")
        if bad:
            d, o = bad[0]
            return Verdict(False, f"{self.label}: {len(bad)}/{len(pairs)} divergências "
                                  f"(aplicado {int(bool(d))}, lido {int(bool(o))})", [m])
        return Verdict(True, f"{self.label}: {len(pairs)} amostras acompanharam", [m])


class Expect(Decision):
    """Cada amostra do monitor deve ser igual ao esperado.

    expected: valor fixo ou função(Observation) → valor esperado naquele passo.
    """

    def __init__(self, monitor: str, expected: Any | Callable[[Observation], Any], *,
                 metric: str = "gpio_divergencias", label: str = "",
                 describe: Callable[[Any], str] = str) -> None:
        self.monitor, self.expected, self.metric = monitor, expected, metric
        self.label = label or monitor.split(":")[-1]
        self.describe = describe
        self.name = f"esperado:{monitor}"

    def evaluate(self, trace: Trace) -> Verdict:
        obs = [o for o in trace.observations if self.monitor in o.observed]
        exp = (lambda o: self.expected(o)) if callable(self.expected) else (lambda o: self.expected)
        bad = [o for o in obs if o.observed[self.monitor] != exp(o)]
        m = _measure(f"{self.metric}_{self.label}", len(bad), len(obs), "diferentes do esperado")
        if not obs:
            return Verdict(False, f"{self.label}: nenhuma amostra")
        if bad:
            o = bad[0]
            return Verdict(False, f"{self.label}: {self.describe(o.observed[self.monitor])} em "
                                  f"'{o.label}' (esperado {self.describe(exp(o))})", [m])
        return Verdict(True, f"{self.label}={self.describe(obs[-1].observed[self.monitor])}", [m])


class Report(Decision):
    """Só registra o último valor do monitor (não reprova)."""

    def __init__(self, monitor: str, describe: Callable[[Any], str] = str, label: str = "") -> None:
        self.monitor, self.describe = monitor, describe
        self.label = label or monitor.split(":")[-1]
        self.name = f"registro:{monitor}"

    def evaluate(self, trace: Trace) -> Verdict:
        series = trace.series(self.monitor)
        if not series:
            return Verdict(False, f"{self.label}: nenhuma amostra")
        return Verdict(None, f"{self.label}={self.describe(series[-1])}")


class WithinTolerance(Decision):
    """O valor observado fica dentro de nominal ± tolerância (% ou absoluta).

    key: com monitor que devolve dict, escolhe o campo (ex.: "SYSCLK").
    step: avalia só as amostras do passo com esse rótulo (ex.: "HSE direto").
    A métrica leva nominal e limites; o perfil de critérios pode trocá-los.
    """

    def __init__(self, monitor: str, nominal: float, *, tol_pct: float | None = None,
                 tol_abs: float | None = None, key: str | None = None, metric: str = "",
                 unit: str = "", label: str = "", fmt: Callable[[float], str] = "{:.6g}".format,
                 step: str | None = None) -> None:
        if tol_pct is None and tol_abs is None:
            raise ValueError("informe tol_pct ou tol_abs")
        self.monitor, self.nominal, self.key, self.unit, self.fmt = monitor, nominal, key, unit, fmt
        self.step = step
        self.tol = tol_abs if tol_abs is not None else abs(nominal) * tol_pct / 100
        self.label = label or key or monitor.split(":")[-1]
        self.metric = metric or self.label.lower()
        self.name = f"tolerancia:{monitor}:{key or ''}"

    def evaluate(self, trace: Trace) -> Verdict:
        raw = [o.observed[self.monitor] for o in trace.observations
               if self.monitor in o.observed and self.step in (None, o.label)]
        series = [v.get(self.key) if self.key is not None and isinstance(v, dict) else v
                  for v in raw]
        series = [v for v in series if v is not None]
        if not series:
            return Verdict(False, f"{self.label}: nenhuma amostra")
        value = float(series[-1])
        lo, hi = self.nominal - self.tol, self.nominal + self.tol
        m = Measurement(self.metric, value, self.unit, samples=[float(v) for v in series],
                        limit_min=lo, limit_max=hi, nominal=self.nominal,
                        description=f"{self.label}: nominal {self.fmt(self.nominal)} "
                                    f"± {self.fmt(self.tol)} {self.unit}".rstrip())
        ok = lo <= value <= hi
        shown = self.fmt(value)
        if self.unit and not shown.endswith(self.unit):     # fmt pode já trazer a unidade
            shown += f" {self.unit}"
        txt = f"{self.label}={shown}"
        return Verdict(ok, txt if ok else f"{txt} (esperado {self.fmt(self.nominal)} "
                                          f"± {self.fmt(self.tol)})", [m])


class MatchesDrive(Decision):
    """O monitor devolve exatamente o valor aplicado pelo driver (ex.: eco de byte)."""

    def __init__(self, monitor: str, driver: str, *, metric: str = "divergencias",
                 label: str = "", describe: Callable[[Any], str] = repr) -> None:
        self.monitor, self.driver, self.metric, self.describe = monitor, driver, metric, describe
        self.label = label or monitor.split(":")[-1]
        self.name = f"igual:{driver}→{monitor}"

    def evaluate(self, trace: Trace) -> Verdict:
        pairs = trace.pairs(self.driver, self.monitor)
        bad = [(d, o) for d, o, _ in pairs if o != d]
        m = _measure(f"{self.metric}_{self.label}", len(bad), len(pairs), "diferentes do enviado")
        if not pairs:
            return Verdict(False, f"{self.label}: nenhuma amostra")
        if bad:
            d, o = bad[0]
            return Verdict(False, f"{self.label}: {len(bad)}/{len(pairs)} diferentes (enviado "
                                  f"{self.describe(d)}, recebido {self.describe(o)})", [m])
        return Verdict(True, f"{self.label}: {len(pairs)}/{len(pairs)} iguais", [m])


class Satisfies(Decision):
    """Cada amostra do monitor satisfaz uma condição (ex.: o pino comutou)."""

    def __init__(self, monitor: str, predicate: Callable[[Any], bool], *, metric: str,
                 label: str = "", what: str = "fora da condição",
                 describe: Callable[[Any], str] = str) -> None:
        self.monitor, self.predicate, self.metric = monitor, predicate, metric
        self.label, self.what, self.describe = label or monitor.split(":")[-1], what, describe
        self.name = f"condicao:{monitor}"

    def evaluate(self, trace: Trace) -> Verdict:
        obs = [o for o in trace.observations if self.monitor in o.observed]
        bad = [o for o in obs if not self.predicate(o.observed[self.monitor])]
        m = _measure(f"{self.metric}_{self.label}", len(bad), len(obs), self.what)
        if not obs:
            return Verdict(False, f"{self.label}: nenhuma amostra")
        if bad:
            return Verdict(False, f"{self.label}: {self.describe(bad[0].observed[self.monitor])} "
                                  f"em '{bad[0].label}' ({self.what})", [m])
        return Verdict(True, f"{self.label}: {self.describe(obs[-1].observed[self.monitor])}",
                       [m])
