"""Driver VISA via PyVISA — multímetros, osciloscópios, fontes SCPI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.instruments.driver import InstrumentDriver

if TYPE_CHECKING:
    from core.instruments.config import InstrumentConfig


class VisaDriver(InstrumentDriver):
    """Comunica com qualquer instrumento SCPI via PyVISA.

    Parâmetros extras (InstrumentConfig.params):
        timeout_ms (int):  tempo limite de leitura (padrão: 5000)
        read_termination (str): terminador de leitura (padrão: "\\n")
    """

    def __init__(self, config: InstrumentConfig) -> None:
        super().__init__(config)
        self._resource = None

    def connect(self) -> None:
        try:
            import pyvisa  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "PyVISA não instalado — execute: pip install pyvisa pyvisa-py"
            ) from exc
        rm = pyvisa.ResourceManager()
        timeout_ms        = self._config.params.get("timeout_ms", 5000)
        read_termination  = self._config.params.get("read_termination", "\n")
        res = rm.open_resource(self._config.address)
        res.timeout           = timeout_ms
        res.read_termination  = read_termination
        self._resource   = res
        self._connected  = True

    def disconnect(self) -> None:
        if self._resource is not None:
            try:
                self._resource.close()
            finally:
                self._resource  = None
                self._connected = False

    def query(self, cmd: str, timeout_ms: int | None = None) -> str:
        assert self._resource is not None, "Instrumento não conectado"
        old = self._resource.timeout
        if timeout_ms is not None:
            self._resource.timeout = timeout_ms
        try:
            return self._resource.query(cmd).strip()
        finally:
            self._resource.timeout = old

    def write(self, cmd: str) -> None:
        assert self._resource is not None, "Instrumento não conectado"
        self._resource.write(cmd)

    def read(self) -> str:
        assert self._resource is not None, "Instrumento não conectado"
        return self._resource.read().strip()
