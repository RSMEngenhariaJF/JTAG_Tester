"""TargetAgent — carrega e executa um stub na RAM do alvo e lê sua fila de resultados.

O SWD fica fora do caminho crítico: o host só prepara (carga do stub, caixa de
correio) e coleta (fila circular na RAM). O stub roda na velocidade do núcleo.

Protocolo da fila (escrita pelo stub, esvaziada pelo host)::

    head  — índice livre-corrente, incrementado pelo stub após gravar um registro
    tail  — índice livre-corrente, incrementado pelo host após ler
    slot  = índice % size;  cheia quando head - tail == size
"""

from __future__ import annotations

import time
from typing import Protocol

# Índices de registrador de núcleo (ARM DCRSR)
REG_SP:   int = 13
REG_PC:   int = 15
REG_XPSR: int = 16
_XPSR_THUMB: int = 1 << 24


class IAgentTarget(Protocol):
    """Operações de depuração que o agente precisa (StLinkADIv5 atende)."""

    def read_mem32(self, addr: int) -> int: ...
    def write_mem32(self, addr: int, value: int) -> None: ...
    def read_block32(self, addr: int, count: int) -> list[int]: ...
    def write_block32(self, addr: int, words: list[int]) -> None: ...
    def halt(self) -> None: ...
    def resume(self) -> None: ...
    def is_halted(self) -> bool: ...
    def write_core_register(self, reg: int, value: int) -> None: ...


def bytes_to_words(data: bytes) -> list[int]:
    """Converte bytes em palavras little-endian (completa com zeros até múltiplo de 4)."""
    data = data + b"\x00" * (-len(data) % 4)
    return [int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data), 4)]


def words_to_bytes(words: list[int]) -> bytes:
    return b"".join(w.to_bytes(4, "little") for w in words)


class TargetAgent:
    """Carrega um binário na RAM do alvo e o executa a partir do núcleo parado."""

    def __init__(self, target: IAgentTarget) -> None:
        self._t = target

    def load(self, image: bytes, addr: int) -> None:
        """Grava `image` em `addr` e confere a leitura de volta."""
        words = bytes_to_words(image)
        self._t.write_block32(addr, words)
        if self._t.read_block32(addr, len(words)) != words:
            raise RuntimeError(f"Verificação do stub em 0x{addr:08X} falhou (RAM não gravou)")

    def start(self, entry: int, sp: int) -> None:
        """Aponta PC/SP para o stub (modo Thumb) e libera o núcleo."""
        if not self._t.is_halted():
            self._t.halt()
        self._t.write_core_register(REG_SP, sp)
        self._t.write_core_register(REG_PC, entry & ~1)
        self._t.write_core_register(REG_XPSR, _XPSR_THUMB)
        self._t.resume()

    def wait_halt(self, timeout_s: float, poll_s: float = 0.02) -> bool:
        """Espera o stub terminar (BKPT). Retorna False em timeout."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._t.is_halted():
                return True
            time.sleep(poll_s)
        return self._t.is_halted()


class RingReader:
    """Esvazia uma fila circular de registros de tamanho fixo na RAM do alvo."""

    def __init__(
        self,
        target: IAgentTarget,
        head_addr: int,
        tail_addr: int,
        data_addr: int,
        size: int,
        rec_words: int,
    ) -> None:
        self._t = target
        self._head = head_addr
        self._tail = tail_addr
        self._data = data_addr
        self._size = size
        self._rec = rec_words

    def drain(self) -> list[list[int]]:
        """Lê todos os registros pendentes e libera o espaço para o stub."""
        head = self._t.read_mem32(self._head)
        tail = self._t.read_mem32(self._tail)
        pending = (head - tail) & 0xFFFFFFFF
        if pending > self._size:
            raise RuntimeError(f"Fila corrompida: head={head} tail={tail} size={self._size}")
        out: list[list[int]] = []
        for i in range(pending):
            slot = (tail + i) % self._size
            out.append(self._t.read_block32(self._data + slot * self._rec * 4, self._rec))
        if pending:
            self._t.write_mem32(self._tail, (tail + pending) & 0xFFFFFFFF)
        return out
