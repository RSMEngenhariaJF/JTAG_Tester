"""Registry de macros de teste de hardware.

Macros são funções Python reutilizáveis que encapsulam sequências de
operações de hardware. Podem ser carregadas de arquivos externos e
chamadas de qualquer teste.

Assinatura padrão de uma macro::

    def nome_da_macro(pal: PeripheralAccessLayer, **kwargs) -> Any:
        ...

Registro via decorador::

    from core.macros import macro

    @macro                                    # registro simples
    def reset_board(pal, *, hold_ms=100):
        "Pulsa o pino de reset."
        ...

    @macro(name="uart_ber", category="UART")  # com metadados
    def run_uart_ber(pal, *, n_bytes=1024):
        "BER loopback USART2."
        ...

Uso em testes::

    from core.macros import get_macro

    reset = get_macro("reset_board")
    reset(pal, hold_ms=50)

    ms = get_macro("uart_ber")(pal, n_bytes=4096)
    if not ms.all_within_limits():
        return self._fail("BER fora do limite", measurements=ms)
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("core.macros")

_MACROS_DIR = Path(__file__).parents[3] / "macros"


# ── MacroParam — parâmetro inspecionado ───────────────────────────────────────

@dataclass
class MacroParam:
    name:         str
    default:      Any  = inspect.Parameter.empty
    annotation:   str  = ""
    keyword_only: bool = False

    @property
    def has_default(self) -> bool:
        return self.default is not inspect.Parameter.empty

    def signature_str(self) -> str:
        s = self.name
        if self.annotation:
            s += f": {self.annotation}"
        if self.has_default:
            s += f" = {self.default!r}"
        return s


# ── MacroEntry — macro registrada ─────────────────────────────────────────────

@dataclass
class MacroEntry:
    """Uma macro registrada no registry."""

    name:        str
    fn:          Callable[..., Any]
    description: str              = ""
    category:    str              = "Geral"
    source_file: str              = ""
    params:      list[MacroParam] = field(default_factory=list)

    def __call__(self, pal, **kwargs) -> Any:
        return self.fn(pal, **kwargs)

    def signature_str(self) -> str:
        """Assinatura legível para exibição na GUI."""
        parts = [p.signature_str() for p in self.params]
        return f"({', '.join(parts)})" if parts else "()"

    def tooltip(self) -> str:
        lines = [f"{self.name}{self.signature_str()}"]
        if self.description:
            lines.append(self.description)
        if self.source_file:
            lines.append(f"Origem: {Path(self.source_file).name}")
        return "\n".join(lines)


def _inspect_params(fn: Callable) -> list[MacroParam]:
    """Extrai os parâmetros de uma macro (excluindo 'pal')."""
    params: list[MacroParam] = []
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return params

    for pname, param in sig.parameters.items():
        if pname in ("pal", "self", "cls"):
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        ann = ""
        if param.annotation is not inspect.Parameter.empty:
            ann = getattr(param.annotation, "__name__", str(param.annotation))

        params.append(MacroParam(
            name         = pname,
            default      = param.default,
            annotation   = ann,
            keyword_only = param.kind == inspect.Parameter.KEYWORD_ONLY,
        ))

    return params


# ── MacroRegistry — singleton ─────────────────────────────────────────────────

class MacroRegistry:
    """Registro global de macros. Singleton."""

    _instance: MacroRegistry | None = None

    def __new__(cls) -> MacroRegistry:
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._entries: dict[str, MacroEntry] = {}
            cls._instance = inst
        return cls._instance

    @classmethod
    def instance(cls) -> MacroRegistry:
        return cls()

    # ── Registro ──────────────────────────────────────────────────────────────

    def register(self, entry: MacroEntry) -> None:
        if entry.name in self._entries:
            logger.warning("Macro '%s' redefinida (origem: %s)", entry.name, entry.source_file)
        self._entries[entry.name] = entry
        logger.debug("Macro registrada: %s  [%s]", entry.name, entry.category)

    # ── Acesso ────────────────────────────────────────────────────────────────

    def get(self, name: str) -> MacroEntry | None:
        return self._entries.get(name)

    def all_entries(self) -> list[MacroEntry]:
        return sorted(self._entries.values(), key=lambda e: (e.category, e.name))

    def categories(self) -> list[str]:
        return sorted({e.category for e in self._entries.values()})

    def by_category(self, category: str) -> list[MacroEntry]:
        return [e for e in self.all_entries() if e.category == category]

    def names(self) -> list[str]:
        return sorted(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    # ── Carregamento de arquivos ───────────────────────────────────────────────

    def load_file(self, path: Path | str) -> list[MacroEntry]:
        """Carrega macros de um arquivo Python.

        Retorna a lista de MacroEntry registradas pelo arquivo.

        O arquivo deve usar o decorador ``@macro`` para registrar funções::

            from core.macros import macro

            @macro(category="GPIO")
            def reset_board(pal, *, hold_ms=100):
                "Pulsa o pino de reset."
                ...
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Arquivo de macro não encontrado: {path}")

        before = set(self._entries.keys())

        module_name = f"_macro_{path.stem}_{id(path)}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Não foi possível carregar: {path}")

        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except Exception as exc:
            raise RuntimeError(f"Erro ao executar '{path.name}': {exc}") from exc

        after = set(self._entries.keys())
        new_names = after - before

        # Atualiza source_file nas novas entradas
        new_entries: list[MacroEntry] = []
        for name in new_names:
            entry = self._entries[name]
            entry.source_file = str(path)
            new_entries.append(entry)

        logger.info("Arquivo '%s' carregado: %d macro(s)", path.name, len(new_entries))
        return new_entries

    def load_directory(self, directory: Path | str = _MACROS_DIR) -> int:
        """Carrega todos os arquivos *.py de um diretório.

        Retorna o número total de macros carregadas.
        """
        directory = Path(directory)
        if not directory.exists():
            return 0

        total = 0
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                entries = self.load_file(py_file)
                total += len(entries)
            except Exception as exc:
                logger.warning("Falha ao carregar '%s': %s", py_file.name, exc)

        return total

    def reset(self) -> None:
        """Remove todas as macros registradas (útil em testes unitários)."""
        self._entries.clear()


# ── Singleton global ───────────────────────────────────────────────────────────

_registry = MacroRegistry.instance()


# ── Decorador @macro ──────────────────────────────────────────────────────────

def macro(
    _fn: Callable | None = None,
    *,
    name:        str = "",
    description: str = "",
    category:    str = "Geral",
) -> Callable:
    """Decorador que registra uma função como macro reutilizável.

    Uso simples::

        @macro
        def reset_board(pal, *, hold_ms=100):
            "Pulsa o pino de reset por hold_ms milissegundos."
            ...

    Com metadados::

        @macro(name="uart_ber", category="UART", description="BER loopback")
        def run_ber_test(pal, *, n_bytes=1024):
            ...
    """
    def _decorator(fn: Callable) -> Callable:
        entry = MacroEntry(
            name        = name or fn.__name__,
            fn          = fn,
            description = description or (fn.__doc__ or "").strip().splitlines()[0] if (fn.__doc__ or "").strip() else "",
            category    = category,
            params      = _inspect_params(fn),
        )
        _registry.register(entry)
        fn._macro_entry = entry  # type: ignore[attr-defined]
        return fn

    if _fn is not None:
        # @macro  (sem parênteses)
        return _decorator(_fn)
    # @macro(...)  (com parênteses)
    return _decorator


# ── API pública ───────────────────────────────────────────────────────────────

def get_macro(name: str) -> MacroEntry:
    """Retorna a macro pelo nome. Levanta KeyError se não encontrada.

    Uso::

        reset = get_macro("reset_board")
        reset(pal, hold_ms=50)
    """
    entry = _registry.get(name)
    if entry is None:
        available = ", ".join(_registry.names()) or "(nenhuma)"
        raise KeyError(
            f"Macro '{name}' não encontrada. "
            f"Disponíveis: {available}"
        )
    return entry


def load_macros(path: Path | str) -> list[MacroEntry]:
    """Atalho: carrega macros de um arquivo ou diretório."""
    p = Path(path)
    if p.is_dir():
        _registry.load_directory(p)
        return _registry.all_entries()
    return _registry.load_file(p)
