"""Modelo de dados imutável para CMSIS-SVD (ARM System View Description).

Hierarquia: SvdDevice → SvdPeripheral → SvdRegister → SvdField

Referência: CMSIS-SVD Schema 1.1 — https://open-cmsis-pack.github.io/svd-spec/
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SvdField:
    """Bit-field dentro de um registrador."""

    name: str
    description: str
    bit_offset: int   # posição do bit menos significativo
    bit_width: int    # largura em bits
    access: str       # "read-only" | "write-only" | "read-write" | ""

    @property
    def mask(self) -> int:
        """Máscara de bits para este campo no valor do registrador."""
        return ((1 << self.bit_width) - 1) << self.bit_offset

    def extract(self, reg_value: int) -> int:
        """Extrai o valor deste campo de um valor de registrador de 32 bits."""
        return (reg_value & self.mask) >> self.bit_offset


@dataclass(frozen=True)
class SvdRegister:
    """Registrador de um periférico."""

    name: str
    description: str
    address_offset: int   # offset em bytes a partir de SvdPeripheral.base_address
    size: int             # largura em bits (típico: 32)
    access: str           # acesso padrão para campos sem acesso próprio
    reset_value: int      # valor após reset
    fields: tuple[SvdField, ...]

    def field(self, name: str) -> SvdField:
        """Retorna o campo pelo nome (case-insensitive)."""
        name_lower = name.lower()
        for f in self.fields:
            if f.name.lower() == name_lower:
                return f
        raise KeyError(f"Campo '{name}' não encontrado em registrador '{self.name}'")


@dataclass(frozen=True)
class SvdPeripheral:
    """Periférico de um dispositivo ARM."""

    name: str
    description: str
    base_address: int
    group_name: str
    registers: tuple[SvdRegister, ...]

    def register(self, name: str) -> SvdRegister:
        """Retorna o registrador pelo nome (case-insensitive)."""
        name_lower = name.lower()
        for r in self.registers:
            if r.name.lower() == name_lower:
                return r
        raise KeyError(f"Registrador '{name}' não encontrado em periférico '{self.name}'")

    def address_of(self, reg_name: str) -> int:
        """Endereço absoluto de um registrador = base_address + address_offset."""
        return self.base_address + self.register(reg_name).address_offset


@dataclass(frozen=True)
class SvdDevice:
    """Dispositivo ARM descrito pelo arquivo SVD."""

    name: str
    version: str
    description: str
    address_unit_bits: int     # tipicamente 8 (byte-addressable)
    width: int                 # largura do barramento de dados (tipicamente 32)
    peripherals: tuple[SvdPeripheral, ...]

    def peripheral(self, name: str) -> SvdPeripheral:
        """Retorna o periférico pelo nome (case-insensitive)."""
        name_lower = name.lower()
        for p in self.peripherals:
            if p.name.lower() == name_lower:
                return p
        raise KeyError(f"Periférico '{name}' não encontrado")

    def peripheral_names(self) -> list[str]:
        """Lista de nomes de periféricos em ordem de declaração."""
        return [p.name for p in self.peripherals]
