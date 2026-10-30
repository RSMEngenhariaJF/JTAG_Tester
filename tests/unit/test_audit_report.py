"""Registro de auditoria: captura na execução (tests_builtin/audit.py, base.run) e
seções "Ambiente da execução" / "Registro de execução por teste" nos três relatórios.

Execução:
    pytest tests/unit/test_audit_report.py -v
"""

from __future__ import annotations

import logging

import pytest

from tests_builtin.base import BuiltinTest, TestResult, TestStatus


class _Logs(BuiltinTest):
    name = "Com log"
    description = "Teste que registra log e às vezes explode"

    def __init__(self, boom: bool = False) -> None:
        self.boom = boom

    def _run(self, pal):
        logging.getLogger("hal.teste").info("configurei o periférico X")
        if self.boom:
            raise RuntimeError("deu ruim no meio")
        return self._pass("ok")


class TestCapture:
    def test_identity_log_and_start(self) -> None:
        r = _Logs().run(None)
        d = r.details
        assert d["teste"]["classe"].endswith("_Logs")
        assert d["teste"]["arquivo"] == "tests/unit/test_audit_report.py"
        assert len(d["teste"]["sha256"]) == 16
        assert any("configurei o periférico X" in line for line in d["log"])
        assert r.started_at and "T" in r.started_at
        assert r.to_dict()["details"]["descricao"].startswith("Teste que registra")

    def test_exception_traceback(self) -> None:
        r = _Logs(boom=True).run(None)
        assert r.status == TestStatus.ERROR
        assert "RuntimeError: deu ruim no meio" in r.details["excecao"]
        assert "Traceback" in r.details["excecao"]

    def test_log_from_other_threads_is_not_captured(self) -> None:
        import threading

        from tests_builtin.audit import LogCapture
        cap = LogCapture()
        cap.start()
        t = threading.Thread(target=lambda: logging.getLogger("x").warning("outra thread"))
        t.start()
        t.join()
        logging.getLogger("x").warning("desta thread")
        cap.stop()
        assert any("desta thread" in line for line in cap.lines)
        assert not any("outra thread" in line for line in cap.lines)

    def test_composed_test_records_steps_and_decisions(self) -> None:
        from testbench import ComposedTest, Driver, Monitor, Testbench
        from testbench.decision import FollowsDrive
        from testbench.stimulus import Levels

        wire = {"v": 0}

        class D(Driver):
            name = "d"

            def apply(self, pal, value):
                wire["v"] = value

        class M(Monitor):
            name = "m"

            def sample(self, pal):
                return wire["v"]

        class T(ComposedTest):
            name = "T"

            def build(self):
                return Testbench([D()], [M()], Levels("d", [1, 0], wait_s=0),
                                 [FollowsDrive("m", "d", label="x")])

        r = T().run(None)
        assert [p[1] for p in r.details["passos"]] == ["d=1", "d=0"]
        assert r.details["passos"][0][3:] == ["d: 1", "m: 1"]
        assert r.details["decisoes"] == [["PASS", "x: 2 amostras acompanharam"]]

    def test_repetitions_table_and_logs(self) -> None:
        from tests_builtin.repeat import RepeatedTest
        r = RepeatedTest(_Logs(), 3).run(None)
        reps = r.details["repeticoes"]
        assert [row[0] for row in reps] == ["1", "2", "3"] and all(row[1] == "PASS" for row in reps)
        assert sum("configurei" in line for line in r.details["log"]) == 3
        assert r.details["log"][0].startswith("[repetição 1]")


class TestReports:
    @pytest.fixture
    def results(self):
        ok = _Logs().run(None)
        ok.params = {"Pinos": "led, rele", "Ciclos": "2"}
        err = _Logs(boom=True).run(None)
        return [ok, err]

    ENV = {"software": "JTAG Tester v9", "sonda": "ST-Link DPIDR=0x6BA02477",
           "projeto_sha256": "abc123", "extra_campo": "x"}

    def _check(self, text: str) -> None:
        for expected in ("Ambiente da execução", "JTAG Tester v9", "ST-Link DPIDR=0x6BA02477",
                         "abc123", "extra_campo", "Registro de execução por teste",
                         "Identificação", "SHA-256 do código", "Parâmetros aplicados",
                         "led, rele", "Log durante o teste", "configurei o periférico X",
                         "Exceção (rastreamento)", "deu ruim no meio"):
            assert expected in text, expected

    def test_html(self, results) -> None:
        from core.analysis.report import HtmlReport
        self._check(HtmlReport(environment=self.ENV).generate(results))

    def test_pdf_html(self, results) -> None:
        from core.analysis.report_pdf import PdfReport
        self._check(PdfReport(environment=self.ENV).build_html(results))

    def test_docx(self, results) -> None:
        pytest.importorskip("docx")
        from core.analysis.report_docx import DocxReport
        doc = DocxReport(environment=self.ENV).generate(results)
        text = "\n".join(p.text for p in doc.paragraphs)
        text += "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
        self._check(text)

    def test_results_without_details_still_render(self) -> None:
        from core.analysis.report import HtmlReport
        html = HtmlReport().generate([TestResult("X", TestStatus.PASS, "ok")])
        assert "Registro de execução por teste" not in html and "Ambiente da execução" not in html
