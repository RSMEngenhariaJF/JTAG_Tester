"""Exemplo — UART: Verifica se USART2 está configurado pelo firmware.

Útil quando o firmware já inicializa a UART e você quer confirmar
que os registradores estão com os valores corretos antes de prosseguir.

Adapte: mude EXPECTED_BAUD, F_CLK, PORT.
"""

from tests_builtin.base import BuiltinTest, TestResult
from instruments.usart import UsartInstrument, _baud_divider

EXPECTED_BAUD = 115200
F_CLK         = 16_000_000   # Hz — HSI padrão; mude se usar PLL


class Usart2ConfigCheck(BuiltinTest):
    name        = "USART2 Config Check"
    description = (
        f"Verifica se USART2 está configurado para {EXPECTED_BAUD} baud "
        f"e com TX+RX habilitados."
    )

    def _run(self, pal) -> TestResult:
        u = UsartInstrument(2, pal)

        if not u.is_enabled:
            return self._fail("USART2 não está habilitado (UE=0)")

        if not u.is_tx_enabled:
            return self._fail("USART2 TX não habilitado (TE=0)")

        if not u.is_rx_enabled:
            return self._fail("USART2 RX não habilitado (RE=0)")

        # Verifica BRR
        exp_mantissa, exp_fraction = _baud_divider(EXPECTED_BAUD, F_CLK)
        got_mantissa = pal.read_field("USART2", "BRR", "DIV_Mantissa")
        got_fraction = pal.read_field("USART2", "BRR", "DIV_Fraction")

        if got_mantissa == exp_mantissa and got_fraction == exp_fraction:
            return self._pass(
                f"USART2 OK: {EXPECTED_BAUD} baud, TX+RX ativos",
                measured=(got_mantissa, got_fraction),
                expected=(exp_mantissa, exp_fraction),
            )

        return self._fail(
            f"BRR errado: mantissa={got_mantissa} fração={got_fraction} "
            f"(esperado {exp_mantissa}/{exp_fraction})",
            measured=(got_mantissa, got_fraction),
            expected=(exp_mantissa, exp_fraction),
        )
