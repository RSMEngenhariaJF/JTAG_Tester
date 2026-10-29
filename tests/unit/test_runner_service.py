"""Testes unitários de TestRunnerService.

Usa FakeMemory + SVD real — sem hardware.
Usa pytest-qt (qtbot) para capturar sinais emitidos pela QThread.

Execução:
    pytest tests/unit/test_runner_service.py -v
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from core.pal.access import PeripheralAccessLayer
from core.svd.parser import parse
from app.services.runner import TestRunnerService
from tests_builtin import STANDARD_SUITE, DeviceIdTest, ClockTest, TestStatus
from tests_builtin.base import BuiltinTest, TestResult

_SVD = Path(__file__).parents[2] / "devices" / "stm32f446" / "STM32F446.svd"
_DBGMCU = 0xE0042000


# ---------------------------------------------------------------------------
# Infra de teste
# ---------------------------------------------------------------------------


class FakeMemory:
    def __init__(self, initial: dict[int, int] | None = None) -> None:
        self._mem: dict[int, int] = dict(initial or {})

    def read_mem32(self, addr: int) -> int:
        return self._mem.get(addr, 0)

    def write_mem32(self, addr: int, value: int) -> None:
        self._mem[addr] = value & 0xFFFFFFFF


class FakeDevice:
    """Stub de DeviceService: PAL com FakeMemory, sem hardware."""

    def __init__(self, pal: PeripheralAccessLayer | None) -> None:
        self._pal = pal

    @property
    def pal(self) -> PeripheralAccessLayer | None:
        return self._pal


class _BlockingTest(BuiltinTest):
    """BuiltinTest que bloqueia a thread ate release() — para testes deterministas."""

    name        = "_Block"
    description = "Bloqueia a thread ate release() ser chamado"

    def __init__(self) -> None:
        self._gate    = threading.Event()
        self._started = threading.Event()   # set quando _run esta bloqueando

    def release(self) -> None:
        self._gate.set()

    def wait_until_started(self, timeout: float = 5.0) -> None:
        self._started.wait(timeout=timeout)

    def _run(self, pal) -> TestResult:
        self._started.set()       # sinaliza que esta bloqueando
        self._gate.wait(timeout=5.0)
        return self._pass("released")


@pytest.fixture(scope="module")
def svd():
    return parse(_SVD)


@pytest.fixture
def mem():
    return FakeMemory({_DBGMCU: 0x10000421})


@pytest.fixture
def pal(mem, svd):
    p = PeripheralAccessLayer(mem, svd)
    # ClockTest precisa de GPIOAEN e GPIOCEN
    p.modify_field("RCC", "AHB1ENR", "GPIOAEN", 1)
    p.modify_field("RCC", "AHB1ENR", "GPIOCEN", 1)
    return p


@pytest.fixture
def device(pal):
    return FakeDevice(pal)


@pytest.fixture
def runner(qtbot, device):
    svc = TestRunnerService(device)
    return svc


# ===========================================================================
# Estado
# ===========================================================================


class TestRunnerServiceState:
    def test_not_running_initially(self, runner) -> None:
        assert not runner.is_running

    def test_raises_when_no_probe(self, qtbot) -> None:
        svc = TestRunnerService(FakeDevice(pal=None))
        with pytest.raises(RuntimeError, match="Probe não conectado"):
            svc.run([DeviceIdTest()])

    def test_raises_when_already_running(self, qtbot, runner) -> None:
        """Verifica RuntimeError ao tentar iniciar suite enquanto outra roda.

        O assert é feito DENTRO do handler test_started (thread ainda ativa),
        evitando corrida entre FakeMemory rápida e o assert externo.
        """
        raised: list[bool] = []

        def _try_second_run(_name: str) -> None:
            try:
                runner.run([DeviceIdTest()])
            except RuntimeError:
                raised.append(True)

        runner.test_started.connect(_try_second_run)

        with qtbot.waitSignal(runner.suite_finished, timeout=5000):
            runner.run(STANDARD_SUITE)

        assert raised, "RuntimeError nunca levantada durante execução concorrente"


# ===========================================================================
# Sinais
# ===========================================================================


class TestRunnerServiceSignals:
    def test_suite_started_emits_total_count(self, qtbot, runner) -> None:
        tests = [DeviceIdTest(), ClockTest()]
        with qtbot.waitSignal(runner.suite_started, timeout=3000) as sig:
            runner.run(tests)
        assert sig.args[0] == 2
        qtbot.waitSignal(runner.suite_finished, timeout=3000)

    def test_test_started_emits_name(self, qtbot, runner) -> None:
        names: list[str] = []
        runner.test_started.connect(names.append)

        with qtbot.waitSignal(runner.suite_finished, timeout=3000):
            runner.run([DeviceIdTest(), ClockTest()])

        assert "DeviceId" in names
        assert "Clocks"   in names

    def test_test_finished_emits_result(self, qtbot, runner) -> None:
        from tests_builtin.base import TestResult
        results: list[TestResult] = []
        runner.test_finished.connect(results.append)

        with qtbot.waitSignal(runner.suite_finished, timeout=3000):
            runner.run([DeviceIdTest()])

        assert len(results) == 1
        assert isinstance(results[0], TestResult)

    def test_suite_finished_emits_all_results(self, qtbot, runner) -> None:
        received: list = []
        runner.suite_finished.connect(received.append)

        tests = [DeviceIdTest(), ClockTest()]
        with qtbot.waitSignal(runner.suite_finished, timeout=3000):
            runner.run(tests)

        assert len(received) == 1          # suite_finished emitido uma vez
        assert len(received[0]) == len(tests)

    def test_not_running_after_suite_finishes(self, qtbot, runner) -> None:
        with qtbot.waitSignal(runner.suite_finished, timeout=3000):
            runner.run([DeviceIdTest()])
        assert not runner.is_running

    def test_running_true_during_execution(self, qtbot, runner) -> None:
        """is_running True enquanto _BlockingTest trava a thread."""
        blocker = _BlockingTest()
        runner.run([blocker])
        blocker.wait_until_started()    # espera thread bloquear no gate
        assert runner.is_running
        blocker.release()
        qtbot.waitSignal(runner.suite_finished, timeout=3000)

    def test_result_names_match_test_names(self, qtbot, runner) -> None:
        tests = [DeviceIdTest(), ClockTest()]
        received: list = []
        runner.suite_finished.connect(received.append)

        with qtbot.waitSignal(runner.suite_finished, timeout=3000):
            runner.run(tests)

        names = [r.name for r in received[0]]
        assert names == [t.name for t in tests]


# ===========================================================================
# Abort
# ===========================================================================


class TestRunnerServiceAbort:
    def test_abort_stops_before_all_tests(self, qtbot, runner) -> None:
        """Abort determinista: blocker trava a thread; abort() antes de release()."""
        blocker = _BlockingTest()
        # DeviceId | blocker | DeviceId — abort deve parar antes do 3o teste
        tests = [DeviceIdTest(), blocker, DeviceIdTest()]
        received: list = []
        runner.suite_finished.connect(received.append)

        # Usa context manager para que o event loop rode ao sair do with-block
        with qtbot.waitSignal(runner.suite_finished, timeout=5000):
            runner.run(tests)
            blocker.wait_until_started()   # bloqueia ate thread travar no gate
            runner.abort()
            blocker.release()              # libera; thread checa _abort e para

        assert len(received[0]) < len(tests)

    def test_abort_on_idle_is_harmless(self, runner) -> None:
        runner.abort()   # não deve levantar
        assert not runner.is_running

    def test_not_running_after_abort(self, qtbot, runner) -> None:
        runner.test_finished.connect(lambda _: runner.abort())

        with qtbot.waitSignal(runner.suite_finished, timeout=5000):
            runner.run(STANDARD_SUITE)

        assert not runner.is_running
