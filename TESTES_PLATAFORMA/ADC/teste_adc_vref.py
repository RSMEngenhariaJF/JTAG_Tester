"""Exemplo — ADC: Mede tensão interna de referência (VREFINT) com ADC1.

O STM32F446 tem um canal interno VREFINT (~1.21 V) que pode ser lido
pelo ADC1 no canal 17. Útil para verificar se o ADC está funcional
sem precisar de sinal externo.

Valor típico: VREFINT = 1.21 V ± 10 mV
"""

from __future__ import annotations
import time
from tests_builtin.base import BuiltinTest, TestResult

VREFINT_EXPECTED_MV = 1210   # mV
TOLERANCE_MV        = 50     # ±50 mV


class AdcVrefIntTest(BuiltinTest):
    name        = "ADC1 VREFINT"
    description = (
        "Mede VREFINT interno (~1.21 V) no ADC1 canal 17. "
        "Sem conexão externa necessária."
    )

    def _run(self, pal) -> TestResult:
        # Habilita clock ADC1
        pal.modify_field("RCC", "APB2ENR", "ADC1EN", 1)

        # Liga ADC (ADON=1)
        pal.modify_field("ADC1", "CR2", "ADON", 1)
        time.sleep(0.001)   # tempo de estabilização

        # Habilita sensor de temperatura e VREFINT
        pal.modify_field("ADC_Common", "CCR", "TSVREFE", 1)

        # Seleciona canal 17 (VREFINT) no SQR3 (sequência regular, 1ª conversão)
        pal.modify_field("ADC1", "SQR3", "SQ1", 17)
        pal.modify_field("ADC1", "SQR1", "L",   0)   # 1 conversão

        # Inicia conversão
        pal.modify_field("ADC1", "CR2", "SWSTART", 1)

        # Aguarda EOC (end of conversion)
        deadline = time.perf_counter() + 0.1
        while not pal.read_field("ADC1", "SR", "EOC"):
            if time.perf_counter() > deadline:
                return self._fail("ADC1 EOC timeout (VREFINT)")

        raw = pal.read_field("ADC1", "DR", "DATA")

        # Converte para mV: Vmeasured = raw × 3300 mV / 4095
        vref_mv = round(raw * 3300 / 4095)

        # Desliga ADC
        pal.modify_field("ADC1", "CR2", "ADON", 0)

        delta = abs(vref_mv - VREFINT_EXPECTED_MV)
        if delta <= TOLERANCE_MV:
            return self._pass(
                f"VREFINT = {vref_mv} mV (esperado {VREFINT_EXPECTED_MV} ±{TOLERANCE_MV} mV)",
                measured=vref_mv, expected=VREFINT_EXPECTED_MV,
            )
        return self._fail(
            f"VREFINT = {vref_mv} mV (esperado {VREFINT_EXPECTED_MV} ±{TOLERANCE_MV} mV)",
            measured=vref_mv, expected=VREFINT_EXPECTED_MV,
        )
