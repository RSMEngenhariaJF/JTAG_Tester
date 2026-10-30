"""Analisador de espectro — interface por função, independente de fabricante.

Exemplo::

    sa = get_spectrum_analyzer("sa")
    sa.set_center_span(center_hz=8e6, span_hz=20e6)
    sa.set_rbw(10e3)
    sa.single_sweep()
    f, dbm = sa.peak()                 # marcador no pico
    tr = sa.get_trace()                # Spectrum: freqs_hz / levels_dbm
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.instruments.traceability import InstrumentIdentity


@dataclass
class Spectrum:
    """Traço do analisador: níveis (dBm) nos pontos de frequência (Hz)."""

    freqs_hz:   list[float]
    levels_dbm: list[float]

    def __len__(self) -> int:
        return len(self.levels_dbm)

    def peak(self) -> tuple[float, float]:
        i = max(range(len(self.levels_dbm)), key=self.levels_dbm.__getitem__)
        return self.freqs_hz[i], self.levels_dbm[i]

    def level_at(self, freq_hz: float) -> float:
        """Nível no ponto mais próximo de `freq_hz`."""
        i = min(range(len(self.freqs_hz)), key=lambda k: abs(self.freqs_hz[k] - freq_hz))
        return self.levels_dbm[i]


def linspace(start: float, stop: float, n: int) -> list[float]:
    if n == 1:
        return [start]
    step = (stop - start) / (n - 1)
    return [start + i * step for i in range(n)]


class SpectrumAnalyzer(ABC):
    def __init__(self, driver, identity: InstrumentIdentity | None = None) -> None:
        self._d = driver
        self.identity = identity

    @abstractmethod
    def set_center_span(self, center_hz: float, span_hz: float) -> None: ...

    @abstractmethod
    def set_start_stop(self, start_hz: float, stop_hz: float) -> None: ...

    @abstractmethod
    def set_rbw(self, rbw_hz: float, vbw_hz: float | None = None) -> None: ...

    @abstractmethod
    def set_ref_level(self, dbm: float) -> None: ...

    @abstractmethod
    def single_sweep(self, timeout_s: float = 10.0) -> None:
        """Faz uma varredura e só retorna quando ela termina."""

    @abstractmethod
    def get_trace(self, trace: int = 1) -> Spectrum: ...

    @abstractmethod
    def peak(self) -> tuple[float, float]:
        """(frequência Hz, nível dBm) do pico, pelo marcador do instrumento."""
