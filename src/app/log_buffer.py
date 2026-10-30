"""Coletor de logs em memória — base da janela de logs e da exportação para análise.

Todo registro do ``logging`` (e as exceções não tratadas, inclusive de threads)
vai para um buffer circular. A GUI assina as novidades; a exportação gera texto
(.log) ou JSON Lines (.jsonl), um objeto por linha com campos separados — formato
pensado para análise automática (scripts, ferramentas de IA aprovadas pelo Instituto).

Na exportação, o caminho da pasta do usuário (que contém o nome da pessoa) é
substituído por "~" — dado pessoal fora do necessário (LGPD).
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import sys
import threading
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

MAX_RECORDS = 5000
LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


@dataclass
class LogEntry:
    """Um registro de log com os campos separados (não só a linha formatada)."""

    timestamp: str          # ISO 8601 com fuso
    level:     str          # "ERROR"
    logger:    str          # "app.services.device"
    message:   str
    exception: str = ""     # traceback completo, se houver
    thread:    str = ""
    module:    str = ""
    line:      int = 0
    extra:     dict = field(default_factory=dict)

    @property
    def levelno(self) -> int:
        return LEVELS.get(self.level, 0)

    def text(self) -> str:
        t = f"{self.timestamp} | {self.level:<8} | {self.logger} | {self.message}"
        return t + ("\n" + self.exception if self.exception else "")


class LogBuffer(logging.Handler):
    """Handler de logging que guarda os últimos ``MAX_RECORDS`` registros."""

    def __init__(self, maxlen: int = MAX_RECORDS) -> None:
        super().__init__(level=logging.DEBUG)
        self._records: deque[LogEntry] = deque(maxlen=maxlen)
        self._lock_buf = threading.Lock()
        self._listeners: list[Callable[[LogEntry | None], None]] = []

    # ── logging.Handler ───────────────────────────────────────────────────

    def emit(self, record: logging.LogRecord) -> None:
        try:
            exc = ""
            if record.exc_info:
                exc = "".join(traceback.format_exception(*record.exc_info)).rstrip()
            entry = LogEntry(
                timestamp=datetime.fromtimestamp(record.created).astimezone().isoformat(
                    timespec="milliseconds"),
                level=record.levelname,
                logger=record.name,
                message=record.getMessage(),
                exception=exc,
                thread=record.threadName or "",
                module=record.module,
                line=record.lineno,
            )
        except Exception:
            self.handleError(record)
            return
        with self._lock_buf:
            self._records.append(entry)
        self._notify(entry)

    # ── Assinatura (a GUI repassa para a thread de interface) ─────────────

    def add_listener(self, fn: Callable[[LogEntry | None], None]) -> None:
        """fn(entry) a cada registro; fn(None) quando o buffer é limpo."""
        self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[LogEntry | None], None]) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _notify(self, entry: LogEntry | None) -> None:
        for fn in list(self._listeners):
            with contextlib.suppress(Exception):   # listener com defeito não derruba o log
                fn(entry)

    # ── Consulta e manutenção ─────────────────────────────────────────────

    def records(self, min_level: str = "DEBUG") -> list[LogEntry]:
        floor = LEVELS.get(min_level, 0)
        with self._lock_buf:
            return [e for e in self._records if e.levelno >= floor]

    def count(self, min_level: str = "ERROR") -> int:
        return len(self.records(min_level))

    def clear(self) -> None:
        with self._lock_buf:
            self._records.clear()
        self._notify(None)

    # ── Exportação ────────────────────────────────────────────────────────

    def export_text(self, entries: list[LogEntry] | None = None,
                    context: dict | None = None) -> str:
        entries = self.records() if entries is None else entries
        head = [f"# {k}: {v}" for k, v in (context or {}).items()]
        return _redact("\n".join(head + [e.text() for e in entries]) + "\n")

    def export_jsonl(self, entries: list[LogEntry] | None = None,
                     context: dict | None = None) -> str:
        """1ª linha: {"type": "session", ...contexto}; depois {"type": "log", ...}."""
        entries = self.records() if entries is None else entries
        lines = [json.dumps({"type": "session",
                             "exported_at": datetime.now().astimezone().isoformat(
                                 timespec="seconds"),
                             **(context or {})}, ensure_ascii=False)]
        lines += [json.dumps({"type": "log", **asdict(e)}, ensure_ascii=False)
                  for e in entries]
        return _redact("\n".join(lines) + "\n")

    def save(self, path: Path | str, entries: list[LogEntry] | None = None,
             context: dict | None = None) -> Path:
        path = Path(path)
        data = (self.export_jsonl(entries, context) if path.suffix.lower() == ".jsonl"
                else self.export_text(entries, context))
        path.write_text(data, encoding="utf-8")
        return path


_USER_DIR = re.compile(r"[A-Za-z]:(?:\\{1,2}|/)Users(?:\\{1,2}|/)[^\\/\s\"':]+", re.IGNORECASE)


def _redact(text: str) -> str:
    """Troca a pasta do usuário por "~": o caminho real, o nome curto 8.3 e /home/<nome>."""
    home = str(Path.home())
    for variant in {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}:
        text = text.replace(variant, "~")
    text = _USER_DIR.sub("~", text)
    return re.sub(r"/home/[^/\s\"':]+", "~", text)


# ── Instância global ──────────────────────────────────────────────────────────

_buffer: LogBuffer | None = None


def get_log_buffer() -> LogBuffer:
    global _buffer
    if _buffer is None:
        _buffer = LogBuffer()
    return _buffer


def install(root: logging.Logger | None = None) -> LogBuffer:
    """Liga o buffer ao logger raiz e registra exceções não tratadas (idempotente)."""
    buf = get_log_buffer()
    root = root or logging.getLogger()
    if buf not in root.handlers:
        root.addHandler(buf)

    log = logging.getLogger("app.excecao")

    def _sys_hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Exceção não tratada: %s", exc, exc_info=(exc_type, exc, tb))

    def _thread_hook(args):
        log.critical("Exceção não tratada na thread %s: %s",
                     getattr(args.thread, "name", "?"), args.exc_value,
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook
    return buf
