"""Mapa de funções alternativas (AF) por dispositivo: pino + sinal → número da AF.

Subcamada de dados entre os blocos e o chip: a AF de um sinal depende do pino
(ex.: UART7_RX é AF7 em PE7 e AF11 em PA8), então não cabe numa regra por
família. O mapa fica em devices/<chip>/af.json, gerado do banco do CubeMX
instalado na máquina (tools/gerar_af.py), no formato::

    {"mcu": "STM32H753ZITx", "pins": {"PE7": {"UART7_RX": 7, ...}, ...}}

Ordem de resolução (hal.common.pin_af): AF informada no Pinout → este mapa →
tabela por família (último recurso).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DEVICES_DIR = Path(__file__).parents[2] / "devices"


@lru_cache(maxsize=8)
def load(device_name: str) -> dict[str, dict[str, int]]:
    """Mapa do dispositivo (nome do SVD, ex. "STM32H753"); {} se não houver af.json."""
    path = DEVICES_DIR / device_name.lower() / "af.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("pins", {})


def lookup(device_name: str, port: str, pin: int, signal: str) -> int | None:
    """AF de `signal` (ex. "UART7_RX") no pino `port`/`pin` (ex. "GPIOE", 7)."""
    pin_name = f"P{port.upper().removeprefix('GPIO')}{pin}"
    return load(device_name).get(pin_name, {}).get(signal.upper())
