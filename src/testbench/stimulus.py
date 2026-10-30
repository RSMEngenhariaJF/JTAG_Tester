"""Estímulos prontos — sequências de passos, sem nenhum conhecimento de hardware."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from testbench.core import Step, Stimulus


class Toggle(Stimulus):
    """Liga/desliga os drivers N vezes. sequential: um driver por vez; senão, todos juntos."""

    def __init__(self, drivers: Sequence[str], cycles: int, period_s: float,
                 sequential: bool = True, on: Any = True, off: Any = False) -> None:
        self.drivers, self.cycles, self.half = list(drivers), cycles, period_s / 2
        self.sequential, self.on, self.off = sequential, on, off

    def steps(self) -> Iterable[Step]:
        groups = [[d] for d in self.drivers] if self.sequential else [self.drivers]
        for group in groups:
            for c in range(self.cycles):
                for value, tag in ((self.on, "liga"), (self.off, "desliga")):
                    yield Step({d: value for d in group}, self.half,
                               f"{'+'.join(group)} {tag} #{c + 1}")


class Levels(Stimulus):
    """Aplica, em ordem, cada valor da lista em um driver (ex.: [0, 1, 0])."""

    def __init__(self, driver: str, values: Sequence[Any], wait_s: float = 0.002) -> None:
        self.driver, self.values, self.wait_s = driver, list(values), wait_s

    def steps(self) -> Iterable[Step]:
        for v in self.values:
            yield Step({self.driver: v}, self.wait_s, f"{self.driver}={v}")


class Sample(Stimulus):
    """Não aciona nada: só amostra os monitores (N vezes, com intervalo)."""

    def __init__(self, count: int = 1, interval_s: float = 0.0, label: str = "leitura") -> None:
        self.count, self.interval_s, self.label = count, interval_s, label

    def steps(self) -> Iterable[Step]:
        for i in range(self.count):
            yield Step({}, self.interval_s if i else 0.0, f"{self.label} #{i + 1}")


class Chain(Stimulus):
    """Concatena estímulos: Chain(Levels(...), Sample(...))."""

    def __init__(self, *parts: Stimulus) -> None:
        self.parts = parts

    def steps(self) -> Iterable[Step]:
        for part in self.parts:
            yield from part.steps()
