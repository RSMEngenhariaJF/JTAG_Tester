"""ClockInstrument — gerencia clocks de periféricos via RCC (STM32F446).

Exemplo::

    clk = ClockInstrument(pal)
    clk.enable_gpio("A")          # habilita GPIOA antes de usar seus pinos
    clk.enable_usart(2)           # habilita USART2 no APB1
    assert clk.is_gpio_enabled("C")
"""

from __future__ import annotations

from core.pal.access import PeripheralAccessLayer


# ---------------------------------------------------------------------------
# Tabelas de mapeamento  periférico → (registrador RCC, campo SVD)
# ---------------------------------------------------------------------------

_GPIO_FIELD: dict[str, str] = {
    "A": "GPIOAEN", "B": "GPIOBEN", "C": "GPIOCEN", "D": "GPIODEN",
    "E": "GPIOEEN", "F": "GPIOFEN", "G": "GPIOGEN", "H": "GPIOHEN",
}

_USART_REG_FIELD: dict[int, tuple[str, str]] = {
    1: ("APB2ENR", "USART1EN"),
    2: ("APB1ENR", "USART2EN"),
    3: ("APB1ENR", "USART3EN"),
    6: ("APB2ENR", "USART6EN"),
}

_SPI_REG_FIELD: dict[int, tuple[str, str]] = {
    1: ("APB2ENR", "SPI1EN"),
    2: ("APB1ENR", "SPI2EN"),
    3: ("APB1ENR", "SPI3EN"),
    4: ("APB2ENR", "SPI4EN"),
}

_I2C_REG_FIELD: dict[int, tuple[str, str]] = {
    1: ("APB1ENR", "I2C1EN"),
    2: ("APB1ENR", "I2C2EN"),
    3: ("APB1ENR", "I2C3EN"),
}


def _port_letter(port: str) -> str:
    """Normaliza 'A', 'PA' ou 'GPIOA' → 'A'."""
    p = port.upper().strip()
    if p.startswith("GPIO"):
        return p[4]
    if len(p) == 2 and p[0] == "P":
        return p[1]
    if len(p) == 1:
        return p[0]
    raise ValueError(f"Porta GPIO não reconhecida: '{port}'")


class ClockInstrument:
    """Habilita, desabilita e verifica clocks de periféricos via RCC."""

    def __init__(self, pal: PeripheralAccessLayer) -> None:
        self._pal = pal

    # ------------------------------------------------------------------
    # GPIO  (RCC_AHB1ENR)
    # ------------------------------------------------------------------

    def enable_gpio(self, port: str) -> None:
        """Habilita o clock de uma porta GPIO."""
        self._pal.modify_field("RCC", "AHB1ENR", _GPIO_FIELD[_port_letter(port)], 1)

    def disable_gpio(self, port: str) -> None:
        """Desabilita o clock de uma porta GPIO."""
        self._pal.modify_field("RCC", "AHB1ENR", _GPIO_FIELD[_port_letter(port)], 0)

    def is_gpio_enabled(self, port: str) -> bool:
        return bool(self._pal.read_field("RCC", "AHB1ENR", _GPIO_FIELD[_port_letter(port)]))

    # ------------------------------------------------------------------
    # USART  (APB1ENR / APB2ENR)
    # ------------------------------------------------------------------

    def enable_usart(self, n: int) -> None:
        reg, field = _USART_REG_FIELD[n]
        self._pal.modify_field("RCC", reg, field, 1)

    def disable_usart(self, n: int) -> None:
        reg, field = _USART_REG_FIELD[n]
        self._pal.modify_field("RCC", reg, field, 0)

    def is_usart_enabled(self, n: int) -> bool:
        reg, field = _USART_REG_FIELD[n]
        return bool(self._pal.read_field("RCC", reg, field))

    # ------------------------------------------------------------------
    # SPI  (APB1ENR / APB2ENR)
    # ------------------------------------------------------------------

    def enable_spi(self, n: int) -> None:
        reg, field = _SPI_REG_FIELD[n]
        self._pal.modify_field("RCC", reg, field, 1)

    def disable_spi(self, n: int) -> None:
        reg, field = _SPI_REG_FIELD[n]
        self._pal.modify_field("RCC", reg, field, 0)

    def is_spi_enabled(self, n: int) -> bool:
        reg, field = _SPI_REG_FIELD[n]
        return bool(self._pal.read_field("RCC", reg, field))

    # ------------------------------------------------------------------
    # I2C  (APB1ENR)
    # ------------------------------------------------------------------

    def enable_i2c(self, n: int) -> None:
        reg, field = _I2C_REG_FIELD[n]
        self._pal.modify_field("RCC", reg, field, 1)

    def disable_i2c(self, n: int) -> None:
        reg, field = _I2C_REG_FIELD[n]
        self._pal.modify_field("RCC", reg, field, 0)

    def is_i2c_enabled(self, n: int) -> bool:
        reg, field = _I2C_REG_FIELD[n]
        return bool(self._pal.read_field("RCC", reg, field))
