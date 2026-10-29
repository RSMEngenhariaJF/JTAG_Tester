"""Base do framework de testes embutidos (bring-up).

Define TestStatus, TestResult e a classe abstrata BuiltinTest.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any
import time

from core.pal.access import PeripheralAccessLayer

if TYPE_CHECKING:
    from core.analysis.metrics import MeasurementSet


class TestStatus(Enum):
    __test__ = False  # evita que pytest tente coletar esta classe
    PASS  = "PASS"
    FAIL  = "FAIL"
    ERROR = "ERROR"
    SKIP  = "SKIP"


@dataclass
class TestResult:
    __test__ = False  # evita coleta acidental pelo pytest
    name:         str
    status:       TestStatus
    message:      str
    measured:     Any                          = None
    expected:     Any                          = None
    duration_ms:  float                        = field(default=0.0, compare=False)
    measurements: "MeasurementSet | None"      = field(default=None, compare=False)

    @property
    def passed(self) -> bool:
        return self.status == TestStatus.PASS

    def to_dict(self) -> dict:
        d: dict = {
            "name":        self.name,
            "status":      self.status.value,
            "message":     self.message,
            "duration_ms": self.duration_ms,
        }
        if self.measured is not None:
            d["measured"] = self.measured
        if self.expected is not None:
            d["expected"] = self.expected
        if self.measurements:
            d["measurements"] = self.measurements.to_dict()
        return d


class BuiltinTest(ABC):
    """Base para todos os testes embutidos de bring-up.

    Subclasses devem definir ``name`` e ``description`` como atributos de
    classe e implementar ``_run(pal) -> TestResult``.

    ``run()`` captura exceções não tratadas (→ ERROR) e mede a duração.

    Para testes com análise quantitativa, use ``_pass`` / ``_fail`` com
    o parâmetro ``measurements``::

        from core.analysis import analyze_ber, MeasurementSet

        def _run(self, pal):
            ms = MeasurementSet()
            ms.add(analyze_ber("uart_ber", sent, received, limit_max=1e-6))
            if ms.all_within_limits():
                return self._pass(measurements=ms)
            return self._fail("BER fora do limite", measurements=ms)
    """

    name:        str = ""
    description: str = ""

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def run(self, pal: PeripheralAccessLayer) -> TestResult:
        t0 = time.perf_counter()
        try:
            result = self._run(pal)
        except Exception as exc:
            result = TestResult(
                name=self.name,
                status=TestStatus.ERROR,
                message=f"{type(exc).__name__}: {exc}",
            )
        result.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        return result

    @abstractmethod
    def _run(self, pal: PeripheralAccessLayer) -> TestResult:
        ...

    # ------------------------------------------------------------------
    # Helpers para subclasses
    # ------------------------------------------------------------------

    def _pass(
        self,
        message: str = "OK",
        measured: Any = None,
        expected: Any = None,
        measurements: "MeasurementSet | None" = None,
    ) -> TestResult:
        return TestResult(
            self.name, TestStatus.PASS, message, measured, expected,
            measurements=measurements,
        )

    def _fail(
        self,
        message: str,
        measured: Any = None,
        expected: Any = None,
        measurements: "MeasurementSet | None" = None,
    ) -> TestResult:
        return TestResult(
            self.name, TestStatus.FAIL, message, measured, expected,
            measurements=measurements,
        )

    def _skip(self, reason: str) -> TestResult:
        return TestResult(self.name, TestStatus.SKIP, reason)
