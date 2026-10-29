"""Driver TCP/IP — instrumentos com interface LAN (Ethernet, Wi-Fi)."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

from core.instruments.driver import InstrumentDriver

if TYPE_CHECKING:
    from core.instruments.config import InstrumentConfig

_DEFAULT_PORT    = 5025   # porta SCPI padrão (LXI)
_DEFAULT_TIMEOUT = 5.0


class SocketDriver(InstrumentDriver):
    """Comunica via TCP raw com instrumentos LXI/SCPI-over-LAN.

    O campo ``address`` pode ser:
      - ``"192.168.1.10"``          → usa porta 5025
      - ``"192.168.1.10:5025"``     → porta explícita

    Parâmetros extras (InstrumentConfig.params):
        timeout (float): timeout de socket em segundos (padrão: 5.0)
        port    (int):   porta TCP (padrão: 5025; ignorado se address já inclui porta)
        terminator (str): terminador enviado/lido (padrão: "\\n")
    """

    def __init__(self, config: InstrumentConfig) -> None:
        super().__init__(config)
        self._sock: socket.socket | None = None
        host, port = self._parse_address(config.address, config.params)
        self._host = host
        self._port = port

    @staticmethod
    def _parse_address(address: str, params: dict) -> tuple[str, int]:
        if ":" in address:
            host, port_str = address.rsplit(":", 1)
            return host, int(port_str)
        return address, int(params.get("port", _DEFAULT_PORT))

    def connect(self) -> None:
        timeout = float(self._config.params.get("timeout", _DEFAULT_TIMEOUT))
        self._sock = socket.create_connection((self._host, self._port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._connected = True

    def disconnect(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock      = None
                self._connected = False

    def write(self, cmd: str) -> None:
        assert self._sock is not None, "Instrumento não conectado"
        terminator = self._config.params.get("terminator", "\n")
        self._sock.sendall((cmd + terminator).encode())

    def read(self) -> str:
        assert self._sock is not None, "Instrumento não conectado"
        chunks: list[bytes] = []
        terminator = self._config.params.get("terminator", "\n").encode()
        while True:
            chunk = self._sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if chunk.endswith(terminator):
                break
        return b"".join(chunks).decode(errors="replace").strip()

    def query(self, cmd: str, timeout_ms: int | None = None) -> str:
        if timeout_ms is not None and self._sock is not None:
            old = self._sock.gettimeout()
            self._sock.settimeout(timeout_ms / 1000.0)
        self.write(cmd)
        result = self.read()
        if timeout_ms is not None and self._sock is not None:
            self._sock.settimeout(old)
        return result
