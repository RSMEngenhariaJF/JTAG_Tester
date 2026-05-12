"""Metadata canônica do projeto — fonte única de verdade.

Mantenha este arquivo como a referência para versão, autor, repositório e
qualquer informação que apareça no diálogo "Sobre", no pyproject.toml ou
em logs de identificação.
"""

from __future__ import annotations

import platform as _platform
import subprocess
import sys
from pathlib import Path
from typing import Final

NAME: Final[str] = "Plataforma de Bring-up"
PACKAGE_NAME: Final[str] = "bringup-platform"
VERSION: Final[str] = "0.0.1"
DESCRIPTION: Final[str] = (
    "Aplicação desktop para automação de bring-up de hardware via JTAG."
)

AUTHOR: Final[str] = "Rafael Macedo"
AUTHOR_EMAIL: Final[str] = "rafael.macedoengenharia@gmail.com"

REPOSITORY_URL: Final[str] = "https://github.com/RSMEngenhariaJF/JTAG_Tester"
REPOSITORY_GIT: Final[str] = "https://github.com/RSMEngenhariaJF/JTAG_Tester.git"
ISSUES_URL: Final[str] = "https://github.com/RSMEngenhariaJF/JTAG_Tester/issues"

LICENSE: Final[str] = "Proprietary — a definir"

SPRINT: Final[str] = "Sprint 01 — Bootstrap & Esqueleto GUI"
SPEC_VERSION: Final[str] = "v0.5"

# Raiz do projeto quando rodando de checkout (src layout). Em binários
# empacotados (PyInstaller) este caminho aponta para a pasta extraída,
# que normalmente não conterá pyproject.toml — é assim que `is_dev_mode`
# distingue dev de produção.
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]


def git_commit_short() -> str | None:
    """Retorna o hash curto do commit atual, ou None se não houver Git/repo."""
    try:
        out = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def build_label() -> str:
    """Versão + commit curto quando disponível. Ex.: ``0.0.1+a1b2c3d``."""
    commit = git_commit_short()
    return f"{VERSION}+{commit}" if commit else VERSION


def python_version_str() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def platform_str() -> str:
    return f"{_platform.system()} {_platform.release()} ({_platform.machine()})"


def pyside_versions() -> tuple[str, str]:
    """Retorna ``(pyside_version, qt_version)``. Import lazy para não exigir Qt em CLI."""
    import PySide6
    from PySide6.QtCore import qVersion

    pyside_ver = getattr(PySide6, "__version__", "?")
    qt_ver = qVersion() or "?"
    return pyside_ver, qt_ver
