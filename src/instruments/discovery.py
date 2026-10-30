"""Descoberta de instrumentos VISA (LAN, USB-TMC, GPIB) com leitura de *IDN?."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from core.instruments.traceability import InstrumentIdentity

logger = logging.getLogger("instruments.discovery")


@dataclass
class DiscoveredInstrument:
    resource: str
    idn:      str = ""
    error:    str = ""

    @property
    def identity(self) -> InstrumentIdentity | None:
        return InstrumentIdentity.parse(self.idn) if self.idn else None

    def suggested_name(self) -> str:
        """Nome curto para o registro: osc / sa / modelo em minúsculas."""
        from instruments.models import find_model

        ident = self.identity
        if ident is None:
            return "instrumento"
        for kind, short in (("oscilloscope", "osc"), ("spectrum", "sa")):
            if find_model(kind, ident):
                return short
        return re.sub(r"[^a-z0-9]+", "_", ident.model.lower()).strip("_") or "instrumento"


def discover_visa(rm=None, *, include_serial: bool = False,
                  timeout_ms: int = 2000) -> list[DiscoveredInstrument]:
    """Lista recursos VISA e pergunta *IDN? a cada um.

    Portas seriais (ASRL) ficam de fora por padrão: muitas são VCP de probes
    ou outros dispositivos que não falam SCPI. O mesmo aparelho visto por mais
    de um recurso (ex.: VXI-11 e HiSLIP) aparece uma vez só.
    """
    if rm is None:
        import pyvisa  # type: ignore[import]
        rm = pyvisa.ResourceManager()

    found: list[DiscoveredInstrument] = []
    seen: set[tuple[str, str, str]] = set()
    for res in rm.list_resources():
        if res.upper().startswith("ASRL") and not include_serial:
            continue
        item = DiscoveredInstrument(res)
        try:
            inst = rm.open_resource(res)
            try:
                inst.timeout = timeout_ms
                item.idn = inst.query("*IDN?").strip()
            finally:
                inst.close()
        except Exception as exc:
            item.error = str(exc)
            logger.info("Sem resposta de %s: %s", res, exc)
        ident = item.identity
        if ident is not None:
            key = (ident.manufacturer, ident.model, ident.serial)
            if key in seen:
                continue
            seen.add(key)
        found.append(item)
    return found
