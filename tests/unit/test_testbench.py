"""Testes unitários do testbench modular (src/testbench) e dos scripts de GPIO
reescritos nele (Piscar LED, GPIO Output/Input e os blocos de BLOCOS/gpio.py).

O PAL simulado usa o SVD real do H753 e um modelo de pino: saída lê o ODR;
entrada lê o pull interno, um nível externo forçado ou um fio de loopback.

Execução:
    pytest tests/unit/test_testbench.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.pal.access import PeripheralAccessLayer
from core.project.config import PinDef, ProjectConfig, set_active_project
from core.svd.parser import parse
from testbench import ComposedTest, Driver, Monitor, Step, Stimulus, Testbench
from testbench.decision import Expect, FollowsDrive, Report
from testbench.gpio import GpioInputMonitor, GpioLatchMonitor, GpioOutputDriver
from testbench.stimulus import Chain, Levels, Sample, Toggle
from tests_builtin.base import TestStatus
from tests_builtin.params import Signal
from tests_builtin.plan import resolve_ref

ROOT = Path(__file__).resolve().parents[2]
SVD_H7 = ROOT / "devices/stm32h753/STM32H753.svd"


class GpioSim:
    """Memória + modelo elétrico de GPIO sobre os endereços do SVD."""

    def __init__(self, dev) -> None:
        self.m: dict[int, int] = {}
        self.dev = dev
        self.forced: dict[tuple[str, int], int] = {}      # nível externo forte
        self.wires: dict[tuple[str, int], tuple[str, int]] = {}   # entrada ← saída
        self._idr = {dev.peripheral(p).address_of("IDR"): p for p in dev.peripheral_names()
                     if p.startswith("GPIO")}
        self._bsrr = {dev.peripheral(p).address_of("BSRR"): p for p in self._idr.values()}

    def _reg(self, port: str, reg: str) -> int:
        return self.m.get(self.dev.peripheral(port).address_of(reg), 0)

    def _level(self, port: str, pin: int) -> int:
        mode = self._reg(port, "MODER") >> (2 * pin) & 3
        if mode == 1:
            return self._reg(port, "ODR") >> pin & 1
        if (port, pin) in self.forced:
            return self.forced[(port, pin)]
        if (port, pin) in self.wires:
            return self._level(*self.wires[(port, pin)])
        pull = self._reg(port, "PUPDR") >> (2 * pin) & 3
        return 1 if pull == 1 else 0

    def read_mem32(self, addr: int) -> int:
        if addr in self._idr:
            port = self._idr[addr]
            return sum(self._level(port, i) << i for i in range(16))
        return self.m.get(addr, 0)

    def write_mem32(self, addr: int, value: int) -> None:
        if addr in self._bsrr:
            odr = self.dev.peripheral(self._bsrr[addr]).address_of("ODR")
            cur = self.m.get(odr, 0)
            self.m[odr] = (cur | (value & 0xFFFF)) & ~(value >> 16) & 0xFFFF
            return
        self.m[addr] = value & 0xFFFFFFFF


@pytest.fixture
def sim():
    dev = parse(SVD_H7)
    s = GpioSim(dev)
    return s, PeripheralAccessLayer(s, dev)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    import time
    monkeypatch.setattr(time, "sleep", lambda _s: None)


@pytest.fixture
def project():
    proj = ProjectConfig("P", "P-1", "nucleo_h753zi", pins={
        "led": PinDef("GPIOB", 0, "LD1"),
        "rele": PinDef("GPIOB", 14, active_low=True),
        "botao": PinDef("GPIOC", 13),
        "in": PinDef("GPIOA", 3),
    })
    set_active_project(proj)
    from boards.nucleo_h753zi import BOARD
    from core.board.config import set_active_board
    set_active_board(BOARD)
    yield proj
    set_active_project(None)


def _run(ref: str, params: dict, pal):
    return resolve_ref(ref)().configure(params, "t").run(pal)


# ── Núcleo ────────────────────────────────────────────────────────────────────

class _Rec(Driver, Monitor):
    """Driver e monitor de mentira ligados pelo mesmo "fio" (dict compartilhado)."""

    def __init__(self, name, log, wire=None) -> None:
        self.name, self.log = name, log
        self.wire = wire if wire is not None else {"v": 0}

    def setup(self, pal):
        self.log.append(f"setup {self.name}")

    def apply(self, pal, value):
        self.wire["v"] = value

    def sample(self, pal):
        return self.wire["v"]

    def teardown(self, pal):
        self.log.append(f"teardown {self.name}")


class TestCore:
    def test_order_trace_and_teardown_on_error(self) -> None:
        log: list[str] = []
        wire = {"v": 0}; d, m = _Rec("d", log, wire), _Rec("m", log, wire)  # noqa: E702
        tb = Testbench([d], [m], Levels("d", [1, 0], wait_s=0), [])
        trace, _ = tb.run(None)
        assert log == ["setup d", "setup m", "teardown m", "teardown d"]
        assert [o.driven for o in trace.observations] == [{"d": 1}, {"d": 0}]

        class Boom(Stimulus):
            def steps(self):
                yield Step({"d": 1})
                raise RuntimeError("falhou no meio")

        log.clear()
        with pytest.raises(RuntimeError):
            Testbench([d], [m], Boom()).run(None)
        assert log[-2:] == ["teardown m", "teardown d"]       # restaura mesmo com erro

    def test_stimuli(self) -> None:
        steps = list(Toggle(["a", "b"], 2, 0.1, sequential=True).steps())
        assert [s.drive for s in steps][:2] == [{"a": True}, {"a": False}]
        assert len(steps) == 8 and steps[0].wait_s == pytest.approx(0.05)
        assert next(iter(Toggle(["a", "b"], 1, 0.1, sequential=False).steps())).drive == \
            {"a": True, "b": True}
        assert [s.label for s in Chain(Levels("x", [0]), Sample(2)).steps()] == \
            ["x=0", "leitura #1", "leitura #2"]

    def test_decisions_metrics(self) -> None:
        log: list[str] = []
        wire = {"v": 0}; d, m = _Rec("d", log, wire), _Rec("m", log, wire)  # noqa: E702
        _trace, (follow, exp, rep) = Testbench(
            [d], [m], Levels("d", [1, 0], wait_s=0),
            [FollowsDrive("m", "d", label="x"), Expect("m", 1, label="x"), Report("m")]).run(None)
        assert follow.ok and follow.measurements[0].value == 0
        assert exp.ok is False and exp.measurements[0].value == 1
        assert rep.ok is None and rep.message == "m=0"

    def test_composed_profile_can_relax_criterion(self) -> None:
        from core.analysis.config import AnalysisConfig, MetricConfig, set_active_analysis_config

        class T(ComposedTest):
            name = "T"

            def build(self):
                log: list[str] = []
                wire = {"v": 0}; d, m = _Rec("d", log, wire), _Rec("m", log, wire)  # noqa: E702
                return Testbench([d], [m], Levels("d", [1, 0, 1], wait_s=0),
                                 [Expect("m", 1, label="x", metric="cnt")])

        assert T().run(None).status == TestStatus.FAIL          # 1 divergência > 0
        set_active_analysis_config(AnalysisConfig("P", metrics={"cnt": MetricConfig(limit_max=1)}))
        try:
            r = T().run(None)
        finally:
            set_active_analysis_config(None)
        assert r.status == TestStatus.PASS                       # perfil permite 1
        assert next(iter(r.measurements)).limit_source.startswith("perfil P")


# ── Componentes de GPIO ───────────────────────────────────────────────────────

class TestGpioComponents:
    def test_driver_respects_active_low_and_restores(self, sim) -> None:
        _, pal = sim
        rele = Signal("rele", "GPIOB", 14, active_low=True)
        before = pal.read_reg("GPIOB", "MODER")
        trace, _ = Testbench([GpioOutputDriver(rele)], [GpioLatchMonitor(rele),
                             GpioLatchMonitor(rele, raw=True, name="raw")],
                             Levels("out:rele", [True, False], wait_s=0)).run(pal)
        assert trace.series("odr:rele") == [True, False]
        assert trace.series("raw") == [0, 1]                     # ativo-baixo: ativo = 0
        assert pal.read_reg("GPIOB", "MODER") == before

    def test_input_monitor_pull(self, sim) -> None:
        _, pal = sim
        sig = Signal("in", "GPIOA", 3)
        trace, _ = Testbench(monitors=[GpioInputMonitor(sig, pull="pull-up", raw=True)],
                             stimulus=Sample(1)).run(pal)
        assert trace.series("in:in") == [1]


# ── Scripts reescritos ────────────────────────────────────────────────────────

class TestRewrittenScripts:
    def test_piscar_led(self, sim, project) -> None:
        _, pal = sim
        r = _run("TESTES_PLATAFORMA/IO/piscar_led.py:PiscarLed",
                 {"pinos": ["led", "rele"], "ciclos": 2, "periodo_ms": 20}, pal)
        assert r.status == TestStatus.PASS
        assert r.message == "2 saída(s) piscaram 2x: led, rele"
        assert {m.name for m in r.measurements} == {"gpio_divergencias_led",
                                                    "gpio_divergencias_rele"}

    def test_gpio_output_and_input_plugins(self, sim, project) -> None:
        from tests_builtin.loader import PluginLoader
        _, pal = sim
        (out,) = PluginLoader.load_from_file(ROOT / "TESTES_PLATAFORMA/IO/teste_gpio_output.py")
        r = out.run(pal)
        assert r.status == TestStatus.PASS and r.message == "GPIOB.0 SET=1 RESET=0 OK"
        (inp,) = PluginLoader.load_from_file(ROOT / "TESTES_PLATAFORMA/IO/teste_gpio_input.py")
        r = inp.run(pal)
        assert r.status == TestStatus.PASS and r.message == "GPIOC.13 = LOW (solto)"

    def test_nivel_entrada(self, sim, project) -> None:
        s, pal = sim
        ref = "TESTES_PLATAFORMA/BLOCOS/gpio.py:NivelEntrada"
        assert _run(ref, {"pinos": ["botao"], "esperado": "inativo"}, pal).status == TestStatus.PASS
        s.forced[("GPIOC", 13)] = 1
        r = _run(ref, {"pinos": ["botao"], "esperado": "inativo"}, pal)
        assert r.status == TestStatus.FAIL and "botao: ativo" in r.message
        r = _run(ref, {"pinos": ["botao"], "esperado": "qualquer (só registra)"}, pal)
        assert r.status == TestStatus.PASS and r.message == "botao=ativo"

    def test_pull_curto(self, sim, project) -> None:
        s, pal = sim
        ref = "TESTES_PLATAFORMA/BLOCOS/gpio.py:PullCurto"
        r = _run(ref, {"pinos": ["in", "botao"]}, pal)
        assert r.status == TestStatus.PASS and r.message == "2 pino(s) seguem o pull: in, botao"
        s.forced[("GPIOA", 3)] = 0
        r = _run(ref, {"pinos": ["in", "botao"]}, pal)
        assert r.status == TestStatus.FAIL and "in (GPIOA3) preso em 0 (curto a GND?)" in r.message

    def test_loopback(self, sim, project) -> None:
        s, pal = sim
        ref = "TESTES_PLATAFORMA/BLOCOS/gpio.py:LoopbackGpio"
        params = {"saida": ["led"], "entrada": ["in"]}
        assert _run(ref, params, pal).status == TestStatus.FAIL     # sem fio
        s.wires[("GPIOA", 3)] = ("GPIOB", 0)
        r = _run(ref, params, pal)
        assert r.status == TestStatus.PASS and r.message == "led→in: 0→0, 1→1"

    def test_existing_plans_still_valid(self) -> None:
        from core.project.loader import find_projects
        from tests_builtin import params as tp
        for proj in find_projects():
            for e in proj.test_plan:
                assert tp.validate(resolve_ref(e.test).params, e.params, proj) == [], e.label
