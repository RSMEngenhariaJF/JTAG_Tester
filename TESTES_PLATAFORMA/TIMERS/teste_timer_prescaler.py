"""Exemplo — TIMERS: Verifica configuração do TIM2.

Útil para confirmar que o firmware configurou TIM2 com o prescaler
e ARR (auto-reload) corretos para gerar a frequência desejada.

Adapte EXPECTED_PSC, EXPECTED_ARR, EXPECTED_FREQ_HZ.
"""

from tests_builtin.base import BuiltinTest, TestResult

# ─── Configure aqui ───────────────────────────────────────────────────────────
EXPECTED_PSC      = 15999    # prescaler: divide PCLK1 por (PSC+1)
EXPECTED_ARR      = 999      # auto-reload: overflow a cada (ARR+1) contagens
EXPECTED_FREQ_HZ  = 1        # frequência de overflow esperada em Hz
F_PCLK1_HZ       = 16_000_000
# ──────────────────────────────────────────────────────────────────────────────


class Tim2ConfigCheck(BuiltinTest):
    name        = "TIM2 Config Check"
    description = (
        f"Verifica PSC={EXPECTED_PSC}, ARR={EXPECTED_ARR} → "
        f"{EXPECTED_FREQ_HZ} Hz no TIM2."
    )

    def _run(self, pal) -> TestResult:
        # Habilita clock TIM2 (APB1)
        pal.modify_field("RCC", "APB1ENR", "TIM2EN", 1)

        psc = pal.read_reg("TIM2", "PSC") & 0xFFFF
        arr = pal.read_reg("TIM2", "ARR") & 0xFFFF_FFFF

        # Calcula frequência de overflow
        freq = F_PCLK1_HZ / ((psc + 1) * (arr + 1))

        errors = []
        if psc != EXPECTED_PSC:
            errors.append(f"PSC={psc} (esperado {EXPECTED_PSC})")
        if arr != EXPECTED_ARR:
            errors.append(f"ARR={arr} (esperado {EXPECTED_ARR})")

        if errors:
            return self._fail("; ".join(errors), measured=(psc, arr))

        return self._pass(
            f"TIM2 OK: PSC={psc} ARR={arr} → {freq:.1f} Hz",
            measured=freq, expected=float(EXPECTED_FREQ_HZ),
        )
