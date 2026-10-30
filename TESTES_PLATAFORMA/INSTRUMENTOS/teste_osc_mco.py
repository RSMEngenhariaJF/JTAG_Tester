"""Exemplo — INSTRUMENTOS: frequência do MCO1 medida no osciloscópio.

O MCU coloca o HSI (16 MHz) / 4 no pino PA8 (MCO1, NUCLEO-F446RE) e o
osciloscópio cadastrado como "osc" mede a frequência por dois caminhos:
  1. bordas da forma de onda → analyze_frequency (mesmo critério de outros testes)
  2. medida automática do próprio osciloscópio (conferência cruzada)

Ligação: ponta do canal 1 em PA8 (CN10-23 na NUCLEO-F446RE), terra no GND.
Sem osciloscópio conectado, o teste é pulado (SKIP), não reprovado.
"""

from core.analysis import MeasurementSet, analyze_frequency
from core.instruments.roles import get_oscilloscope
from tests_builtin.base import BuiltinTest, TestResult

CANAL       = 1
ESPERADO_HZ = 16_000_000 / 4     # HSI / 4
TOLERANCIA  = 2.0                # % — HSI tem ±1% de fábrica (conferir no datasheet)
NIVEL_V     = 1.65               # metade de 3,3 V


class OscMcoFrequencyTest(BuiltinTest):
    name        = "Osc MCO1"
    description = "Mede no osciloscópio a frequência do HSI/4 em PA8 (MCO1)."

    def _run(self, pal) -> TestResult:
        osc = get_oscilloscope("osc")
        if osc is None:
            return self._skip("Osciloscópio 'osc' não conectado (aba Instrumentos)")

        # Salva o estado para restaurar no finally
        saved = {
            "MCO1":    pal.read_field("RCC", "CFGR", "MCO1"),
            "MCO1PRE": pal.read_field("RCC", "CFGR", "MCO1PRE"),
            "MODER8":  pal.read_field("GPIOA", "MODER", "MODER8"),
            "AFRH8":   pal.read_field("GPIOA", "AFRH", "AFRH8"),
        }
        try:
            pal.modify_field("RCC", "AHB1ENR", "GPIOAEN", 1)
            pal.modify_field("RCC", "CFGR", "MCO1", 0b00)       # fonte = HSI
            pal.modify_field("RCC", "CFGR", "MCO1PRE", 0b110)   # divide por 4
            pal.modify_field("GPIOA", "AFRH", "AFRH8", 0)       # AF0 = MCO1
            pal.modify_field("GPIOA", "MODER", "MODER8", 0b10)  # alternate function

            osc.configure_channel(CANAL, scale_v=1.0, offset_v=-1.65)
            osc.set_timebase(100e-9)                            # ~10 períodos na tela
            osc.set_edge_trigger(CANAL, level_v=NIVEL_V)
            osc.acquire_single(timeout_s=3)

            wf = osc.get_waveform(CANAL)
            ms = MeasurementSet()
            ms.add(analyze_frequency("mco1_freq", wf.edges(NIVEL_V), ESPERADO_HZ,
                                     tolerance_pct=TOLERANCIA))
            f_auto = osc.measure("frequency", CANAL)
        finally:
            pal.modify_field("GPIOA", "MODER", "MODER8", saved["MODER8"])
            pal.modify_field("GPIOA", "AFRH", "AFRH8", saved["AFRH8"])
            pal.modify_field("RCC", "CFGR", "MCO1PRE", saved["MCO1PRE"])
            pal.modify_field("RCC", "CFGR", "MCO1", saved["MCO1"])

        m = ms.get("mco1_freq")
        msg = f"{m.value / 1e6:.4f} MHz pelas bordas, {f_auto / 1e6:.4f} MHz pelo osciloscópio"
        if ms.all_within_limits():
            return self._pass(msg, measured=m.value, expected=ESPERADO_HZ, measurements=ms)
        return self._fail(msg, measured=m.value, expected=ESPERADO_HZ, measurements=ms)
