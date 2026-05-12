"""Script de conveniência para rodar a GUI sem precisar instalar via pip.

Uso (a partir da raiz do projeto):

    python run.py

Pré-requisito: PySide6 instalado no Python ativo.
    pip install PySide6

Para o ambiente completo (com o comando 'bringup-gui', testes e lint), prefira:
    pip install -e ".[dev]"
"""

from __future__ import annotations

import sys
from pathlib import Path

# Adiciona src/ ao sys.path para que o pacote `app` seja importável
# sem precisar instalar o projeto.
_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
