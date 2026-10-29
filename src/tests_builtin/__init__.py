"""Pacote de testes embutidos de bring-up.

Uso rápido (global board já definido via set_active_board)::

    from tests_builtin import STANDARD_SUITE, run_suite
    results = run_suite(pal)

Uso com placa explícita (recomendado em testes unitários)::

    from tests_builtin import build_suite
    from boards.nucleo_f446re import BOARD
    results = run_suite(pal, tests=build_suite(BOARD))
"""

from __future__ import annotations

from typing import Iterable

from core.board.config import BoardConfig
from core.pal.access import PeripheralAccessLayer

from tests_builtin.base import BuiltinTest, TestResult, TestStatus
from tests_builtin.button import ButtonTest
from tests_builtin.clocks import ClockTest
from tests_builtin.device_id import DeviceIdTest
from tests_builtin.led import LedTest
from tests_builtin.sram import SRAMTest
from tests_builtin.usart_loopback import UsartLoopbackTest
from tests_builtin.spi_loopback import SpiLoopbackTest

__all__ = [
    "BuiltinTest",
    "TestResult",
    "TestStatus",
    "DeviceIdTest",
    "ClockTest",
    "SRAMTest",
    "LedTest",
    "ButtonTest",
    "UsartLoopbackTest",
    "SpiLoopbackTest",
    "STANDARD_SUITE",
    "build_suite",
    "run_suite",
    "summarize",
]

# Suite padrão sem placa explícita — cada teste chama get_active_board() em runtime
STANDARD_SUITE: tuple[BuiltinTest, ...] = (
    DeviceIdTest(),
    ClockTest(),
    SRAMTest(),
    LedTest(),
    ButtonTest(),
    UsartLoopbackTest(),
    SpiLoopbackTest(),
)


def build_suite(cfg: BoardConfig) -> tuple[BuiltinTest, ...]:
    """Constrói a suite padrão com a placa explicitamente injetada.

    Preferível a STANDARD_SUITE em testes unitários e scripts
    onde não há estado global de placa configurado.
    """
    return (
        DeviceIdTest(cfg),
        ClockTest(cfg),
        SRAMTest(cfg),
        LedTest(cfg),
        ButtonTest(cfg),
        UsartLoopbackTest(cfg),
        SpiLoopbackTest(cfg),
    )


def run_suite(
    pal: PeripheralAccessLayer,
    tests: Iterable[BuiltinTest] = STANDARD_SUITE,
) -> list[TestResult]:
    """Executa todos os testes e retorna a lista de resultados."""
    return [t.run(pal) for t in tests]


def summarize(results: list[TestResult]) -> dict[TestStatus, int]:
    """Conta resultados por status."""
    counts: dict[TestStatus, int] = {s: 0 for s in TestStatus}
    for r in results:
        counts[r.status] += 1
    return counts
