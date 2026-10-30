"""Testes unitários das classes por função (osciloscópio, analisador de espectro),
rastreabilidade, descoberta VISA e seção de instrumentos nos relatórios.

Sem hardware: os modelos falam com o MockDriver, que registra cada comando.

Execução:
    pytest tests/unit/test_instrument_classes.py -v
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from core.analysis import analyze_frequency
from core.instruments.config import DriverType, InstrumentConfig
from core.instruments.oscilloscope import Waveform
from core.instruments.registry import InstrumentRegistry
from core.instruments.roles import (
    UnsupportedModelError,
    get_oscilloscope,
    get_spectrum_analyzer,
)
from core.instruments.scpi import block_total_size, parse_ieee_block, to_float
from core.instruments.traceability import (
    CalibrationExpiredError,
    CalibrationStatus,
    InstrumentIdentity,
    calibration_status,
    parse_due,
)
from instruments.discovery import discover_visa
from instruments.drivers.mock_driver import MockDriver
from instruments.models import find_model
from instruments.models.rigol_mso8000 import RigolMSO8000
from instruments.models.rs_fpc import RohdeSchwarzFPC

RIGOL_IDN = "RIGOL TECHNOLOGIES,MSO8104,MS8A000000001,00.01.03.00.02"
FPC_IDN = "Rohde&Schwarz,FPC1500,1328.6660K15/100001,V1.70"


@pytest.fixture(autouse=True)
def fresh_registry():
    InstrumentRegistry._instance = None
    yield
    InstrumentRegistry._instance = None


def _mock(name: str, **params) -> MockDriver:
    return MockDriver(InstrumentConfig(name, DriverType.MOCK, "mock://", params=params))


def _block(payload: bytes) -> bytes:
    n = str(len(payload))
    return f"#{len(n)}{n}".encode() + payload + b"\n"


# ── SCPI ──────────────────────────────────────────────────────────────────────

class TestScpi:
    def test_parse_block(self) -> None:
        assert parse_ieee_block(b"#15ABCDE\n") == b"ABCDE"
        assert parse_ieee_block(b"junk#210" + b"x" * 10) == b"x" * 10

    def test_block_total_size(self) -> None:
        assert block_total_size(b"#3010") == 5 + 10
        assert block_total_size(b"#3") is None
        assert block_total_size(b"") is None

    @pytest.mark.parametrize("bad", [b"ABC", b"#0ABC", b"#15AB"])
    def test_bad_blocks(self, bad: bytes) -> None:
        with pytest.raises(ValueError):
            parse_ieee_block(bad)

    def test_to_float_invalid_is_nan(self) -> None:
        assert to_float(" 1.5E+06\n") == 1.5e6
        assert math.isnan(to_float("9.9E37"))


# ── Rastreabilidade ───────────────────────────────────────────────────────────

class TestTraceability:
    def test_parse_idn(self) -> None:
        ident = InstrumentIdentity.parse(RIGOL_IDN)
        assert (ident.manufacturer, ident.model, ident.serial) == (
            "RIGOL TECHNOLOGIES", "MSO8104", "MS8A000000001")
        assert InstrumentIdentity.parse("0.000") is None

    def test_calibration_status(self) -> None:
        today = date(2026, 10, 29)
        assert calibration_status(None, today) == CalibrationStatus.UNKNOWN
        assert calibration_status(date(2026, 10, 1), today) == CalibrationStatus.EXPIRED
        assert calibration_status(date(2026, 11, 10), today) == CalibrationStatus.DUE_SOON
        assert calibration_status(date(2027, 6, 1), today) == CalibrationStatus.VALID
        assert parse_due("31/12/2026") is None

    def test_registry_reads_idn_without_polluting_log(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(InstrumentConfig("osc", DriverType.MOCK, "mock://", params={
            "responses": {"*IDN?": RIGOL_IDN}, "asset_id": "PAT-1",
            "calibration_due": (date.today() + timedelta(days=400)).isoformat(),
        }))
        reg.connect("osc")
        assert reg.identity("osc").model == "MSO8104"
        assert reg.get("osc").log == []
        (rec,) = reg.trace_records()
        d = rec.to_dict()
        assert d["serial"] == "MS8A000000001"
        assert d["asset_id"] == "PAT-1"
        assert d["calibration"] == "válida"

    def test_expired_blocks_only_when_asked(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(InstrumentConfig("dmm", DriverType.MOCK, "mock://", params={
            "calibration_due": "2020-01-01"}))
        reg.connect("dmm")                     # só aviso
        assert reg.calibration("dmm") == CalibrationStatus.EXPIRED
        reg.disconnect("dmm")
        reg.config("dmm").params["block_if_expired"] = True
        with pytest.raises(CalibrationExpiredError):
            reg.connect("dmm")


# ── Rigol MSO8000 ─────────────────────────────────────────────────────────────

class TestRigolMSO8000:
    def test_configuration_commands(self) -> None:
        drv = _mock("osc")
        osc = RigolMSO8000(drv)
        osc.configure_channel(2, scale_v=0.5, offset_v=-1.0, coupling="ac", probe=10)
        osc.set_timebase(1e-6)
        osc.set_edge_trigger(2, level_v=1.65, slope="falling")
        cmds = [c for c, _ in drv.log]
        assert cmds == [
            ":CHANnel2:DISPlay ON", ":CHANnel2:PROBe 10", ":CHANnel2:COUPling AC",
            ":CHANnel2:SCALe 0.5", ":CHANnel2:OFFSet -1",
            ":TIMebase:MAIN:SCALe 1e-06", ":TIMebase:MAIN:OFFSet 0",
            ":TRIGger:MODE EDGE", ":TRIGger:EDGE:SOURce CHANnel2",
            ":TRIGger:EDGE:SLOPe NEGative", ":TRIGger:EDGE:LEVel 1.65",
            ":TRIGger:SWEep SINGle",
        ]

    def test_invalid_channel_and_item(self) -> None:
        osc = RigolMSO8000(_mock("osc"))
        with pytest.raises(ValueError):
            osc.configure_channel(5, 1.0)
        with pytest.raises(ValueError):
            osc.measure("potencia", 1)

    def test_measure(self) -> None:
        drv = _mock("osc", responses={":MEASure:ITEM? FREQuency,CHANnel1": "4.0001E+06"})
        assert RigolMSO8000(drv).measure("frequency", 1) == pytest.approx(4.0001e6)
        drv.set_response(":MEASure:ITEM? VPP,CHANnel1", "9.9E37")
        assert math.isnan(RigolMSO8000(drv).measure("vpp", 1))

    def test_acquire_single_waits_for_stop(self) -> None:
        drv = _mock("osc", responses={":TRIGger:STATus?": "WAIT"})
        osc = RigolMSO8000(drv)
        with pytest.raises(TimeoutError):
            osc.acquire_single(timeout_s=0.05, poll_s=0.01)
        drv.set_response(":TRIGger:STATus?", "STOP")
        osc.acquire_single(timeout_s=0.5, poll_s=0.01)
        assert drv.log[0][0] == ":SINGle"

    def test_waveform_scaling(self) -> None:
        drv = _mock("osc", responses={
            # format,type,points,count,xinc,xorig,xref,yinc,yorig,yref
            ":WAVeform:PREamble?": "0,0,4,1,1e-9,-2e-9,0,0.1,0,128",
        })
        drv.set_raw_response(":WAVeform:DATA?", _block(bytes([128, 138, 148, 118])))
        wf = RigolMSO8000(drv).get_waveform(1)
        assert wf.volts == pytest.approx([0.0, 1.0, 2.0, -1.0])
        assert wf.dt == 1e-9 and wf.t0 == pytest.approx(-2e-9)
        assert ":WAVeform:MODE NORMal" in [c for c, _ in drv.log]

    def test_waveform_raw_reads_in_chunks(self, monkeypatch) -> None:
        import instruments.models.rigol_mso8000 as mod
        monkeypatch.setattr(mod, "RAW_CHUNK", 2)
        drv = _mock("osc", responses={":WAVeform:PREamble?": "0,2,5,1,1e-9,0,0,1,0,0"})
        drv.set_raw_response(":WAVeform:DATA?", _block(bytes([1, 2])))
        wf = RigolMSO8000(drv).get_waveform(1, raw=True)
        starts = [c for c, _ in drv.log if c.startswith(":WAVeform:STARt")]
        assert starts == [":WAVeform:STARt 1", ":WAVeform:STARt 3", ":WAVeform:STARt 5"]
        assert len(wf) == 6        # 3 blocos de 2 bytes do mock


# ── Waveform → analisadores ───────────────────────────────────────────────────

class TestWaveform:
    def test_edges_feed_analyze_frequency(self) -> None:
        # Onda quadrada de 1 MHz amostrada a 100 MS/s (dt = 10 ns)
        volts = [3.3 if (i // 50) % 2 else 0.0 for i in range(1000)]
        wf = Waveform(volts=volts, dt=10e-9)
        rising = wf.edges(1.65)
        assert len(rising) == 10
        m = analyze_frequency("f", rising, 1e6, tolerance_pct=0.1)
        assert m.value == pytest.approx(1e6)
        assert m.within_limits
        assert len(wf.edges(1.65, "either")) == 19


# ── R&S FPC (conceitual) ──────────────────────────────────────────────────────

class TestRohdeSchwarzFPC:
    def test_trace_and_peak(self) -> None:
        drv = _mock("sa", responses={
            "TRAC? TRACE1": "-80.0,-20.5,-75.0", "FREQ:STAR?": "1E6", "FREQ:STOP?": "3E6",
            "CALC:MARK1:X?": "2E6", "CALC:MARK1:Y?": "-20.5",
        })
        sa = RohdeSchwarzFPC(drv)
        sa.set_center_span(2e6, 2e6)
        sa.set_rbw(10e3, vbw_hz=30e3)
        sa.single_sweep(timeout_s=1)
        tr = sa.get_trace()
        assert tr.freqs_hz == [1e6, 2e6, 3e6]
        assert tr.peak() == (2e6, -20.5)
        assert tr.level_at(2.9e6) == -75.0
        assert sa.peak() == (2e6, -20.5)
        cmds = [c for c, _ in drv.log]
        assert cmds[:4] == ["FREQ:CENT 2e+06", "FREQ:SPAN 2e+06", "BAND 10000", "BAND:VID 30000"]
        assert "INIT;*OPC?" in cmds

    def test_start_stop_validation(self) -> None:
        with pytest.raises(ValueError):
            RohdeSchwarzFPC(_mock("sa")).set_start_stop(2e6, 1e6)


# ── Seleção de modelo por função ──────────────────────────────────────────────

class TestRoles:
    def _connect(self, name: str, idn: str, **params) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(InstrumentConfig(name, DriverType.MOCK, "mock://", params={
            "responses": {"*IDN?": idn}, **params}))
        reg.connect(name)

    def test_by_idn(self) -> None:
        self._connect("osc", RIGOL_IDN)
        self._connect("sa", FPC_IDN)
        assert isinstance(get_oscilloscope("osc"), RigolMSO8000)
        assert isinstance(get_spectrum_analyzer("sa"), RohdeSchwarzFPC)
        assert get_oscilloscope("osc").identity.serial == "MS8A000000001"

    def test_not_connected_returns_none(self) -> None:
        assert get_oscilloscope("osc") is None

    def test_wrong_kind_raises(self) -> None:
        self._connect("sa", FPC_IDN)
        with pytest.raises(UnsupportedModelError):
            get_oscilloscope("sa")

    def test_model_override(self) -> None:
        self._connect("osc", "ACME,X1,1,1", model="rigol_mso8000")
        assert isinstance(get_oscilloscope("osc"), RigolMSO8000)

    def test_other_rigol_models_not_matched(self) -> None:
        assert find_model("oscilloscope", InstrumentIdentity.parse("RIGOL,DS1054Z,1,1")) is None


# ── Descoberta VISA ───────────────────────────────────────────────────────────

class _FakeInst:
    def __init__(self, idn: str | Exception) -> None:
        self._idn = idn
        self.timeout = 0

    def query(self, _cmd: str) -> str:
        if isinstance(self._idn, Exception):
            raise self._idn
        return self._idn + "\n"

    def close(self) -> None:
        pass


class _FakeRM:
    def __init__(self, table: dict) -> None:
        self.table = table
        self.opened: list[str] = []

    def list_resources(self):
        return tuple(self.table)

    def open_resource(self, res: str):
        self.opened.append(res)
        return _FakeInst(self.table[res])


class TestDiscovery:
    def test_dedup_skip_serial_and_errors(self) -> None:
        rm = _FakeRM({
            "ASRL6::INSTR": "não deveria ser aberto",
            "TCPIP::10.0.0.5::INSTR": RIGOL_IDN,
            "TCPIP::10.0.0.5::hislip0::INSTR": RIGOL_IDN,
            "TCPIP::10.0.0.9::INSTR": TimeoutError("timeout"),
        })
        found = discover_visa(rm)
        assert [d.resource for d in found] == ["TCPIP::10.0.0.5::INSTR", "TCPIP::10.0.0.9::INSTR"]
        assert "ASRL6::INSTR" not in rm.opened
        assert found[0].suggested_name() == "osc"
        assert found[1].identity is None and "timeout" in found[1].error

    def test_unknown_model_name(self) -> None:
        found = discover_visa(_FakeRM({"TCPIP::1::INSTR": "Keysight Technologies,E5080B,MY1,A"}))
        assert found[0].suggested_name() == "e5080b"


# ── Relatórios ────────────────────────────────────────────────────────────────

_TRACE = [{
    "name": "osc", "address": "TCPIP::10.0.0.5::INSTR", "manufacturer": "RIGOL TECHNOLOGIES",
    "model": "MSO8104", "serial": "MS8A000000001", "firmware": "00.01", "asset_id": "PAT-1",
    "calibration_due": "2027-06-01", "calibration": "válida",
}]


def _results():
    from tests_builtin.base import TestResult, TestStatus
    return [TestResult("Osc MCO1", TestStatus.PASS, "ok")]


class TestReports:
    def test_html_has_instruments_section(self) -> None:
        from core.analysis.report import HtmlReport
        html = HtmlReport(instruments=_TRACE).generate(_results())
        assert "Instrumentos utilizados" in html
        assert "MS8A000000001" in html and "2027-06-01 (válida)" in html
        assert "Instrumentos utilizados" not in HtmlReport().generate(_results())

    def test_pdf_html_has_instruments_section(self) -> None:
        from core.analysis.report_pdf import PdfReport
        assert "MS8A000000001" in PdfReport(instruments=_TRACE).build_html(_results())

    def test_docx_has_instruments_table(self) -> None:
        pytest.importorskip("docx")
        from core.analysis.report_docx import DocxReport
        doc = DocxReport(instruments=_TRACE).generate(_results())
        cells = [c.text for t in doc.tables for row in t.rows for c in row.cells]
        assert "MS8A000000001" in cells and "PAT-1" in cells


class TestPdfBackends:
    def test_qt_backend_writes_pdf(self, tmp_path, qapp) -> None:
        from core.analysis.report_pdf import PdfReport
        out = PdfReport(instruments=_TRACE).save(tmp_path / "r.pdf", _results(), backend="qt")
        data = out.read_bytes()
        assert data.startswith(b"%PDF") and len(data) > 1000

    def test_invalid_backend(self, tmp_path) -> None:
        from core.analysis.report_pdf import PdfReport
        with pytest.raises(ValueError):
            PdfReport().save(tmp_path / "r.pdf", _results(), backend="word")
