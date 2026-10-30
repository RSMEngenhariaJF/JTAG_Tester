"""Rigol MSO8000 (MSO8064/8104/8204) — osciloscópio via SCPI.

Comandos segundo o MSO8000 Programming Guide (Rigol). Ainda não validado em
bancada: conferir com o manual da versão de firmware antes de usar como
critério de aprovação.

Forma de onda (:WAVeform:PREamble?):
    format, type, points, count, xincrement, xorigin, xreference,
    yincrement, yorigin, yreference
    tensão[i] = (byte[i] - yorigin - yreference) * yincrement
    tempo[i]  = (i - xreference) * xincrement + xorigin
"""

from __future__ import annotations

from core.instruments.oscilloscope import Oscilloscope, Waveform
from core.instruments.scpi import parse_ieee_block, to_float

_ITEMS: dict[str, str] = {
    "frequency": "FREQuency", "period": "PERiod", "vpp": "VPP", "vmax": "VMAX",
    "vmin": "VMIN", "vavg": "VAVG", "vrms": "VRMS", "amplitude": "VAMP",
    "rise_time": "RTIMe", "fall_time": "FTIMe", "pos_width": "PWIDth",
    "neg_width": "NWIDth", "duty": "PDUTy", "overshoot": "OVERshoot",
}
_SLOPES = {"rising": "POSitive", "falling": "NEGative", "either": "RFALl"}
_SWEEPS = {"single": "SINGle", "normal": "NORMal", "auto": "AUTO"}
_COUPLINGS = {"DC", "AC", "GND"}
RAW_CHUNK: int = 250_000     # pontos por leitura em modo RAW (BYTE)


class RigolMSO8000(Oscilloscope):
    channels = 4

    def configure_channel(self, ch, scale_v, offset_v=0.0, *, coupling="DC", probe=1.0,
                          enabled=True):
        self._check_channel(ch)
        if coupling.upper() not in _COUPLINGS:
            raise ValueError(f"Acoplamento inválido: {coupling}")
        c = f":CHANnel{ch}"
        self._d.write(f"{c}:DISPlay {'ON' if enabled else 'OFF'}")
        self._d.write(f"{c}:PROBe {probe:g}")
        self._d.write(f"{c}:COUPling {coupling.upper()}")
        self._d.write(f"{c}:SCALe {scale_v:g}")
        self._d.write(f"{c}:OFFSet {offset_v:g}")

    def set_timebase(self, scale_s, offset_s=0.0):
        self._d.write(f":TIMebase:MAIN:SCALe {scale_s:g}")
        self._d.write(f":TIMebase:MAIN:OFFSet {offset_s:g}")

    def set_edge_trigger(self, source_ch, level_v, slope="rising", sweep="single"):
        self._check_channel(source_ch)
        self._d.write(":TRIGger:MODE EDGE")
        self._d.write(f":TRIGger:EDGE:SOURce CHANnel{source_ch}")
        self._d.write(f":TRIGger:EDGE:SLOPe {_SLOPES[slope]}")
        self._d.write(f":TRIGger:EDGE:LEVel {level_v:g}")
        self._d.write(f":TRIGger:SWEep {_SWEEPS[sweep]}")

    def run(self):
        self._d.write(":RUN")

    def stop(self):
        self._d.write(":STOP")

    def single(self):
        self._d.write(":SINGle")

    def force_trigger(self):
        self._d.write(":TFORce")

    def is_stopped(self):
        return self._d.query(":TRIGger:STATus?").strip().upper() == "STOP"

    def measure(self, item, ch):
        self._check_channel(ch)
        if item not in _ITEMS:
            raise ValueError(f"Medida '{item}' não suportada: {sorted(_ITEMS)}")
        return to_float(self._d.query(f":MEASure:ITEM? {_ITEMS[item]},CHANnel{ch}"))

    def get_waveform(self, ch, *, raw=False):
        self._check_channel(ch)
        self._d.write(f":WAVeform:SOURce CHANnel{ch}")
        self._d.write(f":WAVeform:MODE {'RAW' if raw else 'NORMal'}")
        self._d.write(":WAVeform:FORMat BYTE")
        pre = [float(x) for x in self._d.query(":WAVeform:PREamble?").split(",")]
        points = int(pre[2])
        xinc, xorg, xref, yinc, yorg, yref = pre[4:10]

        if not raw:
            data = parse_ieee_block(self._d.query_raw(":WAVeform:DATA?"))
        else:
            data = b""
            for start in range(1, points + 1, RAW_CHUNK):
                self._d.write(f":WAVeform:STARt {start}")
                self._d.write(f":WAVeform:STOP {min(start + RAW_CHUNK - 1, points)}")
                data += parse_ieee_block(self._d.query_raw(":WAVeform:DATA?", timeout_ms=30_000))

        volts = [(b - yorg - yref) * yinc for b in data]
        return Waveform(volts=volts, dt=xinc, t0=xorg - xref * xinc, source=f"CH{ch}",
                        meta={"points_declared": points, "mode": "RAW" if raw else "NORMal"})
