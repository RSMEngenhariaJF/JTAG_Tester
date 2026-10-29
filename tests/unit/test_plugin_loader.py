"""Testes unitários do PluginLoader.

Cria arquivos Python temporários para testar o carregamento de plugins.

Execucao:
    pytest tests/unit/test_plugin_loader.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests_builtin.base import BuiltinTest, TestResult, TestStatus
from tests_builtin.loader import PluginLoader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_plugin(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


# ===========================================================================
# Erros de entrada
# ===========================================================================


class TestPluginLoaderErrors:
    def test_nonexistent_file_raises(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            PluginLoader.load_from_file(tmp_path / "nao_existe.py")

    def test_non_py_extension_raises(self, tmp_path) -> None:
        p = tmp_path / "plugin.txt"
        p.write_text("")
        with pytest.raises(ValueError, match=r"\.py"):
            PluginLoader.load_from_file(p)


# ===========================================================================
# Carregamento basico
# ===========================================================================


class TestPluginLoaderLoad:
    def test_empty_file_returns_empty_list(self, tmp_path) -> None:
        p = write_plugin(tmp_path, "empty.py", "")
        result = PluginLoader.load_from_file(p)
        assert result == []

    def test_file_without_builtin_test_returns_empty(self, tmp_path) -> None:
        p = write_plugin(tmp_path, "no_test.py", "x = 42\nclass Foo: pass\n")
        assert PluginLoader.load_from_file(p) == []

    def test_finds_single_builtin_subclass(self, tmp_path) -> None:
        p = write_plugin(tmp_path, "plugin_a.py", """
from tests_builtin.base import BuiltinTest, TestResult, TestStatus

class MeuTeste(BuiltinTest):
    name = "Meu Teste"
    description = "Exemplo"
    def _run(self, pal):
        return TestResult(self.name, TestStatus.PASS, "ok")
""")
        tests = PluginLoader.load_from_file(p)
        assert len(tests) == 1
        assert isinstance(tests[0], BuiltinTest)
        assert tests[0].name == "Meu Teste"

    def test_finds_multiple_subclasses(self, tmp_path) -> None:
        p = write_plugin(tmp_path, "plugin_multi.py", """
from tests_builtin.base import BuiltinTest, TestResult, TestStatus

class TesteA(BuiltinTest):
    name = "A"
    def _run(self, pal):
        return TestResult(self.name, TestStatus.PASS, "ok")

class TesteB(BuiltinTest):
    name = "B"
    def _run(self, pal):
        return TestResult(self.name, TestStatus.PASS, "ok")
""")
        tests = PluginLoader.load_from_file(p)
        assert len(tests) == 2
        names = {t.name for t in tests}
        assert names == {"A", "B"}

    def test_does_not_include_abstract_base(self, tmp_path) -> None:
        p = write_plugin(tmp_path, "plugin_abstract.py", """
from tests_builtin.base import BuiltinTest, TestResult, TestStatus
from abc import abstractmethod

class IntermediateBase(BuiltinTest):
    @abstractmethod
    def _run(self, pal):
        ...

class ConcreteTest(IntermediateBase):
    name = "Concreto"
    def _run(self, pal):
        return TestResult(self.name, TestStatus.PASS, "ok")
""")
        tests = PluginLoader.load_from_file(p)
        names = [t.name for t in tests]
        assert "Concreto" in names
        assert "" not in names   # base abstrata nao deve aparecer

    def test_loaded_test_runs_without_pal(self, tmp_path) -> None:
        p = write_plugin(tmp_path, "plugin_run.py", """
from tests_builtin.base import BuiltinTest, TestResult, TestStatus

class SemPal(BuiltinTest):
    name = "Sem PAL"
    def _run(self, pal):
        return TestResult(self.name, TestStatus.PASS, "funcionou")
""")
        tests = PluginLoader.load_from_file(p)
        result = tests[0].run(None)   # PAL=None e ok se o teste nao usa
        assert result.status == TestStatus.PASS


# ===========================================================================
# load_from_dir()
# ===========================================================================


class TestPluginLoaderDir:
    def _make_test_file(self, path: Path, letter: str) -> None:
        path.write_text(f"""
from tests_builtin.base import BuiltinTest, TestResult, TestStatus

class Teste{letter}(BuiltinTest):
    name = "Teste {letter}"
    def _run(self, pal):
        return TestResult(self.name, TestStatus.PASS, "ok")
""", encoding="utf-8")

    def test_loads_all_matching_files(self, tmp_path) -> None:
        self._make_test_file(tmp_path / "test_alpha.py", "Alpha")
        self._make_test_file(tmp_path / "test_beta.py",  "Beta")
        tests = PluginLoader.load_from_dir(tmp_path, "test_*.py")
        names = {t.name for t in tests}
        assert "Teste Alpha" in names
        assert "Teste Beta"  in names

    def test_ignores_non_matching_files(self, tmp_path) -> None:
        self._make_test_file(tmp_path / "test_a.py", "A")
        self._make_test_file(tmp_path / "meu_a.py",  "Ignorado")
        tests = PluginLoader.load_from_dir(tmp_path, "test_*.py")
        names = {t.name for t in tests}
        assert "Teste Ignorado" not in names

    def test_empty_dir_returns_empty(self, tmp_path) -> None:
        assert PluginLoader.load_from_dir(tmp_path) == []
