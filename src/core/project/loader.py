"""Carrega e salva ProjectConfigs em arquivos JSON."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from core.project.config import ProjectConfig

logger = logging.getLogger("core.project.loader")

# Diretório-padrão: <raiz_do_projeto>/projects/  (absoluto, independente do CWD)
_PROJECTS_DIR = Path(__file__).parents[3] / "projects"


def find_projects(directory: Path = _PROJECTS_DIR) -> list[ProjectConfig]:
    """Varre *directory* em busca de arquivos .json de projeto.

    Cria o diretório se não existir (primeira execução).
    """
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
        logger.info("Diretório de projetos criado: %s", directory)
        return []

    projects: list[ProjectConfig] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            projects.append(ProjectConfig.from_dict(data))
            logger.debug("Projeto carregado: %s", path.name)
        except Exception as exc:
            logger.warning("Erro ao carregar projeto '%s': %s", path.name, exc)
    return projects


def save_project(
    project: ProjectConfig,
    directory: Path = _PROJECTS_DIR,
    filename: str | None = None,
) -> Path:
    """Salva *project* como JSON. Retorna o caminho do arquivo gerado."""
    directory.mkdir(parents=True, exist_ok=True)

    if filename is None:
        safe = re.sub(r"[^\w\-]", "_", project.name.lower())
        filename = f"{safe}.json"

    path = directory / filename
    path.write_text(
        json.dumps(project.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Projeto salvo: %s", path)
    return path
