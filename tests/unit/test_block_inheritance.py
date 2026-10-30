"""Bloco novo herdando de um bloco existente (em outro arquivo).

Execução:
    pytest tests/unit/test_block_inheritance.py -v
"""

from __future__ import annotations

from pathlib import Path

from tests_builtin.loader import PluginLoader
from tests_builtin.plan import list_library

DERIVADO = '''
from tests_builtin.params import Signals
from tests_builtin.plan import resolve_ref

PullCurto = resolve_ref("TESTES_PLATAFORMA/BLOCOS/gpio.py:PullCurto")


class PullCurtoI2c(PullCurto):
    name = "GPIO — Pull (só pinos I2C)"
    params = {**PullCurto.params, "pinos": Signals("Pinos I2C", types=("I2C",))}
'''


def test_subclass_in_other_file_registers_only_itself(tmp_path: Path) -> None:
    f = tmp_path / "meu_bloco.py"
    f.write_text(DERIVADO, encoding="utf-8")
    names = [type(t).__name__ for t in PluginLoader.load_from_file(f)]
    assert names == ["PullCurtoI2c"]                 # o PullCurto importado não entra


def test_library_has_no_duplicates(tmp_path: Path) -> None:
    (tmp_path / "meu_bloco.py").write_text(DERIVADO, encoding="utf-8")
    refs = [i.ref for i in list_library(tmp_path)]
    assert len(refs) == 1 and refs[0].endswith("meu_bloco.py:PullCurtoI2c")
    item = list_library(tmp_path)[0]
    assert item.category == "GPIO"                   # herdado do bloco pai
    assert item.cls.params["pinos"].types == ("I2C",)
