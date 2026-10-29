"""Testes unitários dos testes embutidos de bring-up.

Usa FakeMemory (sem hardware). BsrrAwareMemory simula o acoplamento
BSRR → ODR do STM32 para que LedTest possa verificar ODR.

Execução:
    pytest tests/unit/test_builtins.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.board.config import set_active_board
from core.pal.access import PeripheralAccessLayer
from core.svd.parser import parse
from tests_builtin import (
    STANDARD_SUITE,
    ButtonTest,
    ClockTest,
    DeviceIdTest,
    LedTest,
    SRAMTest,
    TestStatus,
    run_suite,
    summarize,
)

_SVD = Path(__file__).parents[2] / "devices" / "stm32f446" / "STM32F446.svd"

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

    def peek(self, addr: int) -> int:
        return self._mem.get(addr, 0)


class BsrrAwareMemory(FakeMemory):
    """FakeMemory que simula BSRR → ODR (set/reset atômico do STM32)."""

    def __init__(self, svd, initial: dict[int, int] | None = None) -> None:
        super().__init__(initial)
        self._bsrr_to_odr: dict[int, int] = {}
        for port in ("GPIOA", "GPIOB", "GPIOC", "GPIOD"):
            try:
                p = svd.peripheral(port)
                self._bsrr_to_odr[p.address_of("BSRR")] = p.address_of("ODR")
            except Exception:
                pass

    def write_mem32(self, addr: int, value: int) -> None:
        super().write_mem32(addr, value)
        if addr in self._bsrr_to_odr:
            odr_addr = self._bsrr_to_odr[addr]
            odr = self._mem.get(odr_addr, 0)
            set_bits   = value & 0xFFFF
            reset_bits = (value >> 16) & 0xFFFF
            self._mem[odr_addr] = (odr | set_bits) & ~reset_bits & 0xFFFF


@pytest.fixture(scope="module")
def svd():
    return parse(_SVD)


@pytest.fixture
def fake_mem():
    return FakeMemory()


@pytest.fixture
def pal(fake_mem, svd):
    return PeripheralAccessLayer(fake_mem, svd)


@pytest.fixture
def bsrr_mem(svd):
    return BsrrAwareMemory(svd)


@pytest.fixture
def pal_bsrr(bsrr_mem, svd):
    return PeripheralAccessLayer(bsrr_mem, svd)


# Garante que get_active_board() funcione em todos os testes deste módulo
@pytest.fixture(autouse=True)
def _active_board():
    from boards.nucleo_f446re import BOARD
    set_active_board(BOARD)


# ===========================================================================
# DeviceIdTest
# ===========================================================================

_DBGMCU = 0xE0042000


class TestDeviceId:
    def test_pass_with_correct_idcode(self, pal, fake_mem) -> None:
        fake_mem._mem[_DBGMCU] = 0x10000421   # REV_ID=0x1000, DEV_ID=0x421
        result = DeviceIdTest().run(pal)
        assert result.status == TestStatus.PASS

    def test_measured_is_dev_id(self, pal, fake_mem) -> None:
        fake_mem._mem[_DBGMCU] = 0x10000421
        result = DeviceIdTest().run(pal)
        assert result.measured == 0x421

    def test_expected_is_0x421(self, pal, fake_mem) -> None:
        fake_mem._mem[_DBGMCU] = 0x10000421
        result = DeviceIdTest().run(pal)
        assert result.expected == 0x421

    def test_fail_with_wrong_devid(self, pal, fake_mem) -> None:
        fake_mem._mem[_DBGMCU] = 0x10000123   # DEV_ID=0x123 (errado)
        result = DeviceIdTest().run(pal)
        assert result.status == TestStatus.FAIL
        assert result.measured == 0x123
        assert result.expected == 0x421

    def test_fail_message_contains_hex(self, pal, fake_mem) -> None:
        fake_mem._mem[_DBGMCU] = 0x10000123
        result = DeviceIdTest().run(pal)
        assert "0x123" in result.message
        assert "0x421" in result.message

    def test_duration_populated(self, pal, fake_mem) -> None:
        fake_mem._mem[_DBGMCU] = 0x10000421
        result = DeviceIdTest().run(pal)
        assert result.duration_ms >= 0

    def test_pass_message_contains_rev_id(self, pal, fake_mem) -> None:
        fake_mem._mem[_DBGMCU] = 0x10000421
        result = DeviceIdTest().run(pal)
        assert "1000" in result.message   # REV_ID hex


# ===========================================================================
# ClockTest
# ===========================================================================


class TestClockTest:
    def test_pass_when_both_clocks_enabled(self, pal) -> None:
        pal.modify_field("RCC", "AHB1ENR", "GPIOAEN", 1)
        pal.modify_field("RCC", "AHB1ENR", "GPIOCEN", 1)
        result = ClockTest().run(pal)
        assert result.status == TestStatus.PASS

    def test_fail_when_gpioa_disabled(self, pal) -> None:
        pal.modify_field("RCC", "AHB1ENR", "GPIOAEN", 0)
        pal.modify_field("RCC", "AHB1ENR", "GPIOCEN", 1)
        result = ClockTest().run(pal)
        assert result.status == TestStatus.FAIL
        assert "GPIOA" in result.message

    def test_fail_when_gpioc_disabled(self, pal) -> None:
        pal.modify_field("RCC", "AHB1ENR", "GPIOAEN", 1)
        pal.modify_field("RCC", "AHB1ENR", "GPIOCEN", 0)
        result = ClockTest().run(pal)
        assert result.status == TestStatus.FAIL
        assert "GPIOC" in result.message

    def test_fail_when_both_disabled(self, svd) -> None:
        mem = FakeMemory()   # tudo zerado = nenhum clock ligado
        p = PeripheralAccessLayer(mem, svd)
        result = ClockTest().run(p)
        assert result.status == TestStatus.FAIL
        assert "GPIOA" in result.message
        assert "GPIOC" in result.message

    def test_pass_message_lists_enabled_clocks(self, pal) -> None:
        pal.modify_field("RCC", "AHB1ENR", "GPIOAEN", 1)
        pal.modify_field("RCC", "AHB1ENR", "GPIOCEN", 1)
        result = ClockTest().run(pal)
        assert "GPIOA" in result.message
        assert "GPIOC" in result.message


# ===========================================================================
# SRAMTest
# ===========================================================================

_SRAM = 0x20000000
_PAT  = 0xA5A5A5A5


class TestSRAM:
    def test_pass_with_default_memory(self, pal) -> None:
        result = SRAMTest().run(pal)
        assert result.status == TestStatus.PASS

    def test_restores_original_value(self, pal, fake_mem) -> None:
        fake_mem._mem[_SRAM] = 0xDEADBEEF
        SRAMTest().run(pal)
        assert fake_mem.peek(_SRAM) == 0xDEADBEEF

    def test_restores_zero_original(self, pal, fake_mem) -> None:
        fake_mem._mem[_SRAM] = 0
        SRAMTest().run(pal)
        assert fake_mem.peek(_SRAM) == 0

    def test_pass_message_contains_address(self, pal) -> None:
        result = SRAMTest().run(pal)
        assert "20000000" in result.message

    def test_error_captured_gracefully(self, svd) -> None:
        class RaisesOnWrite(FakeMemory):
            def write_mem32(self, addr, value):
                raise OSError("link down")

        p = PeripheralAccessLayer(RaisesOnWrite(), svd)
        result = SRAMTest().run(p)
        assert result.status == TestStatus.ERROR
        assert "OSError" in result.message


# ===========================================================================
# LedTest
# ===========================================================================


class TestLed:
    def test_pass_with_bsrr_simulation(self, pal_bsrr) -> None:
        result = LedTest().run(pal_bsrr)
        assert result.status == TestStatus.PASS

    def test_fail_when_odr_not_updated(self, pal) -> None:
        # FakeMemory sem simulação BSRR→ODR: ODR5 fica 0 após SET
        result = LedTest().run(pal)
        assert result.status == TestStatus.FAIL
        assert "SET=0" in result.message

    def test_restores_moder_on_pass(self, pal_bsrr) -> None:
        original = pal_bsrr.read_field("GPIOA", "MODER", "MODER5")
        LedTest().run(pal_bsrr)
        assert pal_bsrr.read_field("GPIOA", "MODER", "MODER5") == original

    def test_restores_moder_on_fail(self, pal) -> None:
        pal.modify_field("GPIOA", "MODER", "MODER5", 1)
        LedTest().run(pal)   # vai FAIL (sem BSRR→ODR)
        assert pal.read_field("GPIOA", "MODER", "MODER5") == 1

    def test_duration_populated(self, pal_bsrr) -> None:
        result = LedTest().run(pal_bsrr)
        assert result.duration_ms >= 0

    def test_name_is_led(self) -> None:
        assert LedTest().name == "LED"


# ===========================================================================
# ButtonTest
# ===========================================================================


class TestButton:
    def test_pass_when_input_and_high(self, pal, fake_mem, svd) -> None:
        # MODER default 0 = INPUT; IDR13=1 (botão solto)
        idr_addr = svd.peripheral("GPIOC").address_of("IDR")
        fake_mem._mem[idr_addr] = 1 << 13
        result = ButtonTest().run(pal)
        assert result.status == TestStatus.PASS
        assert result.measured is True
        assert "HIGH" in result.message

    def test_pass_when_input_and_low(self, pal) -> None:
        # IDR13=0 (botão pressionado)
        result = ButtonTest().run(pal)
        assert result.status == TestStatus.PASS
        assert result.measured is False
        assert "LOW" in result.message

    def test_fail_when_output_mode(self, pal) -> None:
        pal.modify_field("GPIOC", "MODER", "MODER13", 0b01)   # OUTPUT
        result = ButtonTest().run(pal)
        assert result.status == TestStatus.FAIL
        assert result.expected == 0
        assert result.measured == 1

    def test_name_is_button(self) -> None:
        assert ButtonTest().name == "Button"


# ===========================================================================
# run_suite + summarize
# ===========================================================================


class TestRunSuite:
    def test_run_suite_returns_all_results(self, pal) -> None:
        results = run_suite(pal, STANDARD_SUITE)
        assert len(results) == len(STANDARD_SUITE)

    def test_run_suite_result_types(self, pal) -> None:
        from tests_builtin.base import TestResult
        results = run_suite(pal, STANDARD_SUITE)
        assert all(isinstance(r, TestResult) for r in results)

    def test_run_suite_names_match(self, pal) -> None:
        results = run_suite(pal, STANDARD_SUITE)
        names = [r.name for r in results]
        assert "DeviceId" in names
        assert "Clocks"   in names
        assert "SRAM"     in names
        assert "LED"      in names
        assert "Button"   in names

    def test_summarize_counts_status(self, pal, fake_mem) -> None:
        fake_mem._mem[_DBGMCU] = 0x00000000   # DEV_ID=0 → FAIL
        results = run_suite(pal, STANDARD_SUITE)
        counts = summarize(results)
        total = sum(counts.values())
        assert total == len(STANDARD_SUITE)
        assert counts[TestStatus.FAIL] >= 1

    def test_summarize_all_status_keys(self, pal) -> None:
        results = run_suite(pal, [])
        counts = summarize(results)
        assert set(counts.keys()) == set(TestStatus)

    def test_error_status_on_exception(self, svd) -> None:
        class AlwaysRaises(FakeMemory):
            def read_mem32(self, addr):
                raise RuntimeError("boom")

        p = PeripheralAccessLayer(AlwaysRaises(), svd)
        result = DeviceIdTest().run(p)
        assert result.status == TestStatus.ERROR
        assert "RuntimeError" in result.message
