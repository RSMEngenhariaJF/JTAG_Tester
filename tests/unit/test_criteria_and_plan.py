"""Testes unitários: tolerâncias do perfil nas medidas/relatórios e plano de testes
parametrizado (params, plano no projeto, Piscar LED, editor da aba).

Execução:
    pytest tests/unit/test_criteria_and_plan.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.analysis import MeasurementSet, analyze_ber, analyze_frequency
from core.analysis.config import AnalysisConfig, MetricConfig, set_active_analysis_config
from core.analysis.criteria_report import criteria_dict, criteria_rows, margin_text
from core.analysis.metrics import SOURCE_DEFAULT, Measurement, apply_criteria
from core.project.config import PinDef, ProjectConfig, TestPlanEntry, set_active_project
from tests_builtin import params as tp
from tests_builtin.base import BuiltinTest, TestResult, TestStatus

ROOT = Path(__file__).resolve().parents[2]
PISCAR = "TESTES_PLATAFORMA/IO/piscar_led.py:PiscarLed"


@pytest.fixture(autouse=True)
def clean_globals():
    set_active_analysis_config(None)
    yield
    set_active_analysis_config(None)
    set_active_project(None)


def _profile(**metrics) -> AnalysisConfig:
    return AnalysisConfig(name="Teste", version="2.1",
                          metrics={k: MetricConfig(**v) for k, v in metrics.items()})


# ── Tolerâncias ───────────────────────────────────────────────────────────────

class TestCriteria:
    def test_without_profile_marks_default(self) -> None:
        ms = MeasurementSet()
        ms.add(analyze_frequency("mco_freq", [0, 1e-6, 2e-6], 1e6, tolerance_pct=1))
        m = ms.get("mco_freq")
        assert m.limit_source == SOURCE_DEFAULT and m.nominal == 1e6

    def test_profile_wins_and_uses_measurement_nominal(self) -> None:
        set_active_analysis_config(_profile(mco_freq={"tolerance_pct": 5.0}))
        ms = MeasurementSet()
        ms.add(analyze_frequency("mco_freq", [0, 1e-6, 2e-6], 1e6, tolerance_pct=1))
        m = ms.get("mco_freq")
        assert (m.limit_min, m.limit_max) == pytest.approx((0.95e6, 1.05e6))
        assert m.limit_source == "perfil Teste v2.1"

    def test_profile_nominal_overrides(self) -> None:
        set_active_analysis_config(_profile(v_3v3={"tolerance_pct": 1.0, "nominal": 3.3}))
        m = apply_criteria(Measurement("v_3v3", 3.31, "V", nominal=3.0))
        assert m.nominal == 3.3 and m.limit_max == pytest.approx(3.333)

    def test_prefix_match(self) -> None:
        cfg = _profile(uart_ber={"limit_max": 1e-6}, uart={"limit_max": 9.0})
        assert cfg.match("uart_ber_115200")[0] == "uart_ber"     # prefixo mais longo
        assert cfg.match("uartx") is None
        m = apply_criteria(analyze_ber("uart_ber_115200", b"ab", b"ab", limit_max=0.0), cfg)
        assert m.limit_max == 1e-6

    def test_empty_metric_ignored(self) -> None:
        cfg = _profile(x={"description": "só anotação"})
        assert cfg.match("x") is None

    @pytest.mark.parametrize("lo,hi,v,expected", [
        (0.0, 10.0, 5.0, 50.0), (0.0, 10.0, 9.0, 10.0), (0.0, 10.0, 11.0, -10.0),
        (None, 2.0, 1.5, 25.0), (1.0, None, 1.2, 20.0), (None, 0.0, 0.0, None),
    ])
    def test_margin(self, lo, hi, v, expected) -> None:
        m = Measurement("m", v, limit_min=lo, limit_max=hi)
        if expected is None:
            assert m.margin_pct is None
        else:
            assert m.margin_pct == pytest.approx(expected)

    def test_margin_text_and_dict(self) -> None:
        m = Measurement("m", 9.0, limit_min=0.0, limit_max=10.0, limit_source="perfil P v1")
        assert margin_text(m) == "+10,0 %"
        d = m.to_dict()
        assert d["limit_source"] == "perfil P v1" and d["margin_pct"] == 10.0

    def test_criteria_section_rows(self) -> None:
        crit = criteria_dict(_profile(v={"tolerance_pct": 2.0, "nominal": 5.0},
                                      b={"limit_max": 1e-7}))
        assert criteria_rows(crit) == [["b", "≤ 1e-07", ""], ["v", "± 2 % de 5", ""]]
        assert criteria_dict(None) is None

    def test_reports_show_profile_and_margin(self) -> None:
        from core.analysis.report import HtmlReport
        from core.analysis.report_pdf import PdfReport
        set_active_analysis_config(_profile(mco_freq={"tolerance_pct": 5.0}))
        ms = MeasurementSet()
        ms.add(analyze_frequency("mco_freq", [0, 1e-6, 2e-6], 1e6))
        res = [TestResult("Osc", TestStatus.PASS, "ok", measurements=ms)]
        crit = criteria_dict(_profile(mco_freq={"tolerance_pct": 5.0}))
        for html in (HtmlReport(criteria=crit).generate(res),
                     PdfReport(criteria=crit).build_html(res)):
            assert "Critérios de análise" in html and "Perfil Teste v2.1" in html
            assert "Margem" in html and "perfil Teste v2.1" in html
        assert "Nenhum perfil" in HtmlReport().generate(res)


# ── Parâmetros ────────────────────────────────────────────────────────────────

def _project() -> ProjectConfig:
    from core.project.config import PeripheralRef
    return ProjectConfig("P", "P-1", "nucleo_f446re", pins={
        "led": PinDef("GPIOA", 5, "LED"),
        "rele": PinDef("GPIOB", 3, active_low=True),
        "tx": PinDef("GPIOA", 2, peripheral=PeripheralRef(periph_type="UART", name="USART2")),
    })


class TestParams:
    PARAMS = {
        "pinos": tp.Signals("Pinos"),
        "n": tp.Int("Ciclos", 3, 1, 10, unit="x"),
        "f": tp.Float("Freq", 1.5, 0.0, 10.0, unit="Hz"),
        "modo": tp.Choice("Modo", ("a", "b")),
        "ok": tp.Bool("Ativo", True),
    }

    def test_defaults_and_describe(self) -> None:
        assert tp.defaults(self.PARAMS) == {"pinos": [], "n": 3, "f": 1.5, "modo": "a", "ok": True}
        d = tp.describe(self.PARAMS, {"pinos": ["led", "rele"]})
        assert d == {"Pinos": "led, rele", "Ciclos": "3 x", "Freq": "1.5 Hz",
                     "Modo": "a", "Ativo": "sim"}

    def test_validate(self) -> None:
        proj = _project()
        assert tp.validate(self.PARAMS, {"pinos": ["led"]}, proj) == []
        bad = {"pinos": ["tx", "xx"], "n": 99, "modo": "z", "zz": 1}
        errs = tp.validate(self.PARAMS, bad, proj)
        joined = " | ".join(errs)
        assert "'tx' não é do tipo GPIO" in joined and "'xx' não existe" in joined
        assert "fora de [1, 10]" in joined and "opção 'z'" in joined
        assert "desconhecido: zz" in joined
        assert "ao menos 1" in tp.validate(self.PARAMS, {}, proj)[0]

    def test_resolve_signals(self) -> None:
        ns = tp.resolve(self.PARAMS, {"pinos": ["rele"]}, _project())
        (s,) = ns.pinos
        assert (s.name, s.port, s.pin, s.active_low) == ("rele", "GPIOB", 3, True)


class _Dummy(BuiltinTest):
    name = "Dummy"
    params = {"pinos": tp.Signals("Pinos"), "n": tp.Int("N", 2, 1, 5)}

    def _run(self, pal) -> TestResult:
        return self._pass(f"{[s.name for s in self.p.pinos]} n={self.p.n}")


class TestParametrizedRun:
    def test_configure_label_and_params_in_result(self) -> None:
        set_active_project(_project())
        r = _Dummy().configure({"pinos": ["led"], "n": 4}, "LEDs").run(MagicMock())
        assert r.status == TestStatus.PASS and r.name == "Dummy — LEDs"
        assert r.message == "['led'] n=4"
        assert r.params == {"Pinos": "led", "N": "4"} and r.to_dict()["params"]["N"] == "4"

    def test_invalid_params_give_error(self) -> None:
        set_active_project(_project())
        r = _Dummy().configure({"pinos": ["nao_existe"]}).run(MagicMock())
        assert r.status == TestStatus.ERROR and "não existe" in r.message

    def test_no_project(self) -> None:
        set_active_project(None)
        r = _Dummy().configure({"pinos": ["led"]}).run(MagicMock())
        assert r.status == TestStatus.ERROR and "Nenhum projeto" in r.message


# ── Plano no projeto ──────────────────────────────────────────────────────────

class TestPlan:
    def test_roundtrip_json(self) -> None:
        proj = _project()
        proj.test_plan = [TestPlanEntry(PISCAR, "LEDs", {"pinos": ["led"]}),
                          TestPlanEntry(PISCAR, "Off", {}, enabled=False)]
        back = ProjectConfig.from_dict(json.loads(json.dumps(proj.to_dict())))
        assert back.test_plan == proj.test_plan
        assert "enabled" not in proj.to_dict()["test_plan"][0]

    def test_build_plan_order_enabled_and_broken(self) -> None:
        from tests_builtin.plan import build_plan
        proj = _project()
        proj.test_plan = [
            TestPlanEntry(PISCAR, "A", {"pinos": ["led"]}),
            TestPlanEntry(PISCAR, "B", {"pinos": ["led"]}, enabled=False),
            TestPlanEntry("TESTES_PLATAFORMA/IO/nao_existe.py:X", "C"),
        ]
        tests = build_plan(proj)
        assert [t.name for t in tests] == ["Piscar LED — A", "Plano — C"]
        assert tests[1].run(MagicMock()).status == TestStatus.ERROR
        assert build_plan(None) == []

    def test_library_lists_piscar_led(self) -> None:
        from tests_builtin.plan import list_library
        assert PISCAR in [i.ref for i in list_library()]

    def test_shipped_projects_plans_are_valid(self) -> None:
        from core.project.loader import find_projects
        from tests_builtin.plan import resolve_ref
        for proj in find_projects():
            for e in proj.test_plan:
                assert tp.validate(resolve_ref(e.test).params, e.params, proj) == [], proj.name


# ── Piscar LED ────────────────────────────────────────────────────────────────

class _FakePal:
    """GPIO mínimo: BSRR atualiza ODR; registra escritas de MODER."""

    def __init__(self) -> None:
        self.odr: dict[str, int] = {}
        self.moder: dict[tuple[str, int], int] = {}

    def modify_field(self, periph, reg, field, value) -> None:
        if reg == "MODER":
            self.moder[(periph, int(field[5:]))] = value
        elif reg == "ODR":
            bit = int(field[3:])
            cur = self.odr.get(periph, 0)
            self.odr[periph] = (cur | (1 << bit)) if value else (cur & ~(1 << bit))

    def read_field(self, periph, reg, field) -> int:
        if reg == "MODER":
            return self.moder.get((periph, int(field[5:])), 0b11)
        return (self.odr.get(periph, 0) >> int(field[3:])) & 1

    def write_reg(self, periph, reg, value) -> None:
        cur = self.odr.get(periph, 0)
        self.odr[periph] = (cur | (value & 0xFFFF)) & ~(value >> 16)


class TestPiscarLed:
    def test_blinks_and_restores(self, monkeypatch) -> None:
        import time

        from boards.nucleo_f446re import BOARD
        from core.board.config import set_active_board
        from tests_builtin.plan import resolve_ref
        monkeypatch.setattr(time, "sleep", lambda _s: None)
        from core.pal.access import PeripheralAccessLayer
        from core.svd.parser import parse
        from tests.unit.test_testbench import GpioSim

        set_active_board(BOARD)
        set_active_project(_project())
        dev = parse(ROOT / "devices/stm32f446/STM32F446.svd")    # PAL com SVD real (F446)
        pal = PeripheralAccessLayer(GpioSim(dev), dev)
        moder = {p: pal.read_reg(p, "MODER") for p in ("GPIOA", "GPIOB")}
        t = resolve_ref(PISCAR)().configure(
            {"pinos": ["led", "rele"], "ciclos": 2, "periodo_ms": 20}, "Saídas")
        r = t.run(pal)
        assert r.status == TestStatus.PASS, r.message
        assert {p: pal.read_reg(p, "MODER") for p in moder} == moder       # restaurado
        assert r.params["Pinos"] == "led, rele"


# ── Editor da aba "Plano de testes" ───────────────────────────────────────────

class TestPlanEditorWidget:
    def test_form_and_signals(self, qtbot) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QListWidget

        from app.gui.test_plan_editor import TestPlanEditor
        pins = _project().pins
        ed = TestPlanEditor(lambda: pins, library_provider=lambda: [])
        qtbot.addWidget(ed)
        ed.set_entries([TestPlanEntry(PISCAR, "LEDs", {"pinos": ["led"]})])

        sig = next(w for w in ed._scroll.widget().findChildren(QListWidget))
        names = [sig.item(i).data(Qt.ItemDataRole.UserRole) for i in range(sig.count())]
        assert names == ["led", "rele"]                       # "tx" (UART) filtrado
        sig.item(1).setCheckState(Qt.CheckState.Checked)
        (e,) = ed.entries()
        assert e.params["pinos"] == ["led", "rele"] and e.params["ciclos"] == 3
        assert ed.validate(pins) == []
        assert "não existe" in ed.validate({})[0]

    def test_duplicate_move_remove(self, qtbot) -> None:
        from app.gui.test_plan_editor import TestPlanEditor
        ed = TestPlanEditor(lambda: {}, library_provider=lambda: [])
        qtbot.addWidget(ed)
        ed.set_entries([TestPlanEntry(PISCAR, "A"), TestPlanEntry(PISCAR, "B")])
        ed._list.setCurrentRow(0)
        ed._duplicate()
        assert [e.label for e in ed.entries()] == ["A", "A (cópia)", "B"]
        ed._move(1)
        assert [e.label for e in ed.entries()] == ["A", "B", "A (cópia)"]
        ed._remove()                                         # seleção acompanhou o item movido
        assert [e.label for e in ed.entries()] == ["A", "B"]


# ── Correções vistas na revisão visual ────────────────────────────────────────

class TestReviewFixes:
    def test_project_dialog_selects_saved_board(self, qtbot) -> None:
        from app.gui.project_dialog import ProjectEditorDialog
        from core.project.loader import find_projects
        proj = next(p for p in find_projects() if p.project_code == "NUCLEO-H753-001")
        dlg = ProjectEditorDialog(None, proj)
        qtbot.addWidget(dlg)
        assert dlg._board_combo.currentData() == "NUCLEO-H753ZI"
        assert dlg._plan_editor.entries()[0].label == "LEDs indicadores"

    def test_params_in_reports(self) -> None:
        from core.analysis.report import HtmlReport
        from core.analysis.report_pdf import PdfReport
        res = [TestResult("Piscar LED — LEDs", TestStatus.PASS, "ok",
                          params={"Pinos": "led, rele", "Ciclos": "2"})]
        # os parâmetros ficam no registro por teste ("Parâmetros aplicados"), não no resumo
        for html in (HtmlReport().generate(res), PdfReport().build_html(res)):
            assert "Parâmetros aplicados" in html
            assert "Pinos" in html and "led, rele" in html and "Ciclos" in html


class TestPlanDiscoverability:
    """O plano tem de ser alcançável pela aba Testes da janela principal."""

    def _win(self, qtbot):
        from app.gui.main_window import MainWindow
        from tests.unit.test_main_window import FakeDevice, FakeRunner
        dev = FakeDevice()
        win = MainWindow(device=dev, runner=FakeRunner(dev))
        qtbot.addWidget(win)
        return win

    def test_edit_plan_button_opens_plan_tab(self, qtbot, monkeypatch) -> None:
        import app.gui.main_window as mw
        win = self._win(qtbot)
        opened = {}

        def fake_exec(dlg):
            opened["tab"] = dlg._tabs.tabText(dlg._tabs.currentIndex())
            return 0

        monkeypatch.setattr(mw.ProjectEditorDialog, "exec", fake_exec)
        assert win._btn_edit_plan.text().startswith("Editar plano")
        win._btn_edit_plan.click()
        assert opened["tab"] == "Plano de testes"

    def test_plugin_with_params_goes_to_plan(self, qtbot, monkeypatch) -> None:
        import app.gui.main_window as mw
        win = self._win(qtbot)
        plugin = str(ROOT / "TESTES_PLATAFORMA" / "IO" / "piscar_led.py")
        monkeypatch.setattr(mw.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (plugin, "")))
        monkeypatch.setattr(mw.QMessageBox, "question",
                            staticmethod(lambda *a: mw.QMessageBox.StandardButton.Yes))
        seen = {}

        def fake_exec(dlg):
            seen["labels"] = [e.test for e in dlg._plan_editor.entries()]
            seen["tab"] = dlg._tabs.tabText(dlg._tabs.currentIndex())
            return 0

        monkeypatch.setattr(mw.ProjectEditorDialog, "exec", fake_exec)
        win._load_plugin()
        assert seen["tab"] == "Plano de testes"
        assert seen["labels"][-1] == PISCAR
        assert win._plugin_list.count() == 0          # não vira plugin solto sem pinos
