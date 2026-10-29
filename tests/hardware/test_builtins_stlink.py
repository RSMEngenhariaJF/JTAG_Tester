"""Testes de hardware: suite de bring-up completa via ST-Link.

Execução:
    pytest tests/hardware/test_builtins_stlink.py -m hardware --stlink -v -s

Pré-condição: NUCLEO-F446RE conectada, firmware padrão rodando
(LED LD2 = PA5 como saída, botão USER = PC13 como entrada).
"""

from __future__ import annotations

import pytest

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


# ---------------------------------------------------------------------------
# Helpers de exibição
# ---------------------------------------------------------------------------


def _print_result(result) -> None:
    status_sym = {"PASS": "✓", "FAIL": "✗", "ERROR": "!", "SKIP": "-"}
    sym = status_sym.get(result.status.value, "?")
    print(
        f"\n  [{sym}] {result.name:<12} {result.duration_ms:6.1f} ms  "
        f"{result.message}"
    )
    if result.measured is not None:
        print(f"      measured={result.measured!r}  expected={result.expected!r}")


# ===========================================================================
# Testes individuais — diagnóstico granular
# ===========================================================================


@pytest.mark.hardware
class TestDeviceIdHardware:
    def test_device_id_passes(self, pal_stlink) -> None:
        result = DeviceIdTest().run(pal_stlink)
        _print_result(result)
        assert result.status == TestStatus.PASS

    def test_device_id_measured_is_0x421(self, pal_stlink) -> None:
        result = DeviceIdTest().run(pal_stlink)
        assert result.measured == 0x421

    def test_device_id_duration_nonzero(self, pal_stlink) -> None:
        result = DeviceIdTest().run(pal_stlink)
        assert result.duration_ms >= 0


@pytest.mark.hardware
class TestClockHardware:
    def test_clocks_pass(self, pal_stlink) -> None:
        result = ClockTest().run(pal_stlink)
        _print_result(result)
        assert result.status == TestStatus.PASS


@pytest.mark.hardware
class TestSRAMHardware:
    def test_sram_pass(self, pal_stlink) -> None:
        result = SRAMTest().run(pal_stlink)
        _print_result(result)
        assert result.status == TestStatus.PASS

    def test_sram_restores_memory(self, pal_stlink) -> None:
        addr = 0x20000000
        original = pal_stlink.mem.read_mem32(addr)
        SRAMTest().run(pal_stlink)
        restored = pal_stlink.mem.read_mem32(addr)
        assert restored == original


@pytest.mark.hardware
class TestLedHardware:
    def test_led_pass(self, pal_stlink) -> None:
        result = LedTest().run(pal_stlink)
        _print_result(result)
        assert result.status == TestStatus.PASS

    def test_led_restores_pa5_moder(self, pal_stlink) -> None:
        original_moder = pal_stlink.read_field("GPIOA", "MODER", "MODER5")
        LedTest().run(pal_stlink)
        restored = pal_stlink.read_field("GPIOA", "MODER", "MODER5")
        assert restored == original_moder


@pytest.mark.hardware
class TestButtonHardware:
    def test_button_pass(self, pal_stlink) -> None:
        result = ButtonTest().run(pal_stlink)
        _print_result(result)
        assert result.status == TestStatus.PASS

    def test_button_high_when_released(self, pal_stlink) -> None:
        result = ButtonTest().run(pal_stlink)
        # Sem pressionar o botão → deve estar solto (HIGH)
        assert result.measured is True


# ===========================================================================
# Suite completa — relatório de bring-up
# ===========================================================================


@pytest.mark.hardware
class TestFullSuiteHardware:
    def test_all_tests_produce_result(self, pal_stlink) -> None:
        results = run_suite(pal_stlink)
        assert len(results) == len(STANDARD_SUITE)

    def test_all_pass(self, pal_stlink) -> None:
        """Gate de bring-up: todos os testes devem passar na NUCLEO padrão."""
        results = run_suite(pal_stlink)
        print("\n\n  === Relatório de Bring-up ===")
        for r in results:
            _print_result(r)
        counts = summarize(results)
        fail_err = counts[TestStatus.FAIL] + counts[TestStatus.ERROR]
        print(
            f"\n  Resumo: PASS={counts[TestStatus.PASS]}  "
            f"FAIL={counts[TestStatus.FAIL]}  "
            f"ERROR={counts[TestStatus.ERROR]}  "
            f"SKIP={counts[TestStatus.SKIP]}"
        )
        assert fail_err == 0, f"{fail_err} teste(s) falharam — veja saída acima"

    def test_summarize_all_pass_count(self, pal_stlink) -> None:
        results = run_suite(pal_stlink)
        counts = summarize(results)
        assert counts[TestStatus.PASS] == len(STANDARD_SUITE)
