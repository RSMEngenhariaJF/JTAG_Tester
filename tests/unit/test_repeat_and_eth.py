"""Repetições do plano (tests_builtin/repeat.py) e partes do teste de tráfego Ethernet
que não dependem da placa (quadros, layout da SRAM, contas de taxa, decisão).

O caminho completo do Ethernet (DMA + PHY em loopback) foi validado na placa CT;
aqui ficam a lógica e os limites.

Execução:
    pytest tests/unit/test_repeat_and_eth.py -v
"""

from __future__ import annotations

import pytest

from core.analysis import MeasurementSet
from core.analysis.metrics import Measurement
from core.project.config import ProjectConfig, TestPlanEntry
from tests_builtin.base import BuiltinTest, TestStatus
from tests_builtin.repeat import RepeatedTest, aggregate

# ── Repetições ────────────────────────────────────────────────────────────────

_SEQ: list[tuple[TestStatus, float]] = []


class _Seq(BuiltinTest):
    """Devolve a próxima (status, valor) de _SEQ; métrica com limite ≤ 10."""

    name = "Seq"

    def _run(self, pal):
        status, value = _SEQ.pop(0)
        ms = MeasurementSet()
        ms.add(Measurement("x", value, "V", limit_max=10.0))
        if status == TestStatus.ERROR:
            raise RuntimeError("caiu")
        return (self._pass if status == TestStatus.PASS else self._fail)(f"x={value}",
                                                                          measurements=ms)


class TestRepeat:
    def test_entry_round_trip(self) -> None:
        e = TestPlanEntry("a.py:X", "r", {}, repeat=5)
        assert TestPlanEntry.from_dict(e.to_dict()).repeat == 5
        assert "repeat" not in TestPlanEntry("a.py:X").to_dict()
        assert TestPlanEntry.from_dict({"test": "a.py:X", "repeat": 0}).repeat == 1

    def test_all_pass_aggregates_statistics(self) -> None:
        _SEQ[:] = [(TestStatus.PASS, v) for v in (2.0, 4.0, 6.0)]
        r = RepeatedTest(_Seq().configure({}, "L"), 3).run(None)
        assert r.status == TestStatus.PASS and r.name == "Seq — L"
        assert r.message.startswith("3/3 PASS em 3 repetições")
        x = next(m for m in r.measurements if m.name == "x")
        assert x.samples == [2.0, 4.0, 6.0] and x.value == 6.0          # pior: menor margem
        assert "média 4" in x.description and "desvio 2" in x.description
        rep = next(m for m in r.measurements if m.name == "repeticoes_aprovadas")
        assert rep.value == 3 and rep.within_limits

    def test_one_failure_fails_and_says_which(self) -> None:
        _SEQ[:] = [(TestStatus.PASS, 1.0), (TestStatus.FAIL, 12.0), (TestStatus.PASS, 3.0)]
        r = RepeatedTest(_Seq(), 3).run(None)
        assert r.status == TestStatus.FAIL
        assert "2/3 PASS" in r.message and "falharam: 2 (#2: x=12.0)" in r.message
        x = next(m for m in r.measurements if m.name == "x")
        assert x.value == 12.0 and x.within_limits is False

    def test_all_errors_is_error(self) -> None:
        _SEQ[:] = [(TestStatus.ERROR, 0.0)] * 2
        assert RepeatedTest(_Seq(), 2).run(None).status == TestStatus.ERROR

    def test_build_plan_wraps_only_repeated(self) -> None:
        from tests_builtin.plan import build_plan
        ref = "TESTES_PLATAFORMA/IO/piscar_led.py:PiscarLed"
        proj = ProjectConfig("P", "P", "b", test_plan=[
            TestPlanEntry(ref, "uma"), TestPlanEntry(ref, "tres", repeat=3)])
        a, b = build_plan(proj)
        assert not isinstance(a, RepeatedTest)
        assert isinstance(b, RepeatedTest) and b.times == 3 and b.name.endswith("tres")

    def test_aggregate_without_measurements(self) -> None:
        from tests_builtin.base import TestResult
        r = aggregate("T", [TestResult("T", TestStatus.SKIP, "s")] * 2)
        assert r.status == TestStatus.SKIP


# ── Ethernet: partes puras ────────────────────────────────────────────────────

class TestEthPieces:
    def test_frame_layout(self) -> None:
        from hal.eth_dma import ETHERTYPE, MAC_ADDR, frame_bytes
        f = frame_bytes(64, 1)
        assert len(f) == 60                                   # +4 de FCS no fio = 64
        assert f[:6] == MAC_ADDR and f[12:14] == ETHERTYPE.to_bytes(2, "big")
        assert frame_bytes(64, 1) == f and frame_bytes(64, 2) != f    # reprodutível, distinto

    def test_rates(self) -> None:
        from hal.eth_dma import BatchResult
        # 128 quadros de 1518 B a 100 Mbit/s: período = (1518+20)*8 ns*10 = 123,04 µs
        r = BatchResult(1518, 128, 128, 0, 0, 0, 128, 0, 127 * 123.04e-6, 0.02)
        assert r.line_mbps() == pytest.approx(100.0, rel=1e-6)
        assert r.data_mbps() == pytest.approx(100 * 1518 / 1538, rel=1e-6)
        assert r.fer == 0.0
        lost = BatchResult(64, 100, 98, 1, 1, 0, 98, 1, None, 0.01)
        assert lost.errors == 2 and lost.fer == pytest.approx(0.02) and lost.line_mbps() is None

    def test_layout_rejects_too_many_frames(self) -> None:
        from hal.eth_dma import EthTraffic
        t = EthTraffic.__new__(EthTraffic)
        t.ram_base, t.ram_size = 0x24008000, 0x70000
        assert t.layout(1518, 256, 4)["stride"] == 1536
        with pytest.raises(ValueError, match="não cabem"):
            t.layout(1518, 400, 4)

    def test_decision(self) -> None:
        from testbench import Observation, Trace
        mod = __import__("tests_builtin.plan", fromlist=["resolve_ref"]).resolve_ref(
            "TESTES_PLATAFORMA/BLOCOS/ethernet.py:EthernetTrafego")
        decision_cls = __import__(mod.__module__, fromlist=["_Trafego"])._Trafego
        stats = {"tamanho": 64, "enviados": 128, "recebidos": 128, "erros": 0,
                 "erros_crc": 0, "erros_dados": 0, "perdidos": 0, "comparados": 128,
                 "fer": 0.0, "bits": 128 * 64 * 8, "mbps_fio": 99.7, "mbps_dados": 75.9,
                 "quadros_s": 148_000.0, "utilizacao_pct": 99.7,
                 "teorico_quadros_s": 148_809.0, "notas": []}
        tr = Trace()
        tr.observations.append(Observation(0, "64 B", 0.0, {"eth": 64}, {"m": stats}))
        v = decision_cls("m", 64, 0.0, 95.0).evaluate(tr)
        assert v.ok and {m.name for m in v.measurements} >= {"eth_fer_64B", "eth_ocupacao_pct_64B",
                                                            "eth_ber_max_64B"}
        slow = dict(stats, utilizacao_pct=80.0)
        tr.observations[0] = Observation(0, "64 B", 0.0, {"eth": 64}, {"m": slow})
        assert decision_cls("m", 64, 0.0, 95.0).evaluate(tr).ok is False

    def test_invalid_sizes_fail_before_hardware(self) -> None:
        from core.project.config import PeripheralRef, PinDef, set_active_project
        from tests_builtin.plan import resolve_ref
        proj = ProjectConfig("P", "P", "b", pins={
            "mdc": PinDef("GPIOC", 1, peripheral=PeripheralRef("ETH", "ETH", "MDC"))})
        set_active_project(proj)
        try:
            cls = resolve_ref("TESTES_PLATAFORMA/BLOCOS/ethernet.py:EthernetTrafego")
            r = cls().configure({"periferico": "ETH", "tamanhos": "32, 64"}).run(None)
        finally:
            set_active_project(None)
        assert r.status == TestStatus.FAIL and "entre 64 e 1518" in r.message
