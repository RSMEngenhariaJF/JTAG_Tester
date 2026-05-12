"""Configuração de logging da aplicação.

Em **modo de desenvolvimento** (executando de checkout local), grava logs em
``privada/logs/bringup_YYYYMMDD_HHMMSS.log`` para debug/depuração. Em produção
(binário instalado, sem ``pyproject.toml``) apenas console.

Detecção de modo de desenvolvimento (ordem de prioridade):

1. ``BRINGUP_DEV=1`` (ou ``true`` / ``yes``) → força dev;
2. ``BRINGUP_DEV=0`` (ou ``false`` / ``no``) → força produção;
3. Heurística automática: ``pyproject.toml`` presente na raiz → dev.

A pasta ``privada/`` inteira está fora do versionamento Git (ver ``.gitignore``),
portanto nenhum log gerado por essa configuração sobe para o repositório.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from app._metadata import PROJECT_ROOT

LOG_DIR_NAME = "logs"
PRIVADA_DIR = PROJECT_ROOT / "privada"
DEV_LOG_DIR = PRIVADA_DIR / LOG_DIR_NAME

# Quantos arquivos de log manter; mais antigos são apagados a cada inicialização.
MAX_LOG_FILES = 30

_FILE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_CONSOLE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"


def is_dev_mode() -> bool:
    """True se a aplicação está rodando em modo de desenvolvimento."""
    env = os.environ.get("BRINGUP_DEV", "").strip().lower()
    if env in {"1", "true", "yes"}:
        return True
    if env in {"0", "false", "no"}:
        return False
    return (PROJECT_ROOT / "pyproject.toml").exists()


def _prune_old_logs(directory: Path, keep: int = MAX_LOG_FILES) -> None:
    files = sorted(directory.glob("bringup_*.log"), key=lambda p: p.stat().st_mtime)
    excess = len(files) - keep
    if excess <= 0:
        return
    for old in files[:excess]:
        try:
            old.unlink()
        except OSError:
            pass


def setup_logging(level: int = logging.INFO) -> Path | None:
    """Configura logging global. Retorna o path do log file ou None em prod."""
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt="%H:%M:%S"))
    console.setLevel(level)
    root.addHandler(console)

    if not is_dev_mode():
        return None

    DEV_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    log_path = DEV_LOG_DIR / f"bringup_{timestamp}.log"

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.setLevel(logging.DEBUG)

    _prune_old_logs(DEV_LOG_DIR)
    return log_path
