"""Modelos de instrumento suportados — escolhidos pela resposta de *IDN?.

Para incluir um modelo: implemente a interface por função (Oscilloscope,
SpectrumAnalyzer...) e acrescente uma linha em MODELS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.instruments.traceability import InstrumentIdentity
from instruments.models.rigol_mso8000 import RigolMSO8000
from instruments.models.rs_fpc import RohdeSchwarzFPC


@dataclass(frozen=True)
class ModelEntry:
    key:          str       # valor aceito em InstrumentConfig.params["model"]
    kind:         str       # "oscilloscope" | "spectrum"
    manufacturer: str       # regex sobre o 1º campo do *IDN?
    model:        str       # regex sobre o 2º campo do *IDN?
    cls:          type
    validated:    bool      # já testado em bancada?


MODELS: tuple[ModelEntry, ...] = (
    ModelEntry("rigol_mso8000", "oscilloscope", r"RIGOL", r"MSO8\d{3}", RigolMSO8000, False),
    ModelEntry("rs_fpc", "spectrum", r"Rohde|R&S", r"FPC\d{4}", RohdeSchwarzFPC, False),
)


def find_model(kind: str, identity: InstrumentIdentity | None,
               override: str | None = None) -> ModelEntry | None:
    """Modelo por chave explícita (params["model"]) ou pelo *IDN?."""
    for m in MODELS:
        if m.kind != kind:
            continue
        if override:
            if m.key == override:
                return m
            continue
        if identity and re.search(m.manufacturer, identity.manufacturer, re.I) \
                and re.fullmatch(m.model, identity.model, re.I):
            return m
    return None
