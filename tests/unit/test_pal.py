"""Testes unitários da PAL — Peripheral Access Layer.

Usa um FakeMemory (dicionário) + SvdDevice real (STM32F446.svd).
Não requer hardware.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.pal.access import IMemoryAccess, PeripheralAccessLayer
from core.svd.parser import parse

_SVD = Path(__file__).parents[2] / "devices" / "stm32f446" / "STM32F446.svd"


# ---------------------------------------------------------------------------
# Fake memory — dicionário de 32 bits word-addressed
# ---------------------------------------------------------------------------


class FakeMemory:
    """Simula o acesso a memória do adaptador de debug."""

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def svd():
    return parse(_SVD)


@pytest.fixture
def mem():
    return FakeMemory()


@pytest.fixture
def pal(mem, svd):
    return PeripheralAccessLayer(mem, svd)


# ---------------------------------------------------------------------------
# IMemoryAccess Protocol
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_fake_memory_satisfies_protocol(self, mem: FakeMemory) -> None:
        assert isinstance(mem, IMemoryAccess)

    def test_stlink_adiv5_interface(self) -> None:
        # Verifica estruturalmente — sem importar pyocd
        from core.pal.access import IMemoryAccess
        import inspect
        members = {name for name, _ in inspect.getmembers(IMemoryAccess)}
        assert "read_mem32" in members
        assert "write_mem32" in members


# ---------------------------------------------------------------------------
# read_reg / write_reg
# ---------------------------------------------------------------------------


class TestReadWriteReg:
    def test_read_reg_uses_correct_address(self, pal: PeripheralAccessLayer, mem: FakeMemory, svd) -> None:
        # GPIOA->IDR address = 0x40020010
        expected_addr = svd.peripheral("GPIOA").address_of("IDR")
        mem._mem[expected_addr] = 0xABCD1234
        result = pal.read_reg("GPIOA", "IDR")
        assert result == 0xABCD1234
        assert expected_addr in mem.reads

    def test_write_reg_targets_correct_address(self, pal: PeripheralAccessLayer, mem: FakeMemory, svd) -> None:
        expected_addr = svd.peripheral("GPIOA").address_of("ODR")
        pal.write_reg("GPIOA", "ODR", 0x0020)
        assert mem.peek(expected_addr) == 0x0020

    def test_write_reg_truncates_to_32bit(self, pal: PeripheralAccessLayer, mem: FakeMemory, svd) -> None:
        addr = svd.peripheral("GPIOA").address_of("ODR")
        pal.write_reg("GPIOA", "ODR", 0x1_FFFF_FFFF)
        assert mem.peek(addr) == 0xFFFF_FFFF

    def test_read_uninitialised_returns_zero(self, pal: PeripheralAccessLayer) -> None:
        assert pal.read_reg("GPIOB", "ODR") == 0

    def test_unknown_peripheral_raises(self, pal: PeripheralAccessLayer) -> None:
        with pytest.raises(KeyError):
            pal.read_reg("GPIOQ", "ODR")

    def test_unknown_register_raises(self, pal: PeripheralAccessLayer) -> None:
        with pytest.raises(KeyError):
            pal.read_reg("GPIOA", "NONEXISTENT")


# ---------------------------------------------------------------------------
# read_field
# ---------------------------------------------------------------------------


class TestReadField:
    def test_read_moder5_output_mode(self, pal: PeripheralAccessLayer, mem: FakeMemory, svd) -> None:
        # MODER5 ocupa bits [11:10] do MODER
        addr = svd.peripheral("GPIOA").address_of("MODER")
        # Seta MODER5 = 0b01 (output)
        mem._mem[addr] = 0b01 << 10
        assert pal.read_field("GPIOA", "MODER", "MODER5") == 0b01

    def test_read_field_idr5_high(self, pal: PeripheralAccessLayer, mem: FakeMemory, svd) -> None:
        addr = svd.peripheral("GPIOA").address_of("IDR")
        mem._mem[addr] = 1 << 5   # IDR5 = 1
        assert pal.read_field("GPIOA", "IDR", "IDR5") == 1

    def test_read_field_idr5_low(self, pal: PeripheralAccessLayer, mem: FakeMemory, svd) -> None:
        addr = svd.peripheral("GPIOA").address_of("IDR")
        mem._mem[addr] = 0xFFFF & ~(1 << 5)   # IDR5 = 0
        assert pal.read_field("GPIOA", "IDR", "IDR5") == 0

    def test_read_field_does_not_bleed_adjacent_bits(self, pal: PeripheralAccessLayer, mem: FakeMemory, svd) -> None:
        # MODER tem campos de 2 bits; garante que MODER5 não inclui MODER4 ou MODER6
        addr = svd.peripheral("GPIOA").address_of("MODER")
        mem._mem[addr] = 0xFFFFFFFF  # todos os campos = 0b11
        val = pal.read_field("GPIOA", "MODER", "MODER5")
        assert val == 0b11  # apenas os 2 bits de MODER5

    def test_unknown_field_raises(self, pal: PeripheralAccessLayer) -> None:
        with pytest.raises(KeyError):
            pal.read_field("GPIOA", "MODER", "NONEXISTENT")


# ---------------------------------------------------------------------------
# modify_field (Read-Modify-Write)
# ---------------------------------------------------------------------------


class TestModifyField:
    def test_modify_sets_field_bits(self, pal: PeripheralAccessLayer, mem: FakeMemory, svd) -> None:
        addr = svd.peripheral("GPIOA").address_of("MODER")
        mem._mem[addr] = 0x00000000
        pal.modify_field("GPIOA", "MODER", "MODER5", 0b01)
        assert mem.peek(addr) & (0b11 << 10) == 0b01 << 10

    def test_modify_preserves_other_fields(self, pal: PeripheralAccessLayer, mem: FakeMemory, svd) -> None:
        addr = svd.peripheral("GPIOA").address_of("MODER")
        # Coloca MODER0=0b11 e MODER15=0b11
        initial = (0b11 << 0) | (0b11 << 30)
        mem._mem[addr] = initial
        # Modifica apenas MODER5
        pal.modify_field("GPIOA", "MODER", "MODER5", 0b01)
        result = mem.peek(addr)
        # MODER0 e MODER15 não devem ter mudado
        assert (result >> 0) & 0b11 == 0b11
        assert (result >> 30) & 0b11 == 0b11

    def test_modify_clears_field_to_zero(self, pal: PeripheralAccessLayer, mem: FakeMemory, svd) -> None:
        addr = svd.peripheral("GPIOA").address_of("MODER")
        mem._mem[addr] = 0b11 << 10  # MODER5 = 0b11
        pal.modify_field("GPIOA", "MODER", "MODER5", 0b00)
        assert (mem.peek(addr) >> 10) & 0b11 == 0b00

    def test_modify_does_rmw_sequence(self, pal: PeripheralAccessLayer, mem: FakeMemory, svd) -> None:
        addr = svd.peripheral("GPIOA").address_of("MODER")
        mem._mem[addr] = 0xDEAD0000
        pal.modify_field("GPIOA", "MODER", "MODER5", 0b10)
        # Deve ter lido antes de escrever
        assert addr in mem.reads
        assert any(a == addr for a, _ in mem.writes)

    def test_modify_spi_br_field(self, pal: PeripheralAccessLayer, mem: FakeMemory, svd) -> None:
        # SPI1->CR1 tem campo BR[5:3] (baudrate prescaler, 3 bits)
        addr = svd.peripheral("SPI1").address_of("CR1")
        mem._mem[addr] = 0x00000000
        pal.modify_field("SPI1", "CR1", "BR", 0b101)
        assert (mem.peek(addr) >> 3) & 0b111 == 0b101


# ---------------------------------------------------------------------------
# address_of
# ---------------------------------------------------------------------------


class TestAddressOf:
    _EXPECTED = {
        ("GPIOA", "MODER"): 0x40020000,
        ("GPIOA", "ODR"):   0x40020014,
        ("GPIOA", "IDR"):   0x40020010,
        ("GPIOA", "BSRR"): 0x40020018,
        ("TIM1",  "CR1"):  0x40010000,
        ("USART1","SR"):    0x40011000,
        ("DMA1",  "LISR"): 0x40026000,
    }

    @pytest.mark.parametrize("key,addr", _EXPECTED.items())
    def test_address(self, pal: PeripheralAccessLayer, key: tuple, addr: int) -> None:
        assert pal.address_of(*key) == addr, f"{key}: esperado 0x{addr:08X}"


# ---------------------------------------------------------------------------
# BSRR — registrador de set/reset atômico
# ---------------------------------------------------------------------------


class TestBSSR:
    def test_set_pa5_via_bsrr(self, pal: PeripheralAccessLayer, mem: FakeMemory, svd) -> None:
        odr_addr = svd.peripheral("GPIOA").address_of("ODR")
        mem._mem[odr_addr] = 0x0000   # PA5 = 0 inicialmente

        # BSRR: bits [15:0] = set, bits [31:16] = reset
        pal.write_reg("GPIOA", "BSRR", 1 << 5)  # set PA5

        # Simula o hardware: BSRR write → ODR atualizado
        bsrr_val = mem.peek(svd.peripheral("GPIOA").address_of("BSRR"))
        if bsrr_val & 0xFFFF:      # bits de set
            mem._mem[odr_addr] |= bsrr_val & 0xFFFF
        if bsrr_val >> 16:         # bits de reset
            mem._mem[odr_addr] &= ~(bsrr_val >> 16) & 0xFFFF

        assert (mem.peek(odr_addr) >> 5) & 1 == 1

    def test_reset_pa5_via_bsrr(self, pal: PeripheralAccessLayer, mem: FakeMemory, svd) -> None:
        odr_addr = svd.peripheral("GPIOA").address_of("ODR")
        mem._mem[odr_addr] = 1 << 5   # PA5 = 1 inicialmente

        pal.write_reg("GPIOA", "BSRR", 1 << (5 + 16))  # reset PA5

        bsrr_val = mem.peek(svd.peripheral("GPIOA").address_of("BSRR"))
        if bsrr_val >> 16:
            mem._mem[odr_addr] &= ~(bsrr_val >> 16) & 0xFFFF

        assert (mem.peek(odr_addr) >> 5) & 1 == 0
