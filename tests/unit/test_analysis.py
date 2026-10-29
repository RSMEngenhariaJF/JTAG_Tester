"""Testes unitários — sistema de análise e métricas."""

from __future__ import annotations

import math

import pytest

from core.analysis.metrics import Measurement, MeasurementSet
from core.analysis.analyzers import (
    analyze_ber,
    analyze_timing,
    analyze_jitter,
    analyze_voltage,
    analyze_ripple,
    analyze_frequency,
    analyze_delay,
)


# ─────────────────────────────────────────────────────────────────────────────
# Measurement
# ─────────────────────────────────────────────────────────────────────────────

class TestMeasurement:

    def test_single_value_no_samples(self):
        m = Measurement(name="volt", value=3.3, unit="V")
        assert m.value == 3.3
        assert m.mean  == 3.3
        assert m.std_dev == 0.0

    def test_stats_with_samples(self):
        m = Measurement(name="x", value=0.0, samples=[1.0, 2.0, 3.0, 4.0, 5.0])
        assert m.mean == pytest.approx(3.0)
        assert m.minimum == 1.0
        assert m.maximum == 5.0
        assert m.std_dev > 0

    def test_within_limits_pass(self):
        m = Measurement(name="v", value=3.3, limit_min=3.0, limit_max=3.6)
        assert m.within_limits is True
        assert m.status == "PASS"

    def test_within_limits_fail_high(self):
        m = Measurement(name="v", value=4.0, limit_min=3.0, limit_max=3.6)
        assert m.within_limits is False
        assert m.status == "FAIL"

    def test_within_limits_fail_low(self):
        m = Measurement(name="v", value=2.9, limit_min=3.0, limit_max=3.6)
        assert m.within_limits is False

    def test_no_limits_returns_none(self):
        m = Measurement(name="x", value=1.5)
        assert m.within_limits is None
        assert m.status == "INFO"

    def test_only_limit_max(self):
        m = Measurement(name="ber", value=1e-8, limit_max=1e-6)
        assert m.within_limits is True

    def test_only_limit_max_fail(self):
        m = Measurement(name="ber", value=1e-4, limit_max=1e-6)
        assert m.within_limits is False

    def test_percentiles(self):
        m = Measurement(name="x", value=0.0, samples=list(range(101)))
        assert m.p05 == pytest.approx(5.0, abs=1.0)
        assert m.p95 == pytest.approx(95.0, abs=1.0)

    def test_to_dict_has_required_keys(self):
        m = Measurement(name="v", value=3.3, unit="V",
                        limit_min=3.0, limit_max=3.6,
                        description="Tensão 3V3")
        d = m.to_dict()
        assert d["name"]      == "v"
        assert d["value"]     == 3.3
        assert d["unit"]      == "V"
        assert d["limit_min"] == 3.0
        assert d["limit_max"] == 3.6
        assert d["status"]    == "PASS"

    def test_to_dict_with_samples_has_stats(self):
        m = Measurement(name="x", value=2.5, samples=[1.0, 2.0, 3.0, 4.0])
        d = m.to_dict()
        assert "stats" in d
        assert d["stats"]["n"] == 4
        assert d["stats"]["mean"] == pytest.approx(2.5)


# ─────────────────────────────────────────────────────────────────────────────
# MeasurementSet
# ─────────────────────────────────────────────────────────────────────────────

class TestMeasurementSet:

    def test_empty_set_all_within_limits(self):
        ms = MeasurementSet()
        assert ms.all_within_limits() is True
        assert len(ms) == 0
        assert not ms.any_fail()

    def test_add_and_get(self):
        ms = MeasurementSet()
        m  = Measurement(name="uart_ber", value=1e-7, limit_max=1e-5)
        ms.add(m)
        assert ms.get("uart_ber") is m
        assert len(ms) == 2 - 1  # len == 1
        assert len(ms) == 1

    def test_all_within_limits_with_pass(self):
        ms = MeasurementSet()
        ms.add(Measurement("a", 1.0, limit_max=2.0))
        ms.add(Measurement("b", 3.3, limit_min=3.0, limit_max=3.6))
        assert ms.all_within_limits() is True

    def test_any_fail_with_failure(self):
        ms = MeasurementSet()
        ms.add(Measurement("a", 1.0, limit_max=2.0))   # PASS
        ms.add(Measurement("b", 5.0, limit_max=2.0))   # FAIL
        assert ms.all_within_limits() is False
        assert ms.any_fail() is True

    def test_info_measurements_dont_affect_result(self):
        ms = MeasurementSet()
        ms.add(Measurement("info", 42.0))              # sem limites = INFO
        assert ms.all_within_limits() is True

    def test_iteration(self):
        ms = MeasurementSet()
        ms.add(Measurement("x", 1.0))
        ms.add(Measurement("y", 2.0))
        names = [m.name for m in ms]
        assert names == ["x", "y"]

    def test_to_dict(self):
        ms = MeasurementSet()
        ms.add(Measurement("v", 3.3, limit_min=3.0, limit_max=3.6))
        d = ms.to_dict()
        assert d["all_pass"] is True
        assert len(d["measurements"]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# BER
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyzeBer:

    def test_perfect_transmission(self):
        data = bytes(range(256))
        m = analyze_ber("ber", data, data)
        assert m.value == 0.0
        assert m.status == "INFO"   # sem limite definido

    def test_perfect_transmission_with_limit(self):
        data = bytes(range(256))
        m = analyze_ber("ber", data, data, limit_max=1e-6)
        assert m.within_limits is True

    def test_single_bit_error(self):
        sent = bytes([0b00000000])
        recv = bytes([0b00000001])   # 1 bit diferente
        m    = analyze_ber("ber", sent, recv)
        assert m.value == pytest.approx(1 / 8)

    def test_all_bits_flipped(self):
        sent = bytes([0xFF])
        recv = bytes([0x00])
        m    = analyze_ber("ber", sent, recv)
        assert m.value == pytest.approx(1.0)

    def test_lost_bytes_count_as_errors(self):
        sent = bytes([0x00] * 4)   # 32 bits
        recv = bytes([0x00] * 2)   # apenas 2 bytes recebidos → 2 bytes perdidos
        m    = analyze_ber("ber", sent, recv)
        assert m.value == pytest.approx(16 / 32)   # 16 bits perdidos / 32 totais

    def test_empty_sent(self):
        m = analyze_ber("ber", b"", b"abc")
        assert m.value == 0.0

    def test_ber_above_limit_fails(self):
        sent = bytes([0xFF] * 100)
        recv = bytes([0x0F] * 100)   # 4 bits errados por byte → BER = 0.5
        m    = analyze_ber("ber", sent, recv, limit_max=1e-6)
        assert m.within_limits is False

    def test_unit_is_err_per_bit(self):
        m = analyze_ber("ber", b"\x00", b"\x00")
        assert m.unit == "err/bit"


# ─────────────────────────────────────────────────────────────────────────────
# Timing
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyzeTiming:

    def test_perfect_period(self):
        # Eventos exatamente a cada 1 ms
        ts = [i * 0.001 for i in range(11)]   # 0..10 ms, 10 períodos
        m  = analyze_timing("period", ts, expected_period_s=0.001)
        assert m.value == pytest.approx(0.001, rel=1e-9)
        assert m.within_limits is True

    def test_period_out_of_tolerance(self):
        # Período 10% maior que o esperado → fora de ±5%
        ts = [i * 0.0011 for i in range(11)]
        m  = analyze_timing("period", ts, expected_period_s=0.001, tolerance_pct=5.0)
        assert m.within_limits is False

    def test_insufficient_samples(self):
        m = analyze_timing("period", [0.0], 0.001)
        assert math.isnan(m.value)

    def test_samples_stored(self):
        ts = [i * 0.001 for i in range(6)]   # 5 períodos
        m  = analyze_timing("p", ts, 0.001)
        assert len(m.samples) == 5

    def test_unit_is_seconds(self):
        ts = [0.0, 0.001, 0.002]
        m  = analyze_timing("p", ts, 0.001)
        assert m.unit == "s"


class TestAnalyzeJitter:

    def test_constant_period_zero_jitter(self):
        ts = [i * 0.001 for i in range(21)]
        m  = analyze_jitter("jitter", ts, expected_period_s=0.001)
        assert m.value == pytest.approx(0.0, abs=1e-9)
        assert m.within_limits is True

    def test_jitter_detected(self):
        ts = [0.0, 0.001, 0.0025, 0.003, 0.005]
        m  = analyze_jitter("jitter", ts, expected_period_s=0.001, limit_max_pct=5.0)
        assert m.value > 0

    def test_unit_percent(self):
        ts = [i * 0.001 for i in range(5)]
        m  = analyze_jitter("j", ts, 0.001)
        assert m.unit == "%"


# ─────────────────────────────────────────────────────────────────────────────
# Tensão
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyzeVoltage:

    def test_nominal_voltage(self):
        m = analyze_voltage("v33", [3.30, 3.31, 3.29, 3.30], nominal_v=3.3)
        assert m.value == pytest.approx(3.30, abs=0.01)
        assert m.within_limits is True

    def test_overvoltage_fails(self):
        m = analyze_voltage("v33", [3.50, 3.52], nominal_v=3.3, tolerance_pct=5.0)
        assert m.within_limits is False

    def test_empty_samples(self):
        m = analyze_voltage("v33", [], nominal_v=3.3)
        assert math.isnan(m.value)

    def test_unit_volts(self):
        m = analyze_voltage("v", [3.3], nominal_v=3.3)
        assert m.unit == "V"

    def test_limits_computed_correctly(self):
        m = analyze_voltage("v5", [5.0], nominal_v=5.0, tolerance_pct=10.0)
        assert m.limit_min == pytest.approx(4.5)
        assert m.limit_max == pytest.approx(5.5)


class TestAnalyzeRipple:

    def test_flat_signal_zero_ripple(self):
        m = analyze_ripple("ripple", [3.3, 3.3, 3.3, 3.3])
        assert m.value == pytest.approx(0.0, abs=1e-6)

    def test_ripple_detected(self):
        samples = [3.3 + 0.01 * (i % 2) for i in range(10)]
        m = analyze_ripple("ripple", samples, limit_max_mv=5.0)
        assert m.value == pytest.approx(10.0, abs=1.0)   # ~10 mV pk-pk
        assert m.within_limits is False

    def test_unit_mv(self):
        m = analyze_ripple("r", [3.3, 3.31])
        assert m.unit == "mV"


# ─────────────────────────────────────────────────────────────────────────────
# Frequência
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyzeFrequency:

    def test_exact_frequency(self):
        # 1 kHz → período 1 ms
        ts = [i * 0.001 for i in range(11)]
        m  = analyze_frequency("freq", ts, expected_hz=1000.0)
        assert m.value == pytest.approx(1000.0, rel=1e-6)
        assert m.within_limits is True

    def test_frequency_deviation(self):
        ts = [i * 0.0011 for i in range(11)]   # ~909 Hz em vez de 1 kHz
        m  = analyze_frequency("freq", ts, expected_hz=1000.0, tolerance_pct=1.0)
        assert m.within_limits is False

    def test_unit_hz(self):
        ts = [0.0, 0.001, 0.002]
        m  = analyze_frequency("f", ts, 1000.0)
        assert m.unit == "Hz"


# ─────────────────────────────────────────────────────────────────────────────
# Delay
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyzeDelay:

    def test_constant_delay(self):
        sends    = [0.000, 0.010, 0.020]
        receives = [0.001, 0.011, 0.021]   # atraso exato de 1 ms
        m = analyze_delay("latency", sends, receives)
        assert m.value == pytest.approx(1.0)   # ms
        assert m.unit  == "ms"

    def test_delay_limit(self):
        sends    = [0.0]
        receives = [0.010]   # 10 ms de atraso
        m = analyze_delay("lat", sends, receives, limit_max_ms=5.0)
        assert m.within_limits is False

    def test_delay_pass(self):
        sends    = [0.0]
        receives = [0.002]   # 2 ms
        m = analyze_delay("lat", sends, receives, limit_max_ms=5.0)
        assert m.within_limits is True

    def test_empty_lists(self):
        m = analyze_delay("lat", [], [])
        assert math.isnan(m.value)

    def test_multiple_samples_statistics(self):
        sends    = [0.000, 0.010, 0.020]
        receives = [0.001, 0.012, 0.022]   # atrasos: 1, 2, 2 ms
        m = analyze_delay("lat", sends, receives)
        assert len(m.samples) == 3
        assert m.value == pytest.approx(sum([1, 2, 2]) / 3)


# ─────────────────────────────────────────────────────────────────────────────
# TestResult com measurements
# ─────────────────────────────────────────────────────────────────────────────

class TestTestResultMeasurements:

    def test_result_has_measurements_field(self):
        from tests_builtin.base import TestResult, TestStatus
        r = TestResult(name="t", status=TestStatus.PASS, message="ok")
        assert r.measurements is None

    def test_result_to_dict_without_measurements(self):
        from tests_builtin.base import TestResult, TestStatus
        r = TestResult(name="t", status=TestStatus.PASS, message="ok",
                       duration_ms=12.5)
        d = r.to_dict()
        assert d["name"]        == "t"
        assert d["status"]      == "PASS"
        assert d["duration_ms"] == 12.5
        assert "measurements"   not in d

    def test_result_to_dict_with_measurements(self):
        from tests_builtin.base import TestResult, TestStatus
        ms = MeasurementSet()
        ms.add(Measurement("ber", 1e-7, limit_max=1e-5))
        r = TestResult(name="uart_test", status=TestStatus.PASS, message="OK",
                       measurements=ms)
        d = r.to_dict()
        assert "measurements" in d
        assert d["measurements"]["all_pass"] is True
        assert len(d["measurements"]["measurements"]) == 1
