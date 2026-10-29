"""Testes unitários de UsartInstrument.

Usa FakeMemory + PAL real (com SVD) para simular registradores do STM32F446.

Execucao:
    pytest tests/unit/test_usart.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.pal.access import PeripheralAccessLayer
from core.svd.parser import parse
from instruments.usart import Parity, StopBits, UsartInstrument, WordLength, _baud_divider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeMemory:
    def __init__(self) -> None:
        self._mem: dict[int, int] = {}

    def read_mem32(self, addr: int) -> int:
        return self._mem.get(addr & ~3, 0)

    def write_mem32(self, addr: int, value: int) -> None:
        self._mem[addr & ~3] = value & 0xFFFF_FFFF


@pytest.fixture(scope="module")
def svd():
    return parse(Path("devices/stm32f446/STM32F446.svd"))


@pytest.fixture
def pal(svd):
    return PeripheralAccessLayer(FakeMemory(), svd)


@pytest.fixture
def u1(pal):
    return UsartInstrument(1, pal)


# ===========================================================================
# Criacao
# ===========================================================================


class TestUsartCreation:
    def test_periph_name_usart1(self, u1) -> None:
        assert u1.periph == "USART1"

    def test_periph_name_usart6(self, pal) -> None:
        assert UsartInstrument(6, pal).periph == "USART6"

    def test_periph_name_uart4(self, pal) -> None:
        assert UsartInstrument(4, pal).periph == "UART4"

    def test_periph_name_uart5(self, pal) -> None:
        assert UsartInstrument(5, pal).periph == "UART5"

    def test_invalid_number_raises(self, pal) -> None:
        with pytest.raises(KeyError):
            UsartInstrument(7, pal)

    def test_zero_raises(self, pal) -> None:
        with pytest.raises(KeyError):
            UsartInstrument(0, pal)


# ===========================================================================
# Calculo do divisor de baud rate
# ===========================================================================


class TestBaudDivider:
    def test_115200_at_16mhz(self) -> None:
        m, f = _baud_divider(115200, 16_000_000)
        assert m == 8
        assert f == 10   # 0x8A >> 4 = 8, 0x8A & 0xF = 10

    def test_9600_at_16mhz(self) -> None:
        m, f = _baud_divider(9600, 16_000_000)
        # 16_000_000 // 9600 = 1666 = 0x682; mantissa = 104 = 0x68, fraction = 2
        assert m == 104
        assert f == 2

    def test_115200_at_84mhz(self) -> None:
        m, f = _baud_divider(115200, 84_000_000)
        # 84_000_000 // 115200 = 729 = 0x2D9; mantissa = 45 = 0x2D, fraction = 9
        assert m == 45
        assert f == 9


# ===========================================================================
# configure()
# ===========================================================================


class TestUsartConfigure:
    def test_sets_brr_mantissa_and_fraction(self, u1, pal) -> None:
        u1.configure(baud=115200, f_clk=16_000_000)
        assert pal.read_field("USART1", "BRR", "DIV_Mantissa") == 8
        assert pal.read_field("USART1", "BRR", "DIV_Fraction") == 10

    def test_configure_does_not_enable(self, u1) -> None:
        u1.configure()
        assert not u1.is_enabled

    def test_word_length_8_sets_m0(self, u1, pal) -> None:
        u1.configure(word_length=WordLength.BITS_8)
        assert pal.read_field("USART1", "CR1", "M") == 0

    def test_word_length_9_sets_m1(self, u1, pal) -> None:
        u1.configure(word_length=WordLength.BITS_9)
        assert pal.read_field("USART1", "CR1", "M") == 1

    def test_parity_none_clears_pce(self, u1, pal) -> None:
        u1.configure(parity=Parity.NONE)
        assert pal.read_field("USART1", "CR1", "PCE") == 0

    def test_parity_even_sets_pce1_ps0(self, u1, pal) -> None:
        u1.configure(parity=Parity.EVEN)
        assert pal.read_field("USART1", "CR1", "PCE") == 1
        assert pal.read_field("USART1", "CR1", "PS")  == 0

    def test_parity_odd_sets_pce1_ps1(self, u1, pal) -> None:
        u1.configure(parity=Parity.ODD)
        assert pal.read_field("USART1", "CR1", "PCE") == 1
        assert pal.read_field("USART1", "CR1", "PS")  == 1

    def test_stop_one_sets_00(self, u1, pal) -> None:
        u1.configure(stop=StopBits.ONE)
        assert pal.read_field("USART1", "CR2", "STOP") == 0b00

    def test_stop_two_sets_10(self, u1, pal) -> None:
        u1.configure(stop=StopBits.TWO)
        assert pal.read_field("USART1", "CR2", "STOP") == 0b10


# ===========================================================================
# enable() / disable()
# ===========================================================================


class TestUsartEnable:
    def test_enable_sets_ue_te_re(self, u1, pal) -> None:
        u1.enable()
        assert pal.read_field("USART1", "CR1", "UE") == 1
        assert pal.read_field("USART1", "CR1", "TE") == 1
        assert pal.read_field("USART1", "CR1", "RE") == 1

    def test_enable_tx_only(self, u1, pal) -> None:
        u1.enable(tx=True, rx=False)
        assert pal.read_field("USART1", "CR1", "TE") == 1
        assert pal.read_field("USART1", "CR1", "RE") == 0

    def test_enable_rx_only(self, u1, pal) -> None:
        u1.enable(tx=False, rx=True)
        assert pal.read_field("USART1", "CR1", "TE") == 0
        assert pal.read_field("USART1", "CR1", "RE") == 1

    def test_disable_clears_ue(self, u1, pal) -> None:
        u1.enable()
        u1.disable()
        assert pal.read_field("USART1", "CR1", "UE") == 0


# ===========================================================================
# Propriedades de estado
# ===========================================================================


class TestUsartStatus:
    def test_is_enabled_false_initially(self, u1) -> None:
        assert not u1.is_enabled

    def test_is_tx_enabled_reflects_te(self, u1) -> None:
        u1.enable(tx=True, rx=False)
        assert u1.is_tx_enabled

    def test_is_rx_enabled_reflects_re(self, u1) -> None:
        u1.enable(tx=False, rx=True)
        assert u1.is_rx_enabled

    def test_is_tx_empty_from_sr(self, pal) -> None:
        # Força SR.TXE=1 escrevendo no registrador
        sr_field_offset = 7   # TXE fica em bit 7
        pal.write_reg("USART1", "SR", 1 << sr_field_offset)
        u = UsartInstrument(1, pal)
        assert u.is_tx_empty

    def test_is_rx_ready_from_sr(self, pal) -> None:
        # RXNE está no bit 5
        pal.write_reg("USART1", "SR", 1 << 5)
        u = UsartInstrument(1, pal)
        assert u.is_rx_ready

    def test_read_status_returns_raw_sr(self, pal) -> None:
        pal.write_reg("USART1", "SR", 0xAB)
        u = UsartInstrument(1, pal)
        assert u.read_status() == 0xAB
