"""Testes unitários do coletor de logs (app.log_buffer) e da janela de logs.

Execução:
    pytest tests/unit/test_log_window.py -v
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import pytest

from app.log_buffer import LogBuffer, _redact


@pytest.fixture
def buf():
    b = LogBuffer(maxlen=50)
    log = logging.getLogger("teste.logwin")
    log.setLevel(logging.DEBUG)
    log.addHandler(b)
    yield b
    log.removeHandler(b)


def _log() -> logging.Logger:
    return logging.getLogger("teste.logwin")


class TestLogBuffer:
    def test_collects_levels_and_counts(self, buf) -> None:
        _log().debug("d")
        _log().info("i")
        _log().warning("w")
        _log().error("e")
        assert [e.level for e in buf.records()] == ["DEBUG", "INFO", "WARNING", "ERROR"]
        assert [e.message for e in buf.records("WARNING")] == ["w", "e"]
        assert buf.count("ERROR") == 1

    def test_exception_traceback(self, buf) -> None:
        try:
            _ = 1 / 0
        except ZeroDivisionError:
            _log().exception("falhou")
        (e,) = buf.records("ERROR")
        assert "ZeroDivisionError" in e.exception and e.module and e.line

    def test_ring_buffer_limit(self, buf) -> None:
        for i in range(80):
            _log().info("m%d", i)
        recs = buf.records()
        assert len(recs) == 50 and recs[0].message == "m30"

    def test_listeners_and_clear(self, buf) -> None:
        seen = []
        buf.add_listener(seen.append)
        _log().info("x")
        buf.clear()
        assert seen[0].message == "x" and seen[1] is None and buf.records() == []
        buf.remove_listener(seen.append)
        _log().info("y")
        assert len(seen) == 2

    def test_thread_safe_emit(self, buf) -> None:
        threads = [threading.Thread(target=lambda: [_log().info("t") for _ in range(10)])
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(buf.records()) == 40

    def test_export_jsonl(self, buf, tmp_path) -> None:
        _log().error("erro em %s", Path.home() / "projeto")
        path = buf.save(tmp_path / "logs.jsonl", context={"project": "P-1"})
        lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
        assert lines[0]["type"] == "session" and lines[0]["project"] == "P-1"
        assert lines[1]["type"] == "log" and lines[1]["level"] == "ERROR"
        assert str(Path.home()) not in lines[1]["message"]          # nome do usuário removido
        assert lines[1]["message"].startswith("erro em ~")

    def test_export_text(self, buf, tmp_path) -> None:
        _log().warning("aviso")
        text = buf.save(tmp_path / "logs.log", context={"board": "X"}).read_text(encoding="utf-8")
        assert text.startswith("# board: X") and "WARNING  | teste.logwin | aviso" in text

    def test_redact_both_slashes(self) -> None:
        home = str(Path.home())
        assert _redact(f"{home}\\a e {home.replace(chr(92), '/')}/b") == "~\\a e ~/b"


class TestInstall:
    def test_install_idempotent_and_hooks(self) -> None:
        import sys

        from app.log_buffer import get_log_buffer, install
        root = logging.getLogger()
        had = get_log_buffer() in root.handlers
        old_sys, old_thr = sys.excepthook, threading.excepthook
        try:
            install()
            install()
            assert root.handlers.count(get_log_buffer()) == 1
            before = get_log_buffer().count("CRITICAL")
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                sys.excepthook(*sys.exc_info())
            assert get_log_buffer().count("CRITICAL") == before + 1
        finally:
            sys.excepthook, threading.excepthook = old_sys, old_thr
            if not had:
                root.removeHandler(get_log_buffer())


class TestLogWindow:
    def test_filter_search_and_live_update(self, qtbot, buf) -> None:
        from app.gui.log_window import LogWindow
        _log().info("conectado ao probe")
        _log().error("falha de leitura")
        win = LogWindow(buffer=buf)
        qtbot.addWidget(win)
        assert win._table.rowCount() == 2               # filtro padrão: Info e acima
        win._level.setCurrentIndex(3)                    # Só erros
        assert win._table.rowCount() == 1
        win._level.setCurrentIndex(0)
        win._search.setText("probe")
        assert win._table.rowCount() == 1
        win._search.clear()
        _log().warning("novo aviso")
        qtbot.waitUntil(lambda: win._table.rowCount() == 3, timeout=1000)
        assert "1 erro(s)" in win._summary.text()

    def test_detail_save_and_clear(self, qtbot, buf, tmp_path, monkeypatch) -> None:
        from app.gui import log_window as lw
        try:
            raise ValueError("ruim")
        except ValueError:
            _log().exception("com traceback")
        dest = tmp_path / "s.jsonl"
        win = lw.LogWindow(buffer=buf, context_provider=lambda: {"board": "B"},
                           save_path_provider=lambda *a: (str(dest), ""))
        qtbot.addWidget(win)
        win._table.selectRow(0)
        assert "ValueError: ruim" in win._detail.toPlainText()
        win._save()
        assert json.loads(dest.read_text(encoding="utf-8").splitlines()[0])["board"] == "B"
        monkeypatch.setattr(lw.QMessageBox, "question",
                            staticmethod(lambda *a: lw.QMessageBox.StandardButton.Yes))
        win._clear()
        qtbot.waitUntil(lambda: win._table.rowCount() == 0, timeout=1000)
        assert buf.records() == []


class TestMainWindowLogs:
    def test_counter_and_failed_tests_logged(self, qtbot) -> None:
        from app.gui.main_window import MainWindow
        from app.log_buffer import get_log_buffer, install
        from tests_builtin.base import TestResult, TestStatus
        install()
        get_log_buffer().clear()
        from tests.unit.test_main_window import FakeDevice, FakeRunner
        dev = FakeDevice()
        win = MainWindow(device=dev, runner=FakeRunner(dev))
        qtbot.addWidget(win)
        win._on_test_started("X")
        win._on_test_finished(TestResult("X", TestStatus.ERROR, "deu ruim"))
        qtbot.waitUntil(lambda: "1 erro" in win._sb_logs.text(), timeout=1000)
        assert any("deu ruim" in e.message for e in get_log_buffer().records("ERROR"))
        win._open_logs()
        assert win._log_window is not None and win._log_window.isVisible()
        win._log_window.close()


class TestRedactForms:
    @pytest.mark.parametrize("raw,expected", [
        (r'File "C:\Users\RAFAEL~1\AppData\x.py"', r'File "~\AppData\x.py"'),
        ("C:/Users/fulano/a", "~/a"),
        ("/home/joao/x", "~/x"),
        ("sem caminho", "sem caminho"),
    ])
    def test_user_paths(self, raw: str, expected: str) -> None:
        assert _redact(raw) == expected
