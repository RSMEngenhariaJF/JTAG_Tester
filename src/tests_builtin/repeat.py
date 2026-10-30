"""Repetição de um teste do plano (repetibilidade).

RepeatedTest roda o mesmo teste N vezes (instância nova a cada vez, mesmos
parâmetros) e devolve um único resultado:

    status    PASS só se todas as repetições passaram; ERROR se todas deram erro;
              SKIP se todas foram puladas; senão FAIL
    mensagem  "8/10 PASS em 10 repetições; falharam: 3, 7 (...) | última: ..."
    métricas  uma por nome, com as N amostras (média/desvio no relatório); o valor
              é o PIOR caso (menor margem até o limite), então a métrica reprova
              se qualquer repetição reprovou; a descrição traz média, desvio,
              mínimo e máximo. Mais "repeticoes_aprovadas" (limite = N).

O nome do resultado é o mesmo do teste sem repetição: relatórios, painel de
detalhes e perfil de critérios continuam funcionando.
"""

from __future__ import annotations

import dataclasses
import statistics
import time

from tests_builtin.base import BuiltinTest, TestResult, TestStatus


def _worst(ms: list):
    """A amostra com menor folga até o limite (reprovadas primeiro)."""
    def key(m):
        if m.within_limits is False:
            return (0, m.margin_pct if m.margin_pct is not None else 0.0)
        if m.margin_pct is not None:
            return (1, m.margin_pct)
        return (2, 0.0)
    return min(ms, key=key)


def aggregate(name: str, results: list[TestResult]) -> TestResult:
    from core.analysis import MeasurementSet
    from core.analysis.metrics import Measurement

    n = len(results)
    st = [r.status for r in results]
    passed = st.count(TestStatus.PASS)
    if passed == n:
        status = TestStatus.PASS
    elif all(s == TestStatus.ERROR for s in st):
        status = TestStatus.ERROR
    elif all(s == TestStatus.SKIP for s in st):
        status = TestStatus.SKIP
    else:
        status = TestStatus.FAIL

    msg = f"{passed}/{n} PASS em {n} repetições"
    bad = [i for i, r in enumerate(results, 1) if r.status in (TestStatus.FAIL, TestStatus.ERROR)]
    if bad:
        first = results[bad[0] - 1]
        msg += f"; falharam: {', '.join(map(str, bad))} (#{bad[0]}: {first.message})"
    msg += f" | última: {results[-1].message}"

    by_name: dict[str, list] = {}
    for r in results:
        for m in r.measurements or []:
            by_name.setdefault(m.name, []).append(m)
    ms = MeasurementSet()
    for items in by_name.values():
        values = [float(m.value) for m in items]
        worst = _worst(items)
        spread = statistics.stdev(values) if len(values) > 1 else 0.0
        stats = (f"{len(values)} repetições: média {statistics.mean(values):.6g}, "
                 f"desvio {spread:.3g}, mín {min(values):.6g}, máx {max(values):.6g} "
                 f"{worst.unit}").rstrip()
        desc = f"{worst.description} — {stats}" if worst.description else stats
        ms.add(dataclasses.replace(worst, samples=values, description=desc, limit_source=""))
    ms.add(Measurement("repeticoes_aprovadas", float(passed), f"de {n}", limit_min=float(n),
                       description="repetições com PASS"))
    return TestResult(name, status, msg, measurements=ms, params=results[0].params,
                      duration_ms=round(sum(r.duration_ms for r in results), 2))


class RepeatedTest(BuiltinTest):
    """Envolve um teste já configurado (configure()) e o roda `times` vezes."""

    def __init__(self, test: BuiltinTest, times: int) -> None:
        self.inner, self.times = test, max(1, int(times))
        self.name = test.name
        self.description = f"{test.description} (x{self.times})"
        self.category = getattr(test, "category", "")
        self.params = test.params
        self.label = getattr(test, "label", "")

    def run(self, pal) -> TestResult:
        values = getattr(self.inner, "_param_values", {})
        results = []
        t0 = time.perf_counter()
        for _ in range(self.times):
            test = type(self.inner)().configure(values, self.label)
            results.append(test.run(pal))
        result = aggregate(self.name, results)
        result.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        result.started_at = results[0].started_at
        last = dict(results[-1].details or {})
        last["repeticoes"] = [[str(i), r.status.value, f"{r.duration_ms:.0f}", r.started_at,
                               r.message] for i, r in enumerate(results, 1)]
        logs = []
        for i, r in enumerate(results, 1):
            logs += [f"[repetição {i}] {line}" for line in (r.details or {}).get("log", [])]
        if logs:
            last["log"] = logs
        result.details = last
        return result

    def _run(self, pal) -> TestResult:          # não usado: run() agrega as repetições
        raise NotImplementedError
