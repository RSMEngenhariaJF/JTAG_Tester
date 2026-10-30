"""Acesso por função: o teste pede "o osciloscópio", não um modelo.

    osc = get_oscilloscope("osc")        # None se não conectado → teste faz _skip
    sa  = get_spectrum_analyzer("sa")

O modelo vem de InstrumentConfig.params["model"] ou, se ausente, do *IDN?
lido na conexão (ver instruments.models.MODELS).
"""

from __future__ import annotations

from core.instruments.oscilloscope import Oscilloscope
from core.instruments.registry import InstrumentRegistry
from core.instruments.spectrum import SpectrumAnalyzer


class UnsupportedModelError(LookupError):
    """O instrumento conectado não tem implementação para a função pedida."""


def _wrap(name: str, kind: str):
    from instruments.models import find_model

    reg = InstrumentRegistry.instance()
    driver = reg.get(name)
    if driver is None:
        return None
    config = reg.config(name)
    identity = reg.identity(name)
    override = config.params.get("model") if config else None
    entry = find_model(kind, identity, override)
    if entry is None:
        raise UnsupportedModelError(
            f"'{name}' ({identity or 'sem *IDN?'}) não é um {kind} suportado — "
            "defina params['model'] ou acrescente o modelo em instruments.models.MODELS"
        )
    return entry.cls(driver, identity)


def get_oscilloscope(name: str) -> Oscilloscope | None:
    return _wrap(name, "oscilloscope")


def get_spectrum_analyzer(name: str) -> SpectrumAnalyzer | None:
    return _wrap(name, "spectrum")
