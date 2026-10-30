"""Rastreabilidade de instrumentos — identificação (*IDN?) e situação de calibração.

Cada medição usada como registro de qualidade precisa dizer com qual aparelho
foi feita (fabricante, modelo, nº de série, firmware) e se ele estava dentro da
validade de calibração. Os dados de calibração vêm de InstrumentConfig.params:

    "calibration_due": "2027-03-31"   # validade (AAAA-MM-DD)
    "asset_id":        "PAT-00123"    # patrimônio / identificação interna
    "block_if_expired": true          # recusa conectar com calibração vencida
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum

DUE_SOON_DAYS: int = 30


@dataclass(frozen=True)
class InstrumentIdentity:
    """Resposta de *IDN? (IEEE 488.2): fabricante, modelo, série, firmware."""

    manufacturer: str
    model:        str
    serial:       str
    firmware:     str

    @classmethod
    def parse(cls, idn: str) -> InstrumentIdentity | None:
        """Interpreta a resposta de *IDN?. Retorna None se não tiver 4 campos."""
        parts = [p.strip() for p in idn.strip().split(",")]
        if len(parts) < 4 or not parts[0] or not parts[1]:
            return None
        return cls(parts[0], parts[1], parts[2], ",".join(parts[3:]))

    def __str__(self) -> str:
        return f"{self.manufacturer} {self.model} (S/N {self.serial}, FW {self.firmware})"


class CalibrationStatus(str, Enum):
    VALID    = "válida"
    DUE_SOON = "vence em breve"
    EXPIRED  = "vencida"
    UNKNOWN  = "não informada"


def parse_due(value: object) -> date | None:
    """Converte 'AAAA-MM-DD' em date; None se ausente ou inválido."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def calibration_status(due: date | None, today: date | None = None) -> CalibrationStatus:
    if due is None:
        return CalibrationStatus.UNKNOWN
    today = today or date.today()
    if due < today:
        return CalibrationStatus.EXPIRED
    if (due - today).days <= DUE_SOON_DAYS:
        return CalibrationStatus.DUE_SOON
    return CalibrationStatus.VALID


class CalibrationExpiredError(RuntimeError):
    """Conexão recusada: calibração vencida e block_if_expired ativo."""


@dataclass
class TraceRecord:
    """Linha de rastreabilidade de um instrumento usado na sessão."""

    name:            str
    address:         str
    identity:        InstrumentIdentity | None
    asset_id:        str
    calibration_due: date | None
    status:          CalibrationStatus

    def to_dict(self) -> dict:
        ident = asdict(self.identity) if self.identity else {}
        return {
            "name":            self.name,
            "address":         self.address,
            "manufacturer":    ident.get("manufacturer", ""),
            "model":           ident.get("model", ""),
            "serial":          ident.get("serial", ""),
            "firmware":        ident.get("firmware", ""),
            "asset_id":        self.asset_id,
            "calibration_due": self.calibration_due.isoformat() if self.calibration_due else "",
            "calibration":     self.status.value,
        }
