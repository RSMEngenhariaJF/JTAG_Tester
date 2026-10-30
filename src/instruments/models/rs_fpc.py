"""Rohde & Schwarz FPC1000/FPC1500 — analisador de espectro via SCPI.

CONCEITUAL: escrito a partir da sintaxe SCPI de controle remoto da família FPC,
sem acesso ao equipamento. Validar cada comando com o manual do usuário (seção
"Remote Control") e com o aparelho antes de qualquer uso em teste.
"""

from __future__ import annotations

from core.instruments.scpi import to_float
from core.instruments.spectrum import Spectrum, SpectrumAnalyzer, linspace


class RohdeSchwarzFPC(SpectrumAnalyzer):
    def set_center_span(self, center_hz, span_hz):
        self._d.write(f"FREQ:CENT {center_hz:g}")
        self._d.write(f"FREQ:SPAN {span_hz:g}")

    def set_start_stop(self, start_hz, stop_hz):
        if stop_hz <= start_hz:
            raise ValueError("stop_hz deve ser maior que start_hz")
        self._d.write(f"FREQ:STAR {start_hz:g}")
        self._d.write(f"FREQ:STOP {stop_hz:g}")

    def set_rbw(self, rbw_hz, vbw_hz=None):
        self._d.write(f"BAND {rbw_hz:g}")
        if vbw_hz is not None:
            self._d.write(f"BAND:VID {vbw_hz:g}")

    def set_ref_level(self, dbm):
        self._d.write(f"DISP:TRAC:Y:RLEV {dbm:g}")

    def single_sweep(self, timeout_s=10.0):
        self._d.write("INIT:CONT OFF")
        self._d.query("INIT;*OPC?", timeout_ms=int(timeout_s * 1000))

    def get_trace(self, trace=1):
        self._d.write("FORM ASC")
        levels = [float(x) for x in self._d.query(f"TRAC? TRACE{trace}").split(",") if x.strip()]
        start = float(self._d.query("FREQ:STAR?"))
        stop = float(self._d.query("FREQ:STOP?"))
        return Spectrum(freqs_hz=linspace(start, stop, len(levels)), levels_dbm=levels)

    def peak(self):
        self._d.write("CALC:MARK1 ON")
        self._d.write("CALC:MARK1:MAX")
        return to_float(self._d.query("CALC:MARK1:X?")), to_float(self._d.query("CALC:MARK1:Y?"))
