"""Exemplo — PWM: Verifica configuração de PWM no TIM3 Canal 1 (PA6).

Confirma que o firmware configurou TIM3_CH1 com o duty-cycle e frequência corretos.

Adapte: EXPECTED_FREQ_HZ, EXPECTED_DUTY_PERCENT, F_PCLK1_HZ.
"""

from tests_builtin.base import BuiltinTest, TestResult

EXPECTED_FREQ_HZ      = 1000     # Hz
EXPECTED_DUTY_PERCENT = 50       # %
F_PCLK1_HZ            = 16_000_000
TOLERANCE_PERCENT     = 5        # tolerância de ±5 %


class Tim3Pwm1ConfigCheck(BuiltinTest):
    name        = "TIM3 PWM CH1 Config"
    description = (
        f"Verifica TIM3_CH1: {EXPECTED_FREQ_HZ} Hz, "
        f"{EXPECTED_DUTY_PERCENT}% duty cycle."
    )

    def _run(self, pal) -> TestResult:
        pal.modify_field("RCC", "APB1ENR", "TIM3EN", 1)

        psc = pal.read_reg("TIM3", "PSC") & 0xFFFF
        arr = pal.read_reg("TIM3", "ARR") & 0xFFFF
        ccr = pal.read_reg("TIM3", "CCR1") & 0xFFFF

        if arr == 0:
            return self._fail("ARR=0: TIM3 não configurado")

        actual_freq  = F_PCLK1_HZ / ((psc + 1) * (arr + 1))
        actual_duty  = (ccr / (arr + 1)) * 100

        def in_tol(val: float, exp: float) -> bool:
            return abs(val - exp) / exp * 100 <= TOLERANCE_PERCENT

        errors = []
        if not in_tol(actual_freq, EXPECTED_FREQ_HZ):
            errors.append(f"freq={actual_freq:.1f} Hz (esperado {EXPECTED_FREQ_HZ})")
        if not in_tol(actual_duty, EXPECTED_DUTY_PERCENT):
            errors.append(f"duty={actual_duty:.1f}% (esperado {EXPECTED_DUTY_PERCENT}%)")

        if errors:
            return self._fail("; ".join(errors),
                              measured=(actual_freq, actual_duty))

        return self._pass(
            f"TIM3 CH1 OK: {actual_freq:.0f} Hz, {actual_duty:.1f}%",
            measured=(actual_freq, actual_duty),
            expected=(EXPECTED_FREQ_HZ, EXPECTED_DUTY_PERCENT),
        )
