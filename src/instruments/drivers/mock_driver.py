"""Driver simulado para uso em pytest — sem hardware real necessário."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.instruments.driver import InstrumentDriver

if TYPE_CHECKING:
    from core.instruments.config import InstrumentConfig


class MockDriver(InstrumentDriver):
    """Instrumento falso configurável para testes unitários.

    Use ``responses`` em ``InstrumentConfig.params`` para mapear
    comandos a respostas:

        params={"responses": {"MEAS:VOLT:DC?": "3.300", "*IDN?": "MOCK,1.0"}}

    Qualquer comando não mapeado retorna ``"0.000"``.
    Todos os comandos/respostas enviados ficam em ``driver.log``.
    """

    def __init__(self, config: InstrumentConfig) -> None:
        super().__init__(config)
        self._responses: dict[str, str] = config.params.get("responses", {})
        self.log: list[tuple[str, str]] = []   # [(cmd, response), ...]

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def write(self, cmd: str) -> None:
        self.log.append((cmd, ""))

    def read(self) -> str:
        return "0.000"

    def query(self, cmd: str, timeout_ms: int | None = None) -> str:
        response = self._responses.get(cmd, "0.000")
        self.log.append((cmd, response))
        return response

    def set_response(self, cmd: str, response: str) -> None:
        """Configura resposta para um comando específico em tempo de teste."""
        self._responses[cmd] = response

    def clear_log(self) -> None:
        self.log.clear()
