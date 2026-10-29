"""PluginLoader — carrega subclasses de BuiltinTest de arquivos Python externos.

Exemplo de plugin:

    # meu_teste.py
    from tests_builtin.base import BuiltinTest, TestResult

    class MeuTeste(BuiltinTest):
        name = "Meu Teste"
        description = "Verifica algo especifico do meu hardware"

        def _run(self, pal) -> TestResult:
            return self._pass("tudo OK")

Uso:

    from tests_builtin.loader import PluginLoader
    tests = PluginLoader.load_from_file(Path("meu_teste.py"))
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests_builtin.base import BuiltinTest


class PluginLoader:
    """Carrega testes customizados de módulos Python externos."""

    @staticmethod
    def load_from_file(path: Path | str) -> list[BuiltinTest]:
        """Importa ``path`` e retorna instâncias de todas as subclasses de BuiltinTest."""
        path = Path(path).resolve()

        if not path.exists():
            raise FileNotFoundError(f"Plugin não encontrado: {path}")
        if path.suffix != ".py":
            raise ValueError(f"Plugin deve ser um arquivo .py: {path}")

        spec = importlib.util.spec_from_file_location(
            f"_bringup_plugin_{path.stem}", path
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Não foi possível carregar: {path}")

        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        tests: list[BuiltinTest] = []
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BuiltinTest)
                and obj is not BuiltinTest
                and not getattr(obj, "__abstractmethods__", None)
            ):
                tests.append(obj())

        return tests

    @staticmethod
    def load_from_dir(
        path: Path | str, pattern: str = "test_*.py"
    ) -> list[BuiltinTest]:
        """Carrega todos os plugins de um diretório cujo nome corresponda a ``pattern``."""
        path = Path(path).resolve()
        tests: list[BuiltinTest] = []
        for file in sorted(path.glob(pattern)):
            tests.extend(PluginLoader.load_from_file(file))
        return tests
