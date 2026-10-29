"""Testes de hardware da PAL via ST-Link (NUCLEO-F446RE).

Execução:
    pytest tests/hardware/test_pal_stlink.py -m hardware --stlink -v

Pré-requisitos:
    - NUCLEO-F446RE conectada via USB
    - pyocd pack install stm32f446retx (já feito)
    - Firmware padrão da NUCLEO (LED PA5 piscando)
"""

from __future__ import annotations

import pytest

# Endereços fora do SVD (debug core ARM)
_DBGMCU_IDCODE = 0xE0042000   # bits[11:0] = DEV_ID, bits[31:16] = REV_ID
_STM32F446_DEV_ID = 0x421


@pytest.mark.hardware
class TestDeviceIdentification:
    def test_dbgmcu_device_id(self, pal_stlink) -> None:
        """DBGMCU_IDCODE deve reportar DEV_ID = 0x421 (STM32F446)."""
        idcode = pal_stlink.mem.read_mem32(_DBGMCU_IDCODE)
        dev_id = idcode & 0xFFF
        assert dev_id == _STM32F446_DEV_ID, (
            f"DEV_ID esperado 0x{_STM32F446_DEV_ID:03X}, obtido 0x{dev_id:03X}"
        )
        print(f"\n  DBGMCU_IDCODE = 0x{idcode:08X}  (DEV_ID=0x{dev_id:03X}  REV_ID=0x{idcode >> 16:04X})")

    def test_svd_peripheral_count(self, pal_stlink) -> None:
        """SVD carregado deve ter periféricos."""
        assert len(pal_stlink.device.peripherals) > 10

    def test_svd_device_name(self, pal_stlink) -> None:
        assert pal_stlink.device.name == "STM32F446"


@pytest.mark.hardware
class TestClocks:
    def test_rcc_gpioaen_enabled(self, pal_stlink) -> None:
        """RCC->AHB1ENR bit GPIOAEN deve estar habilitado (LED usa GPIOA)."""
        gpioaen = pal_stlink.read_field("RCC", "AHB1ENR", "GPIOAEN")
        assert gpioaen == 1, "Clock do GPIOA não está habilitado"

    def test_rcc_gpiocen_enabled(self, pal_stlink) -> None:
        """GPIOC deve estar habilitado (botão USER em PC13)."""
        gpiocen = pal_stlink.read_field("RCC", "AHB1ENR", "GPIOCEN")
        assert gpiocen == 1, "Clock do GPIOC não está habilitado"

    def test_rcc_ahb1enr_address(self, pal_stlink) -> None:
        """Endereço do RCC->AHB1ENR deve ser 0x40023830."""
        addr = pal_stlink.address_of("RCC", "AHB1ENR")
        assert addr == 0x40023830


@pytest.mark.hardware
class TestGPIOA:
    def test_idr_readable(self, pal_stlink) -> None:
        """GPIOA->IDR deve ser legível (16 bits válidos)."""
        idr = pal_stlink.read_reg("GPIOA", "IDR")
        assert 0 <= idr <= 0xFFFF, f"IDR fora do range: 0x{idr:08X}"
        print(f"\n  GPIOA->IDR = 0x{idr:04X}")

    def test_pa5_configured_as_output(self, pal_stlink) -> None:
        """PA5 (LED LD2) deve estar configurado como saída (MODER5 = 0b01)."""
        moder5 = pal_stlink.read_field("GPIOA", "MODER", "MODER5")
        assert moder5 == 0b01, (
            f"MODER5 esperado 0b01 (output), obtido 0b{moder5:02b} "
            f"({'input' if moder5 == 0 else 'alternate' if moder5 == 2 else 'analog'})"
        )

    def test_pa5_odr_readable(self, pal_stlink) -> None:
        """GPIOA->ODR deve ser legível."""
        odr = pal_stlink.read_reg("GPIOA", "ODR")
        print(f"\n  GPIOA->ODR = 0x{odr:04X}  (PA5={'HIGH' if (odr >> 5) & 1 else 'LOW'})")
        assert 0 <= odr <= 0xFFFF

    def test_pc13_configured_as_input(self, pal_stlink) -> None:
        """PC13 (botão USER) deve estar configurado como entrada (MODER13 = 0b00)."""
        moder13 = pal_stlink.read_field("GPIOC", "MODER", "MODER13")
        assert moder13 == 0b00, f"MODER13 esperado 0b00 (input), obtido 0b{moder13:02b}"


@pytest.mark.hardware
class TestLEDToggle:
    """Toggle do LED LD2 (PA5) via BSRR — CPU em halt durante o teste."""

    def test_set_led_via_bsrr(self, pal_stlink) -> None:
        """Seta PA5 via BSRR e confirma via ODR."""
        pal_stlink.write_reg("GPIOA", "BSRR", 1 << 5)   # set PA5
        odr5 = pal_stlink.read_field("GPIOA", "ODR", "ODR5")
        assert odr5 == 1, "LED deveria estar HIGH após set via BSRR"

    def test_reset_led_via_bsrr(self, pal_stlink) -> None:
        """Reseta PA5 via BSRR e confirma via ODR."""
        pal_stlink.write_reg("GPIOA", "BSRR", 1 << (5 + 16))   # reset PA5
        odr5 = pal_stlink.read_field("GPIOA", "ODR", "ODR5")
        assert odr5 == 0, "LED deveria estar LOW após reset via BSRR"

    def test_toggle_cycle(self, pal_stlink) -> None:
        """Ciclo completo: lê, inverte, confirma, restaura."""
        before = pal_stlink.read_field("GPIOA", "ODR", "ODR5")

        # Inverte
        if before:
            pal_stlink.write_reg("GPIOA", "BSRR", 1 << (5 + 16))
        else:
            pal_stlink.write_reg("GPIOA", "BSRR", 1 << 5)

        after = pal_stlink.read_field("GPIOA", "ODR", "ODR5")
        assert after != before, "Toggle não funcionou"

        # Restaura
        if before:
            pal_stlink.write_reg("GPIOA", "BSRR", 1 << 5)
        else:
            pal_stlink.write_reg("GPIOA", "BSRR", 1 << (5 + 16))

        restored = pal_stlink.read_field("GPIOA", "ODR", "ODR5")
        assert restored == before, "Restauração do estado original falhou"


@pytest.mark.hardware
class TestRegisterReadBack:
    """Escreve em registradores de configuração e lê de volta."""

    def test_modify_and_restore_moder5(self, pal_stlink) -> None:
        """Altera MODER5 temporariamente e restaura."""
        original = pal_stlink.read_field("GPIOA", "MODER", "MODER5")
        try:
            # Muda para alternate function (0b10) temporariamente
            pal_stlink.modify_field("GPIOA", "MODER", "MODER5", 0b10)
            readback = pal_stlink.read_field("GPIOA", "MODER", "MODER5")
            assert readback == 0b10, f"MODER5 esperado 0b10, obtido 0b{readback:02b}"
        finally:
            # Sempre restaura para não deixar o pino preso
            pal_stlink.modify_field("GPIOA", "MODER", "MODER5", original)
            assert pal_stlink.read_field("GPIOA", "MODER", "MODER5") == original
