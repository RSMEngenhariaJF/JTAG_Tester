"""Osciloscópio — interface por função, independente de fabricante.

O teste usa só esta interface; o modelo concreto (ex.: RigolMSO8000) é
escolhido pela identificação *IDN? em core.instruments.roles.get_oscilloscope().

Exemplo::

    osc = get_oscilloscope("osc")
    if osc is None:
        return self._skip("Osciloscópio não conectado")
    osc.configure_channel(1, scale_v=1.0)
    osc.set_timebase(1e-6)
    osc.set_edge_trigger(1, level_v=1.65)
    osc.acquire_single(timeout_s=2)
    wf = osc.get_waveform(1)
    edges = wf.edges(level_v=1.65)                    # → analyze_frequency(...)
    f = osc.measure("frequency", 1)
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from core.instruments.traceability import InstrumentIdentity

MEASUREMENTS: tuple[str, ...] = (
    "frequency", "period", "vpp", "vmax", "vmin", "vavg", "vrms", "amplitude",
    "rise_time", "fall_time", "pos_width", "neg_width", "duty", "overshoot",
)


@dataclass
class Waveform:
    """Forma de onda adquirida: t[i] = t0 + i * dt."""

    volts:  list[float]
    dt:     float
    t0:     float = 0.0
    source: str = ""
    meta:   dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.volts)

    def times(self) -> list[float]:
        return [self.t0 + i * self.dt for i in range(len(self.volts))]

    def edges(self, level_v: float, slope: str = "rising") -> list[float]:
        """Instantes (s) em que o sinal cruza `level_v`, com interpolação linear.

        slope: "rising", "falling" ou "either". A lista alimenta diretamente
        analyze_frequency / analyze_timing / analyze_jitter.
        """
        out: list[float] = []
        v = self.volts
        for i in range(1, len(v)):
            a, b = v[i - 1], v[i]
            rising = a < level_v <= b
            falling = a > level_v >= b
            if (slope == "rising" and rising) or (slope == "falling" and falling) or \
               (slope == "either" and (rising or falling)):
                frac = (level_v - a) / (b - a)
                out.append(self.t0 + (i - 1 + frac) * self.dt)
        return out


class Oscilloscope(ABC):
    """Operações comuns a osciloscópios. Canais numerados a partir de 1."""

    channels: int = 4

    def __init__(self, driver, identity: InstrumentIdentity | None = None) -> None:
        self._d = driver
        self.identity = identity

    def _check_channel(self, ch: int) -> None:
        if not 1 <= ch <= self.channels:
            raise ValueError(f"Canal {ch} inválido (1..{self.channels})")

    # ── Configuração ─────────────────────────────────────────────────────
    @abstractmethod
    def configure_channel(self, ch: int, scale_v: float, offset_v: float = 0.0, *,
                          coupling: str = "DC", probe: float = 1.0,
                          enabled: bool = True) -> None: ...

    @abstractmethod
    def set_timebase(self, scale_s: float, offset_s: float = 0.0) -> None: ...

    @abstractmethod
    def set_edge_trigger(self, source_ch: int, level_v: float, slope: str = "rising",
                         sweep: str = "single") -> None: ...

    # ── Aquisição ────────────────────────────────────────────────────────
    @abstractmethod
    def run(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def single(self) -> None:
        """Arma uma aquisição única (aguarda o trigger)."""

    @abstractmethod
    def force_trigger(self) -> None: ...

    @abstractmethod
    def is_stopped(self) -> bool:
        """True quando a aquisição terminou (após single + trigger)."""

    def acquire_single(self, timeout_s: float = 5.0, poll_s: float = 0.05,
                       arm: bool = True) -> None:
        """Arma (opcional) e espera a aquisição única terminar."""
        if arm:
            self.single()
        deadline = time.monotonic() + timeout_s
        time.sleep(poll_s)
        while not self.is_stopped():
            if time.monotonic() > deadline:
                raise TimeoutError(f"Osciloscópio não disparou em {timeout_s} s")
            time.sleep(poll_s)

    # ── Resultados ───────────────────────────────────────────────────────
    @abstractmethod
    def measure(self, item: str, ch: int) -> float:
        """Medida automática do instrumento (ver MEASUREMENTS). NaN se inválida."""

    @abstractmethod
    def get_waveform(self, ch: int, *, raw: bool = False) -> Waveform:
        """Forma de onda em volts. raw=True lê a memória completa (mais lento)."""
