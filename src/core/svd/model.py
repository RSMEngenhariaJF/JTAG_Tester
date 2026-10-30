"""Modelo de dados imutável para CMSIS-SVD (ARM System View Description).

Hierarquia: SvdDevice → SvdPeripheral → SvdRegister → SvdField

Referência: CMSIS-SVD Schema 1.1 — https://open-cmsis-pack.github.io/svd-spec/
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Nomes de campo de GPIO que mudam entre famílias STM32 (SVDs antigos e novos):
# F4/F7 usam MODER5/ODR5/IDR5/AFRH8; H7/G0/L4+ usam MODE5/OD5/ID5/AFSEL8.
# O par (antigo, novo) é tentado nos dois sentidos, para os testes servirem às duas.
_FIELD_ALIASES: tuple[tuple[str, str], ...] = (
    (r"MODER(\d+)", r"MODE\1"),
    (r"ODR(\d+)", r"OD\1"),
    (r"IDR(\d+)", r"ID\1"),
    (r"OSPEEDR(\d+)", r"OSPEED\1"),
    (r"PUPDR(\d+)", r"PUPD\1"),
    (r"AFR[LH](\d+)", r"AFSEL\1"),
)


def _field_aliases(name: str) -> list[str]:
    """Nomes equivalentes de `name` em outras famílias (ex.: MODER5 ↔ MODE5)."""
    out: list[str] = []
    for old, new in _FIELD_ALIASES:
        if m := re.fullmatch(old, name, re.IGNORECASE):
            out.append(m.expand(new))
        elif m := re.fullmatch(new.replace(r"\1", r"(\d+)"), name, re.IGNORECASE):
            n = int(m.group(1))
            out.append(old.replace(r"(\d+)", str(n)).replace("[LH]", "H" if n >= 8 else "L"))
    return out


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
        """Retorna o campo pelo nome (case-insensitive), aceitando sinônimos de GPIO."""
        for candidate in (name, *_field_aliases(name)):
            name_lower = candidate.lower()
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
