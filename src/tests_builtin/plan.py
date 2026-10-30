"""Plano de testes do projeto → instâncias de BuiltinTest configuradas.

    tests = build_plan(project)                 # na hora de executar a suite
    lib   = list_library()                      # testes parametrizáveis disponíveis

Referência de teste: "caminho/arquivo.py:Classe", relativa à raiz do repositório.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tests_builtin.base import BuiltinTest, TestResult, TestStatus
from tests_builtin.loader import PluginLoader

REPO_ROOT = Path(__file__).resolve().parents[2]
LIBRARY_DIR = REPO_ROOT / "TESTES_PLATAFORMA"

_cache: dict[Path, dict[str, type[BuiltinTest]]] = {}


@dataclass(frozen=True)
class LibraryItem:
    ref:         str
    name:        str
    description: str
    cls:         type[BuiltinTest]

    @property
    def category(self) -> str:
        return getattr(self.cls, "category", "") or "Outros"


def make_ref(path: Path | str, cls_name: str) -> str:
    path = Path(path).resolve()
    try:
        rel = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        rel = path.as_posix()
    return f"{rel}:{cls_name}"


def resolve_ref(ref: str, reload: bool = False) -> type[BuiltinTest]:
    """Classe de teste a partir de "arquivo.py:Classe"."""
    file_part, sep, cls_name = ref.rpartition(":")
    if not sep or not file_part:
        raise ValueError(f"Referência inválida '{ref}' (esperado arquivo.py:Classe)")
    path = Path(file_part)
    path = (path if path.is_absolute() else REPO_ROOT / path).resolve()
    if reload or path not in _cache:
        _cache[path] = {c.__name__: c for c in PluginLoader.load_classes(path)}
    try:
        return _cache[path][cls_name]
    except KeyError:
        raise LookupError(f"Classe '{cls_name}' não encontrada em {file_part}") from None


class _BrokenEntry(BuiltinTest):
    """Entrada do plano que não pôde ser carregada: aparece como ERROR na suite."""

    def __init__(self, label: str, error: str) -> None:
        self.name = f"Plano — {label}"
        self._error = error

    def _run(self, pal) -> TestResult:
        return TestResult(self.name, TestStatus.ERROR, self._error)


def build_plan(project) -> list[BuiltinTest]:
    """Instancia as entradas ativas do plano, na ordem, com rótulo e parâmetros."""
    if project is None:
        return []
    tests: list[BuiltinTest] = []
    for entry in project.test_plan:
        if not entry.enabled:
            continue
        try:
            cls = resolve_ref(entry.test)
            test = cls().configure(entry.params, entry.label)
            if entry.repeat > 1:
                from tests_builtin.repeat import RepeatedTest
                test = RepeatedTest(test, entry.repeat)
            tests.append(test)
        except Exception as exc:
            tests.append(_BrokenEntry(entry.label or entry.test,
                                      f"Teste do plano não carregou: {exc}"))
    return tests


def list_library(directory: Path | None = None) -> list[LibraryItem]:
    """Testes com parâmetros declarados nos .py da pasta (TESTES_PLATAFORMA por padrão)."""
    root = directory or LIBRARY_DIR
    items: list[LibraryItem] = []
    for path in sorted(root.rglob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            classes = PluginLoader.load_classes(path)
        except Exception:
            continue
        for cls in classes:
            if cls.params:
                items.append(LibraryItem(make_ref(path, cls.__name__), cls.name,
                                         cls.description, cls))
    return sorted(items, key=lambda i: (i.category, i.name))
