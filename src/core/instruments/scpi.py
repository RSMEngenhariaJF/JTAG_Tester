"""Utilitários SCPI independentes de transporte."""

from __future__ import annotations

INVALID_THRESHOLD: float = 9.9e37   # valor que os instrumentos devolvem para "medida inválida"


def parse_ieee_block(data: bytes) -> bytes:
    """Extrai o conteúdo de um bloco binário IEEE 488.2 de tamanho definido.

    Formato: ``#<n><len com n dígitos><bytes>`` seguido opcionalmente de '\\n'.
    Ex.: ``b"#3005ABCDE\\n"`` → ``b"ABCDE"``.
    """
    start = data.find(b"#")
    if start < 0 or start + 2 > len(data):
        raise ValueError("Resposta não contém bloco IEEE 488.2 ('#' ausente)")
    n = _digits(data[start + 1])
    length = int(data[start + 2:start + 2 + n])
    payload = data[start + 2 + n:start + 2 + n + length]
    if len(payload) != length:
        raise ValueError(f"Bloco IEEE 488.2 incompleto: {len(payload)} de {length} bytes")
    return payload


def block_total_size(header: bytes) -> int | None:
    """Tamanho total (cabeçalho + dados) a partir do início de um bloco; None se incompleto."""
    start = header.find(b"#")
    if start < 0 or len(header) < start + 2:
        return None
    n = _digits(header[start + 1])
    if len(header) < start + 2 + n:
        return None
    return start + 2 + n + int(header[start + 2:start + 2 + n])


def _digits(c: int) -> int:
    """Nº de dígitos do campo de tamanho (1..9). '#0' (tamanho indefinido) não é suportado."""
    if not 0x31 <= c <= 0x39:
        raise ValueError("Bloco IEEE 488.2 de tamanho indefinido (#0) ou malformado")
    return c - 0x30


def to_float(text: str) -> float:
    """Converte resposta numérica SCPI; valores ≥ 9.9e37 (inválido) viram NaN."""
    value = float(text.strip())
    return float("nan") if abs(value) >= INVALID_THRESHOLD else value
