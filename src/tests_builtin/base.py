"""Base do framework de testes embutidos (bring-up).

Define TestStatus, TestResult e a classe abstrata BuiltinTest.
"""

from __future__ import annotations

import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from core.pal.access import PeripheralAccessLayer

if TYPE_CHECKING:
    from core.analysis.metrics import MeasurementSet
    from tests_builtin.params import Param


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
    params:       "dict[str, str] | None"      = field(default=None, compare=False)
    started_at:   str                          = field(default="", compare=False)
    # Registro para auditoria (core.analysis.audit): identificação do código,
    # passos, decisões, repetições, log e exceção. Preenchido por run().
    details:      dict | None                  = field(default=None, compare=False)

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
        if self.params:
            d["params"] = self.params
        if self.started_at:
            d["started_at"] = self.started_at
        if self.details:
            d["details"] = self.details
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
    category:    str = ""     # agrupa a biblioteca na janela "Adicionar teste" (ex.: "UART")

    # Parâmetros configuráveis no "Plano de testes" do projeto (tests_builtin.params).
    # Vazio = teste sem parâmetros (comportamento clássico).
    params: ClassVar[dict[str, Param]] = {}

    # ------------------------------------------------------------------
    # Parametrização
    # ------------------------------------------------------------------

    def configure(self, values: dict | None = None, label: str = "") -> BuiltinTest:
        """Define os valores dos parâmetros e o rótulo desta instância (retorna self).

        O rótulo entra no nome do resultado: "Piscar LED — LEDs indicadores".
        """
        self._param_values = dict(values or {})
        self.label = label
        if label:
            self.name = f"{type(self).name} — {label}"
        return self

    def param_errors(self, project=None) -> list[str]:
        from tests_builtin import params as tp
        return tp.validate(self.params, getattr(self, "_param_values", {}), project)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def run(self, pal: PeripheralAccessLayer) -> TestResult:
        from tests_builtin.audit import LogCapture, code_identity

        t0 = time.perf_counter()
        started = datetime.now().astimezone().isoformat(timespec="milliseconds")
        described = None
        self.audit: dict = {}
        capture = LogCapture()
        capture.start()
        try:
            if self.params:
                from core.project.config import get_active_project
                from tests_builtin import params as tp

                values = getattr(self, "_param_values", {})
                project = get_active_project()
                described = tp.describe(self.params, values)
                errs = tp.validate(self.params, values, project)
                if project is None and any(isinstance(p, tp.SignalsParam)
                                           for p in self.params.values()):
                    errs.append("Nenhum projeto ativo para resolver os sinais")
                if errs:
                    raise ValueError("parâmetros inválidos: " + "; ".join(errs))
                self.p = tp.resolve(self.params, values, project)
            result = self._run(pal)
        except Exception as exc:
            result = TestResult(
                name=self.name,
                status=TestStatus.ERROR,
                message=f"{type(exc).__name__}: {exc}",
            )
            self.audit["excecao"] = traceback.format_exc()
        finally:
            capture.stop()
        result.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        result.started_at = result.started_at or started
        details = {"teste": dict(code_identity(type(self))), "descricao": self.description}
        details.update(result.details or {})
        details.update(self.audit)
        if capture.lines:
            details["log"] = capture.lines
        result.details = details
        if described is not None and result.params is None:
            result.params = described
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
