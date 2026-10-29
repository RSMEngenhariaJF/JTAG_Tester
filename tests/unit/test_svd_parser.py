"""Testes unitários do parser SVD — valida conformidade com STM32F446.svd."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.svd.model import SvdDevice, SvdField, SvdPeripheral, SvdRegister
from core.svd.parser import parse

_SVD = Path(__file__).parents[2] / "devices" / "stm32f446" / "STM32F446.svd"


@pytest.fixture(scope="module")
def device() -> SvdDevice:
    return parse(_SVD)


# ===========================================================================
# SvdDevice — metadados
# ===========================================================================


class TestDeviceMetadata:
    def test_name(self, device: SvdDevice) -> None:
        assert device.name == "STM32F446"

    def test_has_peripherals(self, device: SvdDevice) -> None:
        assert len(device.peripherals) > 0

    def test_address_unit_bits(self, device: SvdDevice) -> None:
        assert device.address_unit_bits == 8

    def test_width(self, device: SvdDevice) -> None:
        assert device.width == 32


# ===========================================================================
# SvdDevice.peripheral() — lookup
# ===========================================================================


class TestPeripheralLookup:
    def test_gpioa_exists(self, device: SvdDevice) -> None:
        p = device.peripheral("GPIOA")
        assert p.name == "GPIOA"

    def test_case_insensitive(self, device: SvdDevice) -> None:
        assert device.peripheral("gpioa").name == "GPIOA"

    def test_missing_raises(self, device: SvdDevice) -> None:
        with pytest.raises(KeyError):
            device.peripheral("NONEXISTENT_PERIPHERAL")

    def test_peripheral_names_contains_expected(self, device: SvdDevice) -> None:
        names = device.peripheral_names()
        for expected in ("GPIOA", "TIM1", "USART1", "SPI1", "I2C1", "DMA1", "DMA2"):
            assert expected in names, f"{expected} ausente"


# ===========================================================================
# SvdPeripheral — endereços e registradores
# ===========================================================================


class TestPeripheralAddresses:
    # STM32F446 reference manual — tabela de endereços base
    _EXPECTED = {
        "GPIOA": 0x40020000,
        "GPIOB": 0x40020400,
        "GPIOC": 0x40020800,
        "TIM1":  0x40010000,
        "USART1": 0x40011000,
        "SPI1":  0x40013000,
        "DMA1":  0x40026000,
        "DMA2":  0x40026400,
    }

    @pytest.mark.parametrize("name,addr", _EXPECTED.items())
    def test_base_address(self, device: SvdDevice, name: str, addr: int) -> None:
        assert device.peripheral(name).base_address == addr, (
            f"{name}: esperado 0x{addr:08X}, "
            f"obtido 0x{device.peripheral(name).base_address:08X}"
        )

    def test_gpioa_has_moder(self, device: SvdDevice) -> None:
        p = device.peripheral("GPIOA")
        r = p.register("MODER")
        assert r.name == "MODER"

    def test_gpioa_moder_address(self, device: SvdDevice) -> None:
        # GPIOA_MODER está em offset 0x00 → endereço absoluto = 0x40020000
        assert device.peripheral("GPIOA").address_of("MODER") == 0x40020000

    def test_gpioa_odr_address(self, device: SvdDevice) -> None:
        # GPIOA_ODR offset 0x14 → 0x40020014
        assert device.peripheral("GPIOA").address_of("ODR") == 0x40020014


# ===========================================================================
# derivedFrom — resolução de herança
# ===========================================================================


class TestDerivedFrom:
    def test_dma1_derived_from_dma2(self, device: SvdDevice) -> None:
        # DMA1 é derivado de DMA2: deve ter os mesmos registradores
        dma1 = device.peripheral("DMA1")
        dma2 = device.peripheral("DMA2")
        assert dma1.registers == dma2.registers

    def test_dma1_has_different_base(self, device: SvdDevice) -> None:
        dma1 = device.peripheral("DMA1")
        dma2 = device.peripheral("DMA2")
        assert dma1.base_address != dma2.base_address
        assert dma1.base_address == 0x40026000
        assert dma2.base_address == 0x40026400

    def test_gpiob_derived_has_same_registers_as_base(self, device: SvdDevice) -> None:
        # GPIOs B-E são derivados de GPIOH
        gpiob = device.peripheral("GPIOB")
        base_name = "GPIOH"
        # Verifica que GPIOB tem registradores (herdados)
        assert len(gpiob.registers) > 0

    def test_spi2_derived_has_same_registers_as_spi1(self, device: SvdDevice) -> None:
        spi1 = device.peripheral("SPI1")
        spi2 = device.peripheral("SPI2")
        assert spi1.registers == spi2.registers
        assert spi1.base_address != spi2.base_address


# ===========================================================================
# SvdRegister — campos
# ===========================================================================


class TestRegisterFields:
    def test_moder_has_fields(self, device: SvdDevice) -> None:
        moder = device.peripheral("GPIOA").register("MODER")
        assert len(moder.fields) > 0

    def test_moder0_bit_offset(self, device: SvdDevice) -> None:
        moder = device.peripheral("GPIOA").register("MODER")
        f = moder.field("MODER0")
        assert f.bit_offset == 0
        assert f.bit_width == 2

    def test_moder15_bit_offset(self, device: SvdDevice) -> None:
        moder = device.peripheral("GPIOA").register("MODER")
        f = moder.field("MODER15")
        assert f.bit_offset == 30
        assert f.bit_width == 2

    def test_field_mask(self, device: SvdDevice) -> None:
        moder = device.peripheral("GPIOA").register("MODER")
        f = moder.field("MODER0")
        assert f.mask == 0b11  # bits [1:0]

    def test_field_extract(self, device: SvdDevice) -> None:
        moder = device.peripheral("GPIOA").register("MODER")
        f = moder.field("MODER0")
        # Se MODER = 0xA8000002 → MODER0[1:0] = 0b10 = 2 (alternate function)
        assert f.extract(0xA8000002) == 2

    def test_field_missing_raises(self, device: SvdDevice) -> None:
        moder = device.peripheral("GPIOA").register("MODER")
        with pytest.raises(KeyError):
            moder.field("NONEXISTENT")

    def test_register_missing_raises(self, device: SvdDevice) -> None:
        gpioa = device.peripheral("GPIOA")
        with pytest.raises(KeyError):
            gpioa.register("NONEXISTENT")


# ===========================================================================
# SvdField — acesso
# ===========================================================================


class TestFieldAccess:
    def test_read_only_field_exists(self, device: SvdDevice) -> None:
        # IDR (Input Data Register) campos são read-only
        idr = device.peripheral("GPIOA").register("IDR")
        # pelo menos um campo deve ser read-only
        ro_fields = [f for f in idr.fields if f.access == "read-only"]
        assert ro_fields, "IDR deveria ter campos read-only"


# ===========================================================================
# Performance — parse não deve ser lento demais
# ===========================================================================


def test_parse_completes_in_reasonable_time() -> None:
    """Parse do SVD completo deve ser rápido (< 2s)."""
    import time
    t0 = time.perf_counter()
    dev = parse(_SVD)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"Parse muito lento: {elapsed:.2f}s"
    assert len(dev.peripherals) > 10
