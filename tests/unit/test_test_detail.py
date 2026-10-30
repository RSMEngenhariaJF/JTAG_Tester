"""Testes do painel de detalhes do teste (app/gui/test_detail.py) e da ligação na janela.

Execução:
    pytest tests/unit/test_test_detail.py -v
"""

from __future__ import annotations

import pytest

from app.gui.test_detail import entry_html, result_html, result_name
from core.analysis import MeasurementSet
from core.analysis.metrics import Measurement
from core.project.config import (
    PeripheralRef,
    PinDef,
    ProjectConfig,
    TestPlanEntry,
    set_active_project,
)
from tests_builtin.base import TestResult, TestStatus

PISCAR = "TESTES_PLATAFORMA/IO/piscar_led.py:PiscarLed"
UART = "TESTES_PLATAFORMA/BLOCOS/comunicacao.py:UartLoopback"


@pytest.fixture
def project():
    proj = ProjectConfig("P", "P-1", "nucleo_h753zi", pins={
        "led": PinDef("GPIOB", 0, "LD1"),
        "rele": PinDef("GPIOB", 14, active_low=True),
        "tx": PinDef("GPIOC", 12, peripheral=PeripheralRef("UART", "UART5", "TX")),
        "rx": PinDef("GPIOD", 2, peripheral=PeripheralRef("UART", "UART5", "RX")),
    }, test_plan=[
        TestPlanEntry(PISCAR, "LEDs", {"pinos": ["led", "rele"], "ciclos": 3}),
        TestPlanEntry(UART, "RS232", {"periferico": "UART5"}, enabled=False),
        TestPlanEntry("TESTES_PLATAFORMA/nao_existe.py:X", "quebrado"),
    ])
    set_active_project(proj)
    yield proj
    set_active_project(None)


def _result(name: str, status=TestStatus.PASS) -> TestResult:
    ms = MeasurementSet()
    ms.add(Measurement("gpio_divergencias_led", 0.0, "amostras", limit_max=0.0))
    return TestResult(name, status, "2 saída(s) piscaram 3x", duration_ms=12.3, measurements=ms)


class TestHtml:
    def test_entry_shows_description_params_and_pins(self, project) -> None:
        html = entry_html(project.test_plan[0], project)
        assert "LEDs" in html and "Piscar LED" in html and "categoria" in html
        assert "led → <b>PB0</b>" in html
        assert "rele → <b>PB14</b> (ativo-baixo)" in html
        assert "Ainda não executado" in html

    def test_peripheral_param_lists_pins_by_role(self, project) -> None:
        html = entry_html(project.test_plan[1], project)
        assert "<b>UART5</b> — TX: PC12, RX: PD2" in html
        assert "pausado" in html

    def test_broken_entry(self, project) -> None:
        assert "Não foi possível carregar" in entry_html(project.test_plan[2], project)

    def test_result_with_metrics(self, project) -> None:
        html = result_html(_result("x", TestStatus.FAIL))
        assert "FAIL" in html and "gpio_divergencias_led" in html and "padrão do teste" in html

    def test_result_name_matches_runtime_name(self, project) -> None:
        from tests_builtin.plan import build_plan
        assert result_name(project.test_plan[0]) == build_plan(project)[0].name


class TestMainWindowDetail:
    def test_click_plan_entry_and_result_row(self, qtbot, project) -> None:
        from tests.unit.test_main_window import FakeDevice, FakeRunner

        from app.gui.main_window import MainWindow

        dev = FakeDevice()
        win = MainWindow(device=dev, runner=FakeRunner(dev))
        qtbot.addWidget(win)
        win._active_project = project
        win._refresh_project_tests()

        # clique no teste do plano → descrição e pinos, ainda sem resultado
        win._project_tests_list.setCurrentRow(0)
        texto = win._detail.browser.toPlainText()
        assert "Piscar LED" in texto and "PB0" in texto and "Ainda não executado" in texto

        # o resultado chega com o painel aberto nesse teste → atualiza sozinho
        nome = result_name(project.test_plan[0])
        win._on_test_started(nome)
        win._on_test_finished(_result(nome))
        assert "2 saída(s) piscaram 3x" in win._detail.browser.toPlainText()

        # linha de resultado de teste embutido → só o resultado
        win._on_test_started("Clocks")
        win._on_test_finished(TestResult("Clocks", TestStatus.PASS, "Clocks habilitados"))
        win._table.selectRow(1)
        texto = win._detail.browser.toPlainText()
        assert "Clocks habilitados" in texto and "Parâmetros" not in texto

        # linha do plano na tabela → volta aos detalhes completos do teste
        win._table.selectRow(0)
        assert "PB0" in win._detail.browser.toPlainText()
