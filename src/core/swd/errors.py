"""Exceções do protocolo SWD."""

from __future__ import annotations


class SWDError(Exception):
    """Base para todos os erros SWD."""


class AckError(SWDError):
    """Target retornou ACK WAIT ou FAULT."""

    def __init__(self, ack: int) -> None:
        names = {0b001: "OK", 0b010: "WAIT", 0b100: "FAULT"}
        name = names.get(ack, f"0b{ack:03b}")
        super().__init__(f"SWD ACK inesperado: {name}")
        self.ack = ack


class ParityError(SWDError):
    """Paridade dos dados recebidos não confere."""

    def __init__(self, data: int, received: int, expected: int) -> None:
        super().__init__(
            f"Paridade inválida para 0x{data:08X}: recebida={received}, esperada={expected}"
        )
        self.data = data
        self.received_parity = received
        self.expected_parity = expected
