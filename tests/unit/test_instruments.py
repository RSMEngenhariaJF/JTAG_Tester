"""Testes unitários de GpioInstrument e ClockInstrument.

Usa FakeMemory (dict) + SVD real do STM32F446. Sem hardware.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.pal.access import PeripheralAccessLayer
from core.svd.parser import parse
from instruments.gpio import (
    GpioInstrument,
    GpioMode,
    GpioPin,
    GpioPull,
    GpioSpeed,
)
from instruments.clock import ClockInstrument

_SVD = Path(__file__).parents[2] / "devices" / "stm32f446" / "STM32F446.svd"


# ---------------------------------------------------------------------------
# Infra de teste
# ---------------------------------------------------------------------------


class FakeMemory:
    def __init__(self, initial: dict[int, int] | None = None) -> None:
        self._mem: dict[int, int] = dict(initial or {})
        self.reads: list[int] = []
        self.writes: list[tuple[int, int]] = []

    def read_mem32(self, addr: int) -> int:
        self.reads.append(addr)
        return self._mem.get(addr, 0)

    def write_mem32(self, addr: int, value: int) -> None:
        self.writes.append((addr, value))
        self._mem[addr] = value & 0xFFFFFFFF

    def peek(self, addr: int) -> int:
        return self._mem.get(addr, 0)


@pytest.fixture(scope="module")
def svd():
    return parse(_SVD)


@pytest.fixture
def mem():
    return FakeMemory()


@pytest.fixture
def pal(mem, svd):
    return PeripheralAccessLayer(mem, svd)


@pytest.fixture
def gpio_a(pal):
    return GpioInstrument("A", pal)


@pytest.fixture
def clk(pal):
    return ClockInstrument(pal)


# ===========================================================================
# GpioPin — criação e validação
# ===========================================================================


class TestGpioPinCreation:
    def test_valid_pin(self, pal) -> None:
        p = GpioPin("GPIOA", 5, pal)
        assert p.pin == 5
        assert p.periph == "GPIOA"

    def test_pin_zero(self, pal) -> None:
        GpioPin("GPIOA", 0, pal)

    def test_pin_fifteen(self, pal) -> None:
        GpioPin("GPIOA", 15, pal)

    def test_pin_negative_raises(self, pal) -> None:
        with pytest.raises(ValueError):
            GpioPin("GPIOA", -1, pal)

    def test_pin_sixteen_raises(self, pal) -> None:
        with pytest.raises(ValueError):
            GpioPin("GPIOA", 16, pal)


# ===========================================================================
# GpioPin — configure()
# ===========================================================================


class TestGpioPinConfigure:
    def test_configure_output_sets_moder(self, pal, mem, svd) -> None:
        p = GpioPin("GPIOA", 5, pal)
        p.configure_output()
        addr = svd.peripheral("GPIOA").address_of("MODER")
        moder5 = (mem.peek(addr) >> 10) & 0b11
        assert moder5 == 0b01  # GpioMode.OUTPUT

    def test_configure_input_sets_moder(self, pal, mem, svd) -> None:
        p = GpioPin("GPIOA", 5, pal)
        p.configure_input()
        addr = svd.peripheral("GPIOA").address_of("MODER")
        assert (mem.peek(addr) >> 10) & 0b11 == 0b00

    def test_configure_pull_up(self, pal, mem, svd) -> None:
        p = GpioPin("GPIOA", 3, pal)
        p.configure_input(pull=GpioPull.PULL_UP)
        addr = svd.peripheral("GPIOA").address_of("PUPDR")
        assert (mem.peek(addr) >> 6) & 0b11 == 0b01

    def test_configure_pull_down(self, pal, mem, svd) -> None:
        p = GpioPin("GPIOA", 3, pal)
        p.configure_input(pull=GpioPull.PULL_DOWN)
        addr = svd.peripheral("GPIOA").address_of("PUPDR")
        assert (mem.peek(addr) >> 6) & 0b11 == 0b10

    def test_configure_speed_high(self, pal, mem, svd) -> None:
        p = GpioPin("GPIOA", 5, pal)
        p.configure_output(speed=GpioSpeed.HIGH)
        addr = svd.peripheral("GPIOA").address_of("OSPEEDR")
        assert (mem.peek(addr) >> 10) & 0b11 == int(GpioSpeed.HIGH)

    def test_configure_open_drain(self, pal, mem, svd) -> None:
        p = GpioPin("GPIOA", 5, pal)
        p.configure_output(open_drain=True)
        addr = svd.peripheral("GPIOA").address_of("OTYPER")
        assert (mem.peek(addr) >> 5) & 1 == 1

    def test_configure_push_pull_default(self, pal, mem, svd) -> None:
        p = GpioPin("GPIOA", 5, pal)
        p.configure_output(open_drain=False)
        addr = svd.peripheral("GPIOA").address_of("OTYPER")
        assert (mem.peek(addr) >> 5) & 1 == 0

    def test_configure_alternate_with_af(self, pal, mem, svd) -> None:
        p = GpioPin("GPIOA", 5, pal)   # AFRL (pin 0-7)
        p.configure_alternate(af=5)     # AF5 = SPI1
        moder_addr = svd.peripheral("GPIOA").address_of("MODER")
        afrl_addr  = svd.peripheral("GPIOA").address_of("AFRL")
        assert (mem.peek(moder_addr) >> 10) & 0b11 == 0b10   # ALTERNATE
        assert (mem.peek(afrl_addr)  >> 20) & 0xF == 5       # AFRL5

    def test_configure_alternate_high_pin(self, pal, mem, svd) -> None:
        p = GpioPin("GPIOA", 9, pal)   # AFRH (pin 8-15)
        p.configure_alternate(af=7)    # AF7 = USART1
        afrh_addr = svd.peripheral("GPIOA").address_of("AFRH")
        assert (mem.peek(afrh_addr) >> 4) & 0xF == 7   # AFRH9 = bits [7:4]


# ===========================================================================
# GpioPin — set / reset / read / toggle
# ===========================================================================


class TestGpioPinIO:
    def test_set_writes_bsrr_set_bit(self, pal, mem, svd) -> None:
        p = GpioPin("GPIOA", 5, pal)
        p.set()
        bsrr_addr = svd.peripheral("GPIOA").address_of("BSRR")
        assert mem.peek(bsrr_addr) == (1 << 5)

    def test_reset_writes_bsrr_reset_bit(self, pal, mem, svd) -> None:
        p = GpioPin("GPIOA", 5, pal)
        p.reset()
        bsrr_addr = svd.peripheral("GPIOA").address_of("BSRR")
        assert mem.peek(bsrr_addr) == (1 << 21)   # bit 5+16

    def test_write_true_calls_set(self, pal, mem, svd) -> None:
        GpioPin("GPIOA", 5, pal).write(True)
        bsrr = mem.peek(svd.peripheral("GPIOA").address_of("BSRR"))
        assert bsrr == (1 << 5)

    def test_write_false_calls_reset(self, pal, mem, svd) -> None:
        GpioPin("GPIOA", 5, pal).write(False)
        bsrr = mem.peek(svd.peripheral("GPIOA").address_of("BSRR"))
        assert bsrr == (1 << 21)

    def test_read_returns_idr_bit(self, pal, mem, svd) -> None:
        idr_addr = svd.peripheral("GPIOA").address_of("IDR")
        mem._mem[idr_addr] = 1 << 5
        assert GpioPin("GPIOA", 5, pal).read() is True

    def test_read_low(self, pal, mem, svd) -> None:
        idr_addr = svd.peripheral("GPIOA").address_of("IDR")
        mem._mem[idr_addr] = 0
        assert GpioPin("GPIOA", 5, pal).read() is False

    def test_toggle_from_low_sets_high(self, pal, mem, svd) -> None:
        odr_addr  = svd.peripheral("GPIOA").address_of("ODR")
        bsrr_addr = svd.peripheral("GPIOA").address_of("BSRR")
        mem._mem[odr_addr] = 0   # PA5 = LOW
        GpioPin("GPIOA", 5, pal).toggle()
        assert mem.peek(bsrr_addr) == (1 << 5)   # set via BSRR

    def test_toggle_from_high_sets_low(self, pal, mem, svd) -> None:
        odr_addr  = svd.peripheral("GPIOA").address_of("ODR")
        bsrr_addr = svd.peripheral("GPIOA").address_of("BSRR")
        mem._mem[odr_addr] = 1 << 5   # PA5 = HIGH
        GpioPin("GPIOA", 5, pal).toggle()
        assert mem.peek(bsrr_addr) == (1 << 21)   # reset via BSRR


# ===========================================================================
# GpioPin — propriedades de estado
# ===========================================================================


class TestGpioPinProperties:
    def test_mode_output(self, pal, mem, svd) -> None:
        moder_addr = svd.peripheral("GPIOA").address_of("MODER")
        mem._mem[moder_addr] = 0b01 << 10   # MODER5 = OUTPUT
        assert GpioPin("GPIOA", 5, pal).mode == GpioMode.OUTPUT

    def test_mode_input(self, pal, mem, svd) -> None:
        moder_addr = svd.peripheral("GPIOA").address_of("MODER")
        mem._mem[moder_addr] = 0
        assert GpioPin("GPIOA", 5, pal).mode == GpioMode.INPUT

    def test_pull_up(self, pal, mem, svd) -> None:
        pupdr_addr = svd.peripheral("GPIOA").address_of("PUPDR")
        mem._mem[pupdr_addr] = 0b01 << 10   # PUPDR5 = PULL_UP
        assert GpioPin("GPIOA", 5, pal).pull == GpioPull.PULL_UP


# ===========================================================================
# GpioInstrument — factory e normalização
# ===========================================================================


class TestGpioInstrument:
    @pytest.mark.parametrize("port", ["A", "PA", "GPIOA", "a", "pa", "gpioa"])
    def test_port_normalization(self, pal, port) -> None:
        g = GpioInstrument(port, pal)
        assert g.periph == "GPIOA"

    def test_pin_returns_gpio_pin(self, gpio_a) -> None:
        p = gpio_a.pin(5)
        assert isinstance(p, GpioPin)
        assert p.pin == 5

    def test_pin_cached(self, gpio_a) -> None:
        assert gpio_a.pin(5) is gpio_a.pin(5)

    def test_different_pins_different_objects(self, gpio_a) -> None:
        assert gpio_a.pin(0) is not gpio_a.pin(1)

    def test_read_port(self, gpio_a, mem, svd) -> None:
        idr_addr = svd.peripheral("GPIOA").address_of("IDR")
        mem._mem[idr_addr] = 0xABCD
        assert gpio_a.read_port() == 0xABCD & 0xFFFF

    def test_write_port_full(self, gpio_a, mem, svd) -> None:
        gpio_a.write_port(0x1234)
        odr_addr = svd.peripheral("GPIOA").address_of("ODR")
        assert mem.peek(odr_addr) & 0xFFFF == 0x1234

    def test_write_port_with_mask(self, gpio_a, mem, svd) -> None:
        odr_addr = svd.peripheral("GPIOA").address_of("ODR")
        mem._mem[odr_addr] = 0xFFFF
        gpio_a.write_port(0x0000, mask=0x00FF)   # zera apenas os 8 bits baixos
        assert mem.peek(odr_addr) & 0xFFFF == 0xFF00

    def test_invalid_port_raises(self, pal) -> None:
        with pytest.raises((ValueError, KeyError)):
            GpioInstrument("GPIOZ", pal).pin(0).read()


# ===========================================================================
# ClockInstrument — GPIO clocks
# ===========================================================================


class TestClockGpio:
    @pytest.mark.parametrize("port,field", [
        ("A", "GPIOAEN"), ("B", "GPIOBEN"), ("C", "GPIOCEN"),
        ("PA", "GPIOAEN"), ("GPIOB", "GPIOBEN"),
    ])
    def test_enable_gpio(self, clk, pal, port, field) -> None:
        clk.enable_gpio(port)
        assert pal.read_field("RCC", "AHB1ENR", field) == 1

    def test_disable_gpio(self, clk, pal) -> None:
        clk.enable_gpio("A")
        clk.disable_gpio("A")
        assert not clk.is_gpio_enabled("A")

    def test_is_gpio_enabled_false_initially(self, clk) -> None:
        assert not clk.is_gpio_enabled("B")   # FakeMemory parte do zero

    def test_is_gpio_enabled_true_after_enable(self, clk) -> None:
        clk.enable_gpio("C")
        assert clk.is_gpio_enabled("C")

    def test_enable_preserves_other_clocks(self, clk, pal) -> None:
        clk.enable_gpio("A")
        clk.enable_gpio("B")
        clk.disable_gpio("A")
        assert clk.is_gpio_enabled("B")   # B não deve ser afetado


# ===========================================================================
# ClockInstrument — USART
# ===========================================================================


class TestClockUsart:
    @pytest.mark.parametrize("n,reg,field", [
        (1, "APB2ENR", "USART1EN"),
        (2, "APB1ENR", "USART2EN"),
        (3, "APB1ENR", "USART3EN"),
        (6, "APB2ENR", "USART6EN"),
    ])
    def test_enable_usart(self, clk, pal, n, reg, field) -> None:
        clk.enable_usart(n)
        assert pal.read_field("RCC", reg, field) == 1

    def test_disable_usart(self, clk) -> None:
        clk.enable_usart(2)
        clk.disable_usart(2)
        assert not clk.is_usart_enabled(2)

    def test_usart1_on_apb2(self, clk, pal) -> None:
        clk.enable_usart(1)
        assert pal.read_field("RCC", "APB2ENR", "USART1EN") == 1

    def test_invalid_usart_raises(self, clk) -> None:
        with pytest.raises(KeyError):
            clk.enable_usart(99)


# ===========================================================================
# ClockInstrument — SPI e I2C
# ===========================================================================


class TestClockSpiI2c:
    def test_enable_spi1_apb2(self, clk, pal) -> None:
        clk.enable_spi(1)
        assert pal.read_field("RCC", "APB2ENR", "SPI1EN") == 1

    def test_enable_spi2_apb1(self, clk, pal) -> None:
        clk.enable_spi(2)
        assert pal.read_field("RCC", "APB1ENR", "SPI2EN") == 1

    def test_enable_i2c1(self, clk, pal) -> None:
        clk.enable_i2c(1)
        assert pal.read_field("RCC", "APB1ENR", "I2C1EN") == 1

    def test_enable_i2c3(self, clk, pal) -> None:
        clk.enable_i2c(3)
        assert pal.read_field("RCC", "APB1ENR", "I2C3EN") == 1

    def test_is_spi_enabled(self, clk) -> None:
        assert not clk.is_spi_enabled(3)
        clk.enable_spi(3)
        assert clk.is_spi_enabled(3)
