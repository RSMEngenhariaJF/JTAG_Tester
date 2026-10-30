"""Captura de dados de auditoria durante a execução de um teste.

    LogCapture     — registros de log emitidos pela thread do teste enquanto ele roda
    code_identity  — classe, arquivo e SHA-256 do código do teste (qual versão rodou)
    trace_rows     — passos de um teste composto: aplicado → observado, com instante
    compact        — valor curto e legível para tabelas (dict, float, bytes...)

O resultado vai para TestResult.details e os relatórios o mostram em
"Registro de execução por teste" (core.analysis.audit).
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import inspect
import logging
import threading
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_LOG_LINES = 300
MAX_STEPS = 300
MAX_CELL = 240


class LogCapture(logging.Handler):
    """Guarda os logs da thread atual entre start() e stop()."""

    def __init__(self, level: int = logging.DEBUG) -> None:
        super().__init__(level)
        self.lines: list[str] = []
        self._thread = threading.get_ident()
        self._dropped = 0

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self._thread:
            return
        if len(self.lines) >= MAX_LOG_LINES:
            self._dropped += 1
            return
        t = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
        try:
            msg = record.getMessage()
        except Exception:                       # formato quebrado não derruba o teste
            msg = str(record.msg)
        self.lines.append(f"{t} {record.levelname:<7} {record.name}: {msg}")

    def start(self) -> None:
        self._thread = threading.get_ident()
        root = logging.getLogger()
        # Registros INFO das camadas de HAL entram no registro mesmo que o logging
        # não tenha sido configurado (raiz em WARNING); o nível volta no stop().
        self._root_level = root.level
        if root.level == logging.NOTSET or root.level > logging.INFO:
            root.setLevel(logging.INFO)
        root.addHandler(self)

    def stop(self) -> None:
        root = logging.getLogger()
        root.removeHandler(self)
        root.setLevel(self._root_level)
        if self._dropped:
            self.lines.append(f"... {self._dropped} linha(s) de log omitida(s)")


@functools.lru_cache(maxsize=256)
def code_identity(cls: type) -> dict:
    """{"classe": "piscar_led.PiscarLed", "arquivo": "TESTES_PLATAFORMA/IO/...", "sha256": ...}."""
    out = {"classe": f"{cls.__module__}.{cls.__qualname__}"}
    try:
        path = Path(inspect.getfile(cls)).resolve()
    except (TypeError, OSError):
        return out
    try:
        out["arquivo"] = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        out["arquivo"] = path.name
    with contextlib.suppress(OSError):
        out["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return out


def compact(value, limit: int = MAX_CELL) -> str:
    """Texto curto: floats com 6 algarismos, dicts como chave=valor."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, dict):
        text = ", ".join(f"{k}={compact(v, 40)}" for k, v in value.items()
                         if not isinstance(v, (list, dict)))
    elif isinstance(value, (list, tuple)):
        text = "[" + ", ".join(compact(v, 40) for v in value[:16]) + \
            (", ..." if len(value) > 16 else "") + "]"
    else:
        text = str(value)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def trace_rows(trace) -> list[list[str]]:
    """# | passo | t (ms) | aplicado | observado — um por Observation (até MAX_STEPS)."""
    rows = []
    for o in trace.observations[:MAX_STEPS]:
        rows.append([str(o.index), o.label, f"{o.t_s * 1000:.1f}",
                     "; ".join(f"{k}: {compact(v, 80)}" for k, v in o.driven.items()) or "—",
                     "; ".join(f"{k}: {compact(v, 120)}" for k, v in o.observed.items()) or "—"])
    if len(trace.observations) > MAX_STEPS:
        rows.append(["...", f"{len(trace.observations) - MAX_STEPS} passo(s) omitido(s)",
                     "", "", ""])
    return rows
