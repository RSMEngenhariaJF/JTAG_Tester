"""Macros de teste de hardware — funções reutilizáveis entre projetos.

Uso rápido::

    # Em um arquivo de macro (ex: macros/gpio_utils.py):
    from core.macros import macro

    @macro(category="GPIO")
    def reset_board(pal, *, hold_ms=100):
        "Pulsa o pino de reset."
        ...

    # Em um teste:
    from core.macros import get_macro

    get_macro("reset_board")(pal, hold_ms=50)

    # Ou com tipagem explícita:
    reset = get_macro("reset_board")
    reset(pal)
"""

from core.macros.registry import (
    MacroEntry,
    MacroParam,
    MacroRegistry,
    get_macro,
    load_macros,
    macro,
)

__all__ = [
    "macro",
    "get_macro",
    "load_macros",
    "MacroEntry",
    "MacroParam",
    "MacroRegistry",
]
