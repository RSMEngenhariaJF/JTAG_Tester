"""Configuração de instrumentos externos — análogo ao BoardConfig."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DriverType(str, Enum):
    VISA   = "visa"
    SERIAL = "serial"
    SOCKET = "socket"
    MOCK   = "mock"


@dataclass
class InstrumentConfig:
    """Descreve como conectar a um instrumento externo.

    Análogo ao BoardConfig: define o QUE conectar, não a conexão em si.
    A conexão viva fica no InstrumentRegistry.
    """

    name:        str
    driver_type: DriverType
    address:     str
    description: str                    = ""
    params:      dict[str, object]      = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "driver_type": self.driver_type.value,
            "address":     self.address,
            "description": self.description,
            "params":      self.params,
        }

    @classmethod
    def from_dict(cls, d: dict) -> InstrumentConfig:
        return cls(
            name        = d["name"],
            driver_type = DriverType(d["driver_type"]),
            address     = d["address"],
            description = d.get("description", ""),
            params      = d.get("params", {}),
        )
