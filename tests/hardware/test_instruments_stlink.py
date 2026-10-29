"""Testes de hardware: GpioInstrument e ClockInstrument via ST-Link.

Execução:
    pytest tests/hardware/test_instruments_stlink.py -m hardware --stlink -v -s
"""

from __future__ import annotations

import pytest

from instruments.gpio import GpioInstrument, GpioMode, GpioPull, GpioSpeed
from instruments.clock import ClockInstrument


@pytest.fixture(scope="module")
def gpio_a(pal_stlink):
    return GpioInstrument("A", pal_stlink)


@pytest.fixture(scope="module")
def gpio_c(pal_stlink):
    return GpioInstrument("C", pal_stlink)


@pytest.fixture(scope="module")
def clk(pal_stlink):
    return ClockInstrument(pal_stlink)


# ===========================================================================
# ClockInstrument — verifica clocks do firmware padrão da NUCLEO
# ===========================================================================


@pytest.mark.hardware
class TestClocksHardware:
    def test_gpioa_clock_enabled(self, clk) -> None:
        """GPIOA deve estar com clock habilitado (LED usa PA5)."""
        assert clk.is_gpio_enabled("A")

    def test_gpioc_clock_enabled(self, clk) -> None:
        """GPIOC deve estar habilitado (botão USER em PC13)."""
        assert clk.is_gpio_enabled("C")

    def test_enable_gpiob_clock(self, clk) -> None:
        """Habilita clock do GPIOB e verifica (operação segura — apenas liga clock)."""
        clk.enable_gpio("B")
        assert clk.is_gpio_enabled("B")

    def test_usart2_status_readable(self, clk) -> None:
        """USART2 clock deve ser legível (pode estar on ou off)."""
        state = clk.is_usart_enabled(2)
        assert isinstance(state, bool)
        print(f"\n  USART2EN = {state}")

    def test_enable_usart2(self, clk) -> None:
        clk.enable_usart(2)
        assert clk.is_usart_enabled(2)

    def test_spi1_status_readable(self, clk) -> None:
        state = clk.is_spi_enabled(1)
        assert isinstance(state, bool)
        print(f"\n  SPI1EN = {state}")


# ===========================================================================
# GpioInstrument — leitura de pinos reais
# ===========================================================================


@pytest.mark.hardware
class TestGpioReadHardware:
    def test_read_port_a(self, gpio_a) -> None:
        idr = gpio_a.read_port()
        assert 0 <= idr <= 0xFFFF
        print(f"\n  GPIOA->IDR = 0x{idr:04X}")

    def test_pa5_mode_is_output(self, gpio_a) -> None:
        """PA5 = LD2, configurado como saída pelo firmware padrão."""
        assert gpio_a.pin(5).mode == GpioMode.OUTPUT

    def test_pc13_mode_is_input(self, gpio_c) -> None:
        """PC13 = botão USER, configurado como entrada."""
        assert gpio_c.pin(13).mode == GpioMode.INPUT

    def test_pc13_read(self, gpio_c) -> None:
        """Botão USER não pressionado → PC13 = HIGH (pull-up interno)."""
        val = gpio_c.pin(13).read()
        assert isinstance(val, bool)
        print(f"\n  PC13 (botão USER) = {'HIGH (solto)' if val else 'LOW (pressionado)'}")


# ===========================================================================
# GpioInstrument — controle do LED (PA5)
# ===========================================================================


@pytest.mark.hardware
class TestLedControlHardware:
    def test_led_set_via_instrument(self, gpio_a) -> None:
        """Liga LED via GpioPin.set() e confirma via read_port()."""
        gpio_a.pin(5).set()
        idr_or_odr = gpio_a.read_port()
        # Confirma pelo ODR (CPU halted, IDR reflete o driver)
        odr = gpio_a._pal.read_field("GPIOA", "ODR", "ODR5")
        assert odr == 1

    def test_led_reset_via_instrument(self, gpio_a) -> None:
        """Desliga LED e confirma."""
        gpio_a.pin(5).reset()
        odr = gpio_a._pal.read_field("GPIOA", "ODR", "ODR5")
        assert odr == 0

    def test_led_toggle_via_instrument(self, gpio_a) -> None:
        """Toggle completo com restauração."""
        before = gpio_a._pal.read_field("GPIOA", "ODR", "ODR5")
        gpio_a.pin(5).toggle()
        after = gpio_a._pal.read_field("GPIOA", "ODR", "ODR5")
        assert after != before
        # Restaura
        gpio_a.pin(5).toggle()
        restored = gpio_a._pal.read_field("GPIOA", "ODR", "ODR5")
        assert restored == before


# ===========================================================================
# GpioInstrument — configure e restore (PA5)
# ===========================================================================


@pytest.mark.hardware
class TestGpioConfigureHardware:
    def test_configure_output_high_speed_and_restore(self, gpio_a) -> None:
        """Altera OSPEEDR5 temporariamente e restaura."""
        original_speed = gpio_a._pal.read_field("GPIOA", "OSPEEDR", "OSPEEDR5")
        try:
            gpio_a.pin(5).configure_output(speed=GpioSpeed.VERY_HIGH)
            readback = gpio_a._pal.read_field("GPIOA", "OSPEEDR", "OSPEEDR5")
            assert readback == int(GpioSpeed.VERY_HIGH)
        finally:
            gpio_a._pal.modify_field("GPIOA", "OSPEEDR", "OSPEEDR5", original_speed)

    def test_configure_input_pull_up_and_restore(self, gpio_a) -> None:
        """Reconfigura PA5 como input com pull-up, lê, restaura como output."""
        original_moder = gpio_a._pal.read_field("GPIOA", "MODER", "MODER5")
        original_pupdr = gpio_a._pal.read_field("GPIOA", "PUPDR", "PUPDR5")
        try:
            gpio_a.pin(5).configure_input(pull=GpioPull.PULL_UP)
            assert gpio_a.pin(5).mode == GpioMode.INPUT
            assert gpio_a.pin(5).pull == GpioPull.PULL_UP
        finally:
            gpio_a._pal.modify_field("GPIOA", "MODER", "MODER5", original_moder)
            gpio_a._pal.modify_field("GPIOA", "PUPDR", "PUPDR5", original_pupdr)
        # Verifica restauração
        assert gpio_a.pin(5).mode == GpioMode.OUTPUT
