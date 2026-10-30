"""Testes unitários da MainWindow (Sprint 12).

Usa FakeDevice e FakeRunner para isolar a GUI do hardware e do QThread.
Usa pytest-qt (qtbot) para interagir com widgets.

Execução:
    pytest tests/unit/test_main_window.py -v
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from PySide6.QtCore import Signal, QObject
from PySide6.QtWidgets import QPushButton, QTableWidget

from app.gui.main_window import MainWindow
from tests_builtin import STANDARD_SUITE
from tests_builtin.base import TestResult, TestStatus


# ---------------------------------------------------------------------------
# Doubles de servico (sem Qt real — so sinais)
# ---------------------------------------------------------------------------


class FakeDevice(QObject):
    """DeviceService stub controlavel por testes."""

    probe_connected    = Signal(str)
    probe_disconnected = Signal()
    probe_error        = Signal(str)
    mcu_identified     = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._connected = False
        self.idcode = 0x10006421   # STM32F446 — usado por identify()

    def identify(self, probe=None):
        from core.target import McuInfo
        info = McuInfo(0x2BA01477, 0x410FC241, "STMicroelectronics", self.idcode, 0xE0042000)
        self.mcu_identified.emit(info)
        return info

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def pal(self):
        return None

    def connect(self, board=None, uid: str | None = None) -> None:
        self._connected = True
        target = board.target if board is not None else "stm32f446retx"
        self.probe_connected.emit(f"ST-Link DPIDR=0x2BA01477 alvo={target}")

    def disconnect(self) -> None:
        self._connected = False
        self.probe_disconnected.emit()

    def simulate_error(self, msg: str) -> None:
        self._connected = False
        self.probe_error.emit(msg)


class FakeRunner(QObject):
    """TestRunnerService stub — executa testes sincronamente no teste."""

    test_started   = Signal(str)
    test_finished  = Signal(object)
    suite_started  = Signal(int)
    suite_finished = Signal(object)

    __test__ = False

    def __init__(self, device) -> None:
        super().__init__()
        self._running = False
        self._device  = device

    @property
    def is_running(self) -> bool:
        return self._running

    def run(self, tests=STANDARD_SUITE) -> None:
        if self._running:
            raise RuntimeError("ja em execucao")
        tests = list(tests)
        self._running = True                # antes de suite_started para que is_running=True
        self.suite_started.emit(len(tests))
        results = []
        for t in tests:
            self.test_started.emit(t.name)
            result = TestResult(
                name=t.name, status=TestStatus.PASS, message="ok (fake)"
            )
            self.test_finished.emit(result)
            results.append(result)
        self._running = False
        self.suite_finished.emit(results)

    def abort(self) -> None:
        self._running = False


def _expected_suite(win) -> list:
    """Embutidos + plano de testes do projeto ativo (mesma ordem de _run_suite)."""
    from tests_builtin.plan import build_plan
    return [*STANDARD_SUITE, *build_plan(win._active_project)]


@pytest.fixture
def device():
    return FakeDevice()


@pytest.fixture
def runner(device):
    return FakeRunner(device)


@pytest.fixture
def win(qtbot, device, runner):
    w = MainWindow(device=device, runner=runner)
    qtbot.addWidget(w)
    return w


# ===========================================================================
# Estado inicial
# ===========================================================================


class TestMainWindowInitial:
    def test_window_title_contains_version(self, win) -> None:
        from app import __version__
        assert __version__ in win.windowTitle()

    def test_connect_button_enabled(self, win) -> None:
        assert win._btn_connect.isEnabled()

    def test_connect_button_text(self, win) -> None:
        assert "Conectar" in win._btn_connect.text()

    def test_run_button_disabled_initially(self, win) -> None:
        assert not win._btn_run.isEnabled()

    def test_abort_button_disabled_initially(self, win) -> None:
        assert not win._btn_abort.isEnabled()

    def test_table_empty_initially(self, win) -> None:
        assert win._table.rowCount() == 0

    def test_table_has_correct_columns(self, win) -> None:
        assert win._table.columnCount() == 4
        headers = [
            win._table.horizontalHeaderItem(i).text()
            for i in range(4)
        ]
        assert headers == ["Status", "Teste", "ms", "Mensagem"]

    def test_suite_list_populated(self, win) -> None:
        assert win._suite_list.count() == len(STANDARD_SUITE)

    def test_progress_starts_at_zero(self, win) -> None:
        assert win._progress.value() == 0


# ===========================================================================
# Fluxo de conexao
# ===========================================================================


class TestConnectFlow:
    def test_button_text_after_connect(self, qtbot, win, device) -> None:
        with qtbot.waitSignal(device.probe_connected, timeout=1000):
            win._btn_connect.click()
        assert "Desconectar" in win._btn_connect.text()

    def test_run_enabled_after_connect(self, qtbot, win, device) -> None:
        with qtbot.waitSignal(device.probe_connected, timeout=1000):
            win._btn_connect.click()
        assert win._btn_run.isEnabled()

    def test_probe_label_updated_after_connect(self, qtbot, win, device) -> None:
        with qtbot.waitSignal(device.probe_connected, timeout=1000):
            win._btn_connect.click()
        assert "2BA01477" in win._lbl_probe.text()

    def test_button_text_after_disconnect(self, qtbot, win, device) -> None:
        with qtbot.waitSignal(device.probe_connected, timeout=1000):
            win._btn_connect.click()
        with qtbot.waitSignal(device.probe_disconnected, timeout=1000):
            win._btn_connect.click()
        assert "Conectar" in win._btn_connect.text()

    def test_run_disabled_after_disconnect(self, qtbot, win, device) -> None:
        with qtbot.waitSignal(device.probe_connected, timeout=1000):
            win._btn_connect.click()
        with qtbot.waitSignal(device.probe_disconnected, timeout=1000):
            win._btn_connect.click()
        assert not win._btn_run.isEnabled()

    def test_probe_error_shown_in_label(self, qtbot, win, device) -> None:
        with qtbot.waitSignal(device.probe_error, timeout=1000):
            device.simulate_error("USB não encontrado")
        assert "Erro" in win._lbl_probe.text() or "USB" in win._lbl_probe.text()


# ===========================================================================
# Fluxo de execucao da suite
# ===========================================================================


class TestRunFlow:
    def _connect(self, qtbot, win, device):
        with qtbot.waitSignal(device.probe_connected, timeout=1000):
            win._btn_connect.click()

    def test_table_rows_after_run(self, qtbot, win, device, runner) -> None:
        self._connect(qtbot, win, device)
        with qtbot.waitSignal(runner.suite_finished, timeout=3000):
            win._btn_run.click()
        assert win._table.rowCount() == len(_expected_suite(win))

    def test_table_status_column_after_run(self, qtbot, win, device, runner) -> None:
        self._connect(qtbot, win, device)
        with qtbot.waitSignal(runner.suite_finished, timeout=3000):
            win._btn_run.click()
        for row in range(win._table.rowCount()):
            status = win._table.item(row, 0).text()
            assert status == "PASS"

    def test_table_names_match_suite(self, qtbot, win, device, runner) -> None:
        self._connect(qtbot, win, device)
        with qtbot.waitSignal(runner.suite_finished, timeout=3000):
            win._btn_run.click()
        names = [win._table.item(row, 1).text() for row in range(win._table.rowCount())]
        assert names == [t.name for t in _expected_suite(win)]

    def test_progress_bar_full_after_run(self, qtbot, win, device, runner) -> None:
        self._connect(qtbot, win, device)
        with qtbot.waitSignal(runner.suite_finished, timeout=3000):
            win._btn_run.click()
        # Progress max = numero de testes, value = pass + fail count
        assert win._progress.maximum() == len(_expected_suite(win))

    def test_run_button_disabled_during_run(self, qtbot, win, device, runner) -> None:
        """FakeRunner e sincrono — estados intermediarios sao observaveis via suite_started."""
        self._connect(qtbot, win, device)
        observed: list[bool] = []
        runner.suite_started.connect(lambda _: observed.append(win._btn_run.isEnabled()))
        with qtbot.waitSignal(runner.suite_finished, timeout=3000):
            win._btn_run.click()
        assert not any(observed), "btn_run estava habilitado durante suite_started"

    def test_run_button_reenabled_after_run(self, qtbot, win, device, runner) -> None:
        self._connect(qtbot, win, device)
        with qtbot.waitSignal(runner.suite_finished, timeout=3000):
            win._btn_run.click()
        assert win._btn_run.isEnabled()

    def test_status_bar_shows_summary(self, qtbot, win, device, runner) -> None:
        self._connect(qtbot, win, device)
        with qtbot.waitSignal(runner.suite_finished, timeout=3000):
            win._btn_run.click()
        assert "PASS" in win._sb_suite.text()


# ===========================================================================
# Fechar janela
# ===========================================================================


class TestCloseWindow:
    def test_close_event_disconnects_probe(self, qtbot, device, runner) -> None:
        win = MainWindow(device=device, runner=runner)
        qtbot.addWidget(win)
        with qtbot.waitSignal(device.probe_connected, timeout=1000):
            device.connect()
        assert device.is_connected
        win.close()
        assert not device.is_connected


# ===========================================================================
# Novos widgets (Sprint 15)
# ===========================================================================


class TestNewWidgets:
    def test_probe_combo_exists(self, win) -> None:
        from PySide6.QtWidgets import QComboBox
        assert isinstance(win._combo_probes, QComboBox)

    def test_probe_combo_empty_initially(self, win) -> None:
        assert win._combo_probes.count() == 0

    def test_refresh_button_exists(self, win) -> None:
        assert win._btn_refresh.isEnabled()

    def test_export_button_disabled_initially(self, win) -> None:
        assert not win._btn_export.isEnabled()

    def test_export_enabled_after_run(self, qtbot, win, device, runner) -> None:
        with qtbot.waitSignal(device.probe_connected, timeout=1000):
            win._btn_connect.click()
        with qtbot.waitSignal(runner.suite_finished, timeout=3000):
            win._btn_run.click()
        assert win._btn_export.isEnabled()

    def test_plugin_list_exists(self, win) -> None:
        from PySide6.QtWidgets import QListWidget
        assert isinstance(win._plugin_list, QListWidget)

    def test_plugin_list_empty_initially(self, win) -> None:
        assert win._plugin_list.count() == 0

    def test_load_plugin_button_exists(self, win) -> None:
        assert win._btn_load_plugin.isEnabled()


# ===========================================================================
# Identificar MCU
# ===========================================================================


class TestIdentifyMcu:
    def test_identify_button_enabled_initially(self, win) -> None:
        assert win._btn_identify.isEnabled()

    def test_identify_shows_family(self, win) -> None:
        win._btn_identify.click()
        assert "STM32F446" in win._lbl_mcu.text()
        assert "Cortex-M4" in win._lbl_mcu.text()

    def test_identify_matches_project_board(self, win) -> None:
        win._btn_identify.click()
        assert "Confere" in win._lbl_mcu.text()

    def test_identify_warns_on_mismatch(self, win, device) -> None:
        device.idcode = 0x10006413   # STM32F405/407
        win._btn_identify.click()
        text = win._lbl_mcu.text()
        assert "Não confere" in text
        assert "STM32F405/F407" in text


# ===========================================================================
# Exportar PDF
# ===========================================================================


class TestExportPdf:
    def _run_suite(self, qtbot, win, device, runner) -> None:
        with qtbot.waitSignal(device.probe_connected, timeout=1000):
            win._btn_connect.click()
        with qtbot.waitSignal(runner.suite_finished, timeout=3000):
            win._btn_run.click()

    def test_disabled_without_results(self, win) -> None:
        assert not win._btn_pdf.isEnabled()

    def test_click_saves_pdf(self, qtbot, win, device, runner, tmp_path, monkeypatch) -> None:
        import app.gui.main_window as mw

        self._run_suite(qtbot, win, device, runner)
        assert win._btn_pdf.isEnabled()
        dest = tmp_path / "relatorio.pdf"
        monkeypatch.setattr(mw.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(dest), "")))
        opened: list = []
        monkeypatch.setattr(mw.QDesktopServices, "openUrl", staticmethod(opened.append))
        win._btn_pdf.click()
        assert dest.read_bytes().startswith(b"%PDF")
        assert opened and opened[0].toLocalFile().endswith("relatorio.pdf")

    def test_error_shows_message(self, qtbot, win, device, runner, tmp_path,
                                 monkeypatch) -> None:
        import app.gui.main_window as mw

        self._run_suite(qtbot, win, device, runner)
        monkeypatch.setattr(mw.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(tmp_path / "x.pdf"), "")))

        def boom(*_a, **_k):
            raise RuntimeError("disco cheio")

        monkeypatch.setattr(mw.PdfReport, "save", boom)
        warnings: list = []
        monkeypatch.setattr(mw.QMessageBox, "warning",
                            staticmethod(lambda *a: warnings.append(a[2])))
        win._btn_pdf.click()
        assert warnings and "disco cheio" in warnings[0]


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Preferências em .ini temporário — os testes não tocam o registro do Windows."""
    import app.gui.main_window as mw
    from PySide6.QtCore import QSettings

    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(mw, "_settings", lambda: QSettings(ini, QSettings.Format.IniFormat))


class TestSaveFolder:
    def test_first_time_opens_documents_then_remembers(self, win, tmp_path,
                                                       monkeypatch) -> None:
        import app.gui.main_window as mw
        from PySide6.QtCore import QStandardPaths

        asked: list[str] = []
        chosen = tmp_path / "relatorios" / "r.pdf"
        chosen.parent.mkdir()

        def fake(_parent, _title, start, _filters):
            asked.append(start)
            return str(chosen), "PDF (*.pdf)"

        monkeypatch.setattr(mw.QFileDialog, "getSaveFileName", staticmethod(fake))
        win._ask_save_path("t", "a.pdf", "PDF (*.pdf)")
        win._ask_save_path("t", "b.pdf", "PDF (*.pdf)")

        docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        assert Path(asked[0]) == Path(docs) / "a.pdf"
        assert Path(asked[1]) == chosen.parent / "b.pdf"

    def test_cancel_keeps_previous_folder(self, win, tmp_path, monkeypatch) -> None:
        import app.gui.main_window as mw

        mw._settings().setValue(mw._SETTINGS_LAST_DIR, str(tmp_path))
        monkeypatch.setattr(mw.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a: ("", "")))
        assert win._ask_save_path("t", "a.pdf", "PDF (*.pdf)") == ("", "")
        assert mw._settings().value(mw._SETTINGS_LAST_DIR) == str(tmp_path)

    def test_default_name_has_project_and_timestamp(self, win) -> None:
        import re
        assert re.fullmatch(r"relatorio_.+_\d{8}_\d{4}", win._report_default_stem())
