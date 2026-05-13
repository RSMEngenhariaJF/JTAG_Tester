"""Smoke test do esqueleto da GUI (Sprint 01)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.gui.main_window import MainWindow

pytestmark = pytest.mark.gui

EXPECTED_TOP_LEVEL_MENUS = ["Arquivo", "Projeto", "Executar", "Ferramentas", "Ajuda"]


def _menu_titles(window: MainWindow) -> list[str]:
    bar = window.menuBar()
    titles: list[str] = []
    for action in bar.actions():
        menu = action.menu()
        if menu is not None:
            titles.append(action.text().replace("&", ""))
    return titles


def test_main_window_constructs(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.windowTitle().startswith("Plataforma de Bring-up")
    assert window.statusBar() is not None
    assert window.centralWidget() is not None


def test_main_window_has_required_menus(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    titles = _menu_titles(window)
    for expected in EXPECTED_TOP_LEVEL_MENUS:
        assert expected in titles, f"menu '{expected}' ausente; presentes: {titles}"


def test_status_bar_has_persistent_widgets(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    for attr in ("lbl_probe", "lbl_project", "lbl_plan", "lbl_instruments"):
        assert hasattr(window, attr), f"status bar deveria expor {attr}"
        assert getattr(window, attr).text(), f"{attr} sem texto inicial"
