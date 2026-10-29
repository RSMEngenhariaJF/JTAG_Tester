"""Driver serial via pyserial — analisadores, medidores com RS-232/USB-CDC."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.instruments.driver import InstrumentDriver

if TYPE_CHECKING:
    from core.instruments.config import InstrumentConfig


class SerialDriver(InstrumentDriver):
    """Comunica via porta serial (COM/ttyUSB).

    O campo ``address`` deve ser a porta: ``"COM3"`` ou ``"/dev/ttyUSB0"``.

    Parâmetros extras (InstrumentConfig.params):
        baudrate (int):         velocidade (padrão: 9600)
        timeout  (float):       timeout de leitura em segundos (padrão: 1.0)
        terminator (str):       terminador de linha enviado (padrão: "\\r\\n")
        read_terminator (str):  terminador esperado na resposta (padrão: "\\n")
    """

    def __init__(self, config: InstrumentConfig) -> None:
        super().__init__(config)
        self._serial = None

    def connect(self) -> None:
        try:
            import serial  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "pyserial não instalado — execute: pip install pyserial"
            ) from exc
        p = self._config.params
        self._serial = serial.Serial(
            port     = self._config.address,
            baudrate = p.get("baudrate", 9600),
            bytesize = p.get("bytesize", 8),
            parity   = p.get("parity",   "N"),
            stopbits = p.get("stopbits", 1),
            timeout  = p.get("timeout",  1.0),
        )
        self._connected = True

    def disconnect(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial    = None
                self._connected = False

    def write(self, cmd: str) -> None:
        assert self._serial is not None, "Instrumento não conectado"
        terminator = self._config.params.get("terminator", "\r\n")
        self._serial.write((cmd + terminator).encode())

    def read(self) -> str:
        assert self._serial is not None, "Instrumento não conectado"
        return self._serial.readline().decode(errors="replace").strip()

    def query(self, cmd: str, timeout_ms: int | None = None) -> str:
        if timeout_ms is not None:
            old = self._serial.timeout
            self._serial.timeout = timeout_ms / 1000.0
        self.write(cmd)
        result = self.read()
        if timeout_ms is not None:
            self._serial.timeout = old
        return result
