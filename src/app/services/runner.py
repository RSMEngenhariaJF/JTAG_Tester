"""TestRunnerService — executa a suite de testes embutidos em background.

Uso típico (GUI):
    runner = TestRunnerService(device_service)
    runner.test_started.connect(on_test_started)
    runner.test_finished.connect(on_test_finished)
    runner.suite_finished.connect(on_suite_finished)
    runner.run()          # inicia QThread; sinais emitidos conforme progresso
    # ...
    runner.abort()        # solicita interrupção (thread para no próximo teste)
"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QObject, QThread, Signal

from tests_builtin import STANDARD_SUITE, BuiltinTest, TestResult


class _RunnerThread(QThread):
    """QThread interno que itera os testes e emite sinais por resultado."""

    test_started   = Signal(str)     # nome do teste que vai iniciar
    test_finished  = Signal(object)  # TestResult do teste concluído
    suite_started  = Signal(int)     # total de testes na suite
    suite_finished = Signal(object)  # list[TestResult] completa

    def __init__(
        self,
        pal: object,
        tests: tuple[BuiltinTest, ...],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._pal = pal
        self._tests = tests
        self._abort = False

    def request_abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        self.suite_started.emit(len(self._tests))
        results: list[TestResult] = []
        for test in self._tests:
            if self._abort:
                break
            self.test_started.emit(test.name)
            result = test.run(self._pal)
            self.test_finished.emit(result)
            results.append(result)
        self.suite_finished.emit(results)


class TestRunnerService(QObject):
    """Orquestra a execução dos testes embutidos em thread de fundo.

    Encapsula ``_RunnerThread`` e repassa todos os seus sinais para quem
    escuta o servico (GUI, testes automatizados, etc.).
    """

    __test__ = False  # evita coleta acidental pelo pytest (nome comeca com "Test")

    test_started   = Signal(str)
    test_finished  = Signal(object)   # TestResult
    suite_started  = Signal(int)
    suite_finished = Signal(object)   # list[TestResult]

    def __init__(self, device: object, parent: QObject | None = None) -> None:
        """
        Parâmetros
        ----------
        device : qualquer objeto que exponha a propriedade ``.pal``
                 (tipicamente um DeviceService)
        """
        super().__init__(parent)
        self._device = device
        self._thread: _RunnerThread | None = None

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    # ------------------------------------------------------------------
    # Controle
    # ------------------------------------------------------------------

    def run(self, tests: Iterable[BuiltinTest] = STANDARD_SUITE) -> None:
        """Inicia a suite em background.

        Levanta ``RuntimeError`` se:
        - probe não conectado (``device.pal is None``), ou
        - outra suite já estiver em execução.
        """
        if self.is_running:
            raise RuntimeError("Suite já está em execução.")
        pal = self._device.pal
        if pal is None:
            raise RuntimeError(
                "Probe não conectado — chame DeviceService.connect() primeiro."
            )

        thread = _RunnerThread(pal, tuple(tests), parent=self)
        thread.test_started.connect(self.test_started)
        thread.test_finished.connect(self.test_finished)
        thread.suite_started.connect(self.suite_started)
        thread.suite_finished.connect(self.suite_finished)
        thread.finished.connect(self._on_thread_finished)
        self._thread = thread
        thread.start()

    def abort(self) -> None:
        """Solicita interrupção após o teste atual terminar."""
        if self._thread is not None:
            self._thread.request_abort()

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    def _on_thread_finished(self) -> None:
        self._thread = None
