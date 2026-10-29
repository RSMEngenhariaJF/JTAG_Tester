"""Testes unitários de SpiInstrument.

Usa FakeMemory + PAL real (com SVD) para simular registradores do STM32F446.

Execucao:
    pytest tests/unit/test_spi.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.pal.access import PeripheralAccessLayer
from core.svd.parser import parse
from instruments.spi import SpiBaudDiv, SpiInstrument


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
def s1(pal):
    return SpiInstrument(1, pal)


# ===========================================================================
# Criacao
# ===========================================================================


class TestSpiCreation:
    def test_periph_name_spi1(self, s1) -> None:
        assert s1.periph == "SPI1"

    def test_periph_name_spi4(self, pal) -> None:
        assert SpiInstrument(4, pal).periph == "SPI4"

    def test_invalid_number_raises(self, pal) -> None:
        with pytest.raises(KeyError):
            SpiInstrument(5, pal)

    def test_zero_raises(self, pal) -> None:
        with pytest.raises(KeyError):
            SpiInstrument(0, pal)


# ===========================================================================
# configure()
# ===========================================================================


class TestSpiConfigure:
    def test_mode0_sets_cpol0_cpha0(self, s1, pal) -> None:
        s1.configure(mode=0)
        assert pal.read_field("SPI1", "CR1", "CPOL") == 0
        assert pal.read_field("SPI1", "CR1", "CPHA") == 0

    def test_mode1_sets_cpol0_cpha1(self, s1, pal) -> None:
        s1.configure(mode=1)
        assert pal.read_field("SPI1", "CR1", "CPOL") == 0
        assert pal.read_field("SPI1", "CR1", "CPHA") == 1

    def test_mode2_sets_cpol1_cpha0(self, s1, pal) -> None:
        s1.configure(mode=2)
        assert pal.read_field("SPI1", "CR1", "CPOL") == 1
        assert pal.read_field("SPI1", "CR1", "CPHA") == 0

    def test_mode3_sets_cpol1_cpha1(self, s1, pal) -> None:
        s1.configure(mode=3)
        assert pal.read_field("SPI1", "CR1", "CPOL") == 1
        assert pal.read_field("SPI1", "CR1", "CPHA") == 1

    def test_invalid_mode_raises(self, s1) -> None:
        with pytest.raises(ValueError, match="inválido"):
            s1.configure(mode=4)

    def test_baud_div_set(self, s1, pal) -> None:
        s1.configure(baud_div=SpiBaudDiv.DIV_32)
        assert pal.read_field("SPI1", "CR1", "BR") == int(SpiBaudDiv.DIV_32)

    def test_baud_div_256(self, s1, pal) -> None:
        s1.configure(baud_div=SpiBaudDiv.DIV_256)
        assert pal.read_field("SPI1", "CR1", "BR") == 0b111

    def test_data_8bit_sets_dff0(self, s1, pal) -> None:
        s1.configure(data_16bit=False)
        assert pal.read_field("SPI1", "CR1", "DFF") == 0

    def test_data_16bit_sets_dff1(self, s1, pal) -> None:
        s1.configure(data_16bit=True)
        assert pal.read_field("SPI1", "CR1", "DFF") == 1

    def test_msb_first_default(self, s1, pal) -> None:
        s1.configure(lsb_first=False)
        assert pal.read_field("SPI1", "CR1", "LSBFIRST") == 0

    def test_lsb_first(self, s1, pal) -> None:
        s1.configure(lsb_first=True)
        assert pal.read_field("SPI1", "CR1", "LSBFIRST") == 1

    def test_master_mode_default(self, s1, pal) -> None:
        s1.configure()
        assert pal.read_field("SPI1", "CR1", "MSTR") == 1

    def test_slave_mode(self, s1, pal) -> None:
        s1.configure(master=False)
        assert pal.read_field("SPI1", "CR1", "MSTR") == 0

    def test_sw_nss_sets_ssm_and_ssi(self, s1, pal) -> None:
        s1.configure(sw_nss=True)
        assert pal.read_field("SPI1", "CR1", "SSM") == 1
        assert pal.read_field("SPI1", "CR1", "SSI") == 1

    def test_hw_nss_clears_ssm(self, s1, pal) -> None:
        s1.configure(sw_nss=False)
        assert pal.read_field("SPI1", "CR1", "SSM") == 0


# ===========================================================================
# enable() / disable()
# ===========================================================================


class TestSpiEnable:
    def test_enable_sets_spe(self, s1, pal) -> None:
        s1.enable()
        assert pal.read_field("SPI1", "CR1", "SPE") == 1

    def test_disable_clears_spe(self, s1, pal) -> None:
        s1.enable()
        s1.disable()
        assert pal.read_field("SPI1", "CR1", "SPE") == 0

    def test_is_enabled_false_initially(self, s1) -> None:
        assert not s1.is_enabled

    def test_is_enabled_true_after_enable(self, s1) -> None:
        s1.enable()
        assert s1.is_enabled


# ===========================================================================
# Propriedades de estado (SR)
# ===========================================================================


class TestSpiStatus:
    def test_is_busy_from_bsy(self, pal) -> None:
        # BSY está no bit 7 do SR
        pal.write_reg("SPI1", "SR", 1 << 7)
        assert SpiInstrument(1, pal).is_busy

    def test_is_tx_empty_from_txe(self, pal) -> None:
        # TXE está no bit 1 do SR (verificar via SVD: offset=1, width=1)
        pal.write_reg("SPI1", "SR", 1 << 1)
        assert SpiInstrument(1, pal).is_tx_empty

    def test_is_rx_ready_from_rxne(self, pal) -> None:
        # RXNE está no bit 0 do SR
        pal.write_reg("SPI1", "SR", 1 << 0)
        assert SpiInstrument(1, pal).is_rx_ready

    def test_read_status_raw(self, pal) -> None:
        pal.write_reg("SPI1", "SR", 0x03)
        assert SpiInstrument(1, pal).read_status() == 0x03

    def test_mode_property_roundtrip(self, s1) -> None:
        for m in range(4):
            s1.configure(mode=m)
            assert s1.mode == m
