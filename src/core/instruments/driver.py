"""Classe base para drivers de instrumentos externos."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.instruments.config import InstrumentConfig


class InstrumentDriver(ABC):
    """Interface comum para qualquer instrumento externo.

    Subclasses implementam connect/disconnect e query/write para
    o protocolo específico (VISA, serial, socket, etc.).
    """

    def __init__(self, config: InstrumentConfig) -> None:
        self._config    = config
        self._connected = False

    # ── Identidade ──────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def description(self) -> str:
        return self._config.description

    @property
    def address(self) -> str:
        return self._config.address

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Ciclo de vida ───────────────────────────────────────────────────

    @abstractmethod
    def connect(self) -> None:
        """Abre a conexão com o instrumento."""

    @abstractmethod
    def disconnect(self) -> None:
        """Fecha a conexão com o instrumento."""

    # ── Interface genérica de comunicação ───────────────────────────────

    def query(self, cmd: str, timeout_ms: int | None = None) -> str:
        """Envia um comando e retorna a resposta (string)."""
        raise NotImplementedError(f"{type(self).__name__} não implementa query()")

    def write(self, cmd: str) -> None:
        """Envia um comando sem aguardar resposta."""
        raise NotImplementedError(f"{type(self).__name__} não implementa write()")

    def read(self) -> str:
        """Lê uma resposta sem enviar comando."""
        raise NotImplementedError(f"{type(self).__name__} não implementa read()")

    def query_raw(self, cmd: str, timeout_ms: int | None = None) -> bytes:
        """Envia um comando e retorna a resposta binária completa (ex.: bloco #9...)."""
        raise NotImplementedError(f"{type(self).__name__} não implementa query_raw()")

    def identify(self) -> str:
        """Resposta de *IDN? — usada para rastreabilidade ao conectar."""
        return self.query("*IDN?")

    # ── Context manager ─────────────────────────────────────────────────

    def __enter__(self) -> InstrumentDriver:
        return self

    def __exit__(self, *_) -> None:
        if self._connected:
            self.disconnect()

    def __repr__(self) -> str:
        status = "conectado" if self._connected else "desconectado"
        return f"<{type(self).__name__} name={self.name!r} {status}>"
