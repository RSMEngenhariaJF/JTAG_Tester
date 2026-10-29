"""Exemplo — SPI: Verifica se SPI1 foi configurado corretamente pelo firmware.

Útil para checar que o firmware inicializou SPI1 com o modo e divisor corretos.
"""

from tests_builtin.base import BuiltinTest, TestResult
from instruments.spi import SpiBaudDiv, SpiInstrument

EXPECTED_MODE     = 0              # SPI modo 0 (CPOL=0, CPHA=0)
EXPECTED_BAUD_DIV = SpiBaudDiv.DIV_256


class Spi1ConfigCheck(BuiltinTest):
    name        = "SPI1 Config Check"
    description = "Verifica modo, baud e SPE do SPI1 configurado pelo firmware."

    def _run(self, pal) -> TestResult:
        spi = SpiInstrument(1, pal)

        if not spi.is_enabled:
            return self._fail("SPI1 não está habilitado (SPE=0)")

        actual_mode = spi.mode
        actual_br   = pal.read_field("SPI1", "CR1", "BR")

        errors = []
        if actual_mode != EXPECTED_MODE:
            errors.append(f"modo={actual_mode} (esperado {EXPECTED_MODE})")
        if actual_br != int(EXPECTED_BAUD_DIV):
            errors.append(f"BR={actual_br} (esperado {int(EXPECTED_BAUD_DIV)})")

        if errors:
            return self._fail("; ".join(errors), measured=actual_mode, expected=EXPECTED_MODE)

        return self._pass(
            f"SPI1 OK: modo {actual_mode}, BR={actual_br}",
            measured=actual_mode, expected=EXPECTED_MODE,
        )
