"""BoardLoader — descobre configurações de placa em src/boards/*.py.

Cada arquivo em src/boards/ deve expor uma variável chamada ``BOARD``
do tipo ``BoardConfig``. O loader importa cada arquivo dinamicamente e
coleta todos os BOARDs encontrados.

Uso::

    from core.board.loader import find_boards
    boards = find_boards()          # escaneia src/boards/ automaticamente
    for b in boards:
        print(b.project_code, b.name)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from core.board.config import BoardConfig

# Diretório-padrão: src/boards/  (relativo a este arquivo em src/core/board/)
_DEFAULT_BOARDS_DIR = Path(__file__).parents[2] / "boards"


def find_boards(boards_dir: Path | str | None = None) -> list[BoardConfig]:
    """Varre ``boards_dir`` em busca de arquivos .py que exponham ``BOARD``.

    Parâmetros
    ----------
    boards_dir : diretório a varrer; None → usa ``src/boards/``

    Retorna
    -------
    Lista de BoardConfig em ordem alfabética de arquivo.
    Arquivos com erros de importação são silenciosamente ignorados.
    """
    root = Path(boards_dir) if boards_dir else _DEFAULT_BOARDS_DIR
    boards: list[BoardConfig] = []

    for path in sorted(root.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"_board_{path.stem}", path
            )
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            cfg = getattr(module, "BOARD", None)
            if isinstance(cfg, BoardConfig):
                boards.append(cfg)
        except Exception:
            pass

    return boards
