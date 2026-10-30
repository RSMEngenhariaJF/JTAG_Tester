"""Parâmetros de teste — a lógica do teste fica separada dos pinos e valores.

Um teste declara o que precisa em ``params``; o projeto (aba "Plano de testes")
diz a que sinais e valores ele se aplica. O mesmo arquivo serve a várias
instâncias: "Piscar LED" nos LEDs indicadores, "Piscar LED" nas saídas de relé...

Exemplo::

    class PiscarLed(BuiltinTest):
        name = "Piscar LED"
        params = {
            "pinos":      SignalsParam("Pinos", types=("GPIO",)),
            "ciclos":     IntParam("Ciclos", default=3, minimum=1, maximum=50),
            "periodo_ms": IntParam("Período", default=250, minimum=20, maximum=5000, unit="ms"),
        }

        def _run(self, pal):
            for s in self.p.pinos:              # Signal: .name .port .pin .active_low
                ...
            time.sleep(self.p.periodo_ms / 1000)

Os sinais são resolvidos pelo nome no projeto ativo na hora da execução: trocar
o pino de um sinal no Pinout não exige mudar o teste nem o plano.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


@dataclass(frozen=True)
class Signal:
    """Sinal do projeto resolvido para o pino físico."""

    name:        str
    port:        str
    pin:         int
    active_low:  bool = False
    periph_type: str = "GPIO"
    description: str = ""
    role:        str = ""            # função no periférico: "TX", "MOSI", "MDC"...
    af:          int | None = None   # AF informada no Pinout (params["af"]); None = tabela
    periph_name: str = ""            # periférico do pino: "TIM2", "USART3"...

    def __str__(self) -> str:
        return f"{self.name} ({self.port}{self.pin})"


def _signal(name: str, pd) -> Signal:
    af = pd.peripheral.params.get("af") if pd.peripheral.params else None
    return Signal(name, pd.port, pd.pin, pd.active_low, pd.peripheral.periph_type or "GPIO",
                  pd.description, pd.peripheral.role.upper(), None if af is None else int(af),
                  pd.peripheral.name)


@dataclass(frozen=True)
class Peripheral:
    """Periférico do Pinout (ex.: USART3) com seus pinos indexados pela função."""

    name:        str
    periph_type: str
    pins:        dict[str, Signal]
    params:      dict = field(default_factory=dict)

    def pin(self, role: str) -> Signal:
        try:
            return self.pins[role.upper()]
        except KeyError:
            raise KeyError(f"{self.name}: nenhum pino com função {role.upper()} no Pinout "
                           f"(há: {', '.join(sorted(self.pins)) or 'nenhum'})") from None

    def has(self, role: str) -> bool:
        return role.upper() in self.pins

    def __str__(self) -> str:
        return self.name


# ── Tipos de parâmetro ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Param:
    label: str
    help:  str = ""

    def default(self) -> Any:
        raise NotImplementedError

    def validate(self, value: Any, project=None) -> list[str]:
        return []

    def resolve(self, value: Any, project=None) -> Any:
        return value

    def describe(self, value: Any) -> str:
        """Texto curto do valor, para o relatório."""
        return str(value)


@dataclass(frozen=True)
class SignalsParam(Param):
    """Lista de sinais do projeto. ``types`` filtra pelo tipo do pino (vazio = todos)."""

    types:     tuple[str, ...] = ("GPIO",)
    min_count: int = 1
    max_count: int | None = None

    def default(self) -> list[str]:
        return []

    def accepts(self, periph_type: str) -> bool:
        return not self.types or (periph_type or "GPIO").upper() in self.types

    def validate(self, value, project=None) -> list[str]:
        names = list(value or [])
        errs = []
        if len(names) < self.min_count:
            errs.append(f"{self.label}: selecione ao menos {self.min_count}")
        if self.max_count is not None and len(names) > self.max_count:
            errs.append(f"{self.label}: no máximo {self.max_count}")
        if project is not None:
            for n in names:
                if n not in project.pins:
                    errs.append(f"{self.label}: sinal '{n}' não existe no projeto")
                elif not self.accepts(project.pins[n].peripheral.periph_type):
                    errs.append(f"{self.label}: sinal '{n}' não é do tipo "
                                f"{'/'.join(self.types)}")
        return errs

    def resolve(self, value, project=None) -> list[Signal]:
        out = []
        for n in value or []:
            out.append(_signal(n, project.pin(n)))
        return out

    def describe(self, value) -> str:
        return ", ".join(value or []) or "—"


@dataclass(frozen=True)
class IntParam(Param):
    default_value: int = 0
    minimum: int = 0
    maximum: int = 1_000_000
    unit: str = ""

    def default(self) -> int:
        return self.default_value

    def validate(self, value, project=None) -> list[str]:
        if not isinstance(value, int) or isinstance(value, bool):
            return [f"{self.label}: inteiro esperado"]
        if not self.minimum <= value <= self.maximum:
            return [f"{self.label}: fora de [{self.minimum}, {self.maximum}]"]
        return []

    def describe(self, value) -> str:
        return f"{value} {self.unit}".strip()


@dataclass(frozen=True)
class FloatParam(Param):
    default_value: float = 0.0
    minimum: float = 0.0
    maximum: float = 1e12
    decimals: int = 3
    unit: str = ""

    def default(self) -> float:
        return self.default_value

    def validate(self, value, project=None) -> list[str]:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return [f"{self.label}: número esperado"]
        if not self.minimum <= value <= self.maximum:
            return [f"{self.label}: fora de [{self.minimum:g}, {self.maximum:g}]"]
        return []

    def resolve(self, value, project=None) -> float:
        return float(value)

    def describe(self, value) -> str:
        return f"{value:g} {self.unit}".strip()


@dataclass(frozen=True)
class ChoiceParam(Param):
    choices: tuple[str, ...] = field(default_factory=tuple)
    default_value: str = ""

    def default(self) -> str:
        return self.default_value or (self.choices[0] if self.choices else "")

    def validate(self, value, project=None) -> list[str]:
        return [] if value in self.choices else [f"{self.label}: opção '{value}' inválida"]


@dataclass(frozen=True)
class BoolParam(Param):
    default_value: bool = False

    def default(self) -> bool:
        return self.default_value

    def validate(self, value, project=None) -> list[str]:
        return [] if isinstance(value, bool) else [f"{self.label}: sim/não esperado"]

    def describe(self, value) -> str:
        return "sim" if value else "não"


@dataclass(frozen=True)
class TextParam(Param):
    default_value: str = ""
    placeholder: str = ""

    def default(self) -> str:
        return self.default_value

    def validate(self, value, project=None) -> list[str]:
        return [] if isinstance(value, str) else [f"{self.label}: texto esperado"]

    def describe(self, value) -> str:
        return value or "—"


@dataclass(frozen=True)
class PeripheralParam(Param):
    """Um periférico do Pinout de um dos tipos (ex.: UART → "USART3")."""

    types: tuple[str, ...] = ("UART",)

    def default(self) -> str:
        return ""

    def options(self, pins: dict) -> list[str]:
        names: list[str] = []
        for pd in pins.values():
            ref = pd.peripheral
            if ref.name and (ref.periph_type or "").upper() in self.types and ref.name not in names:
                names.append(ref.name)
        return names

    def validate(self, value, project=None) -> list[str]:
        if not value:
            return [f"{self.label}: escolha um periférico"]
        if project is not None and value not in self.options(project.pins):
            return [f"{self.label}: '{value}' não está no Pinout como {'/'.join(self.types)}"]
        return []

    def resolve(self, value, project=None) -> Peripheral:
        pins: dict[str, Signal] = {}
        params: dict = {}
        ptype = ""
        for name, pd in project.pins.items():
            if pd.peripheral.name == value:
                sig = _signal(name, pd)
                pins[sig.role or name.upper()] = sig
                params.update(pd.peripheral.params or {})
                ptype = pd.peripheral.periph_type
        return Peripheral(value, ptype, pins, params)


# Atalhos com o valor padrão como 2º argumento posicional (mais legível no teste)
def Int(label: str, default: int, minimum: int = 0, maximum: int = 1_000_000,  # noqa: N802
        unit: str = "", help: str = "") -> IntParam:
    return IntParam(label, help, default, minimum, maximum, unit)


def Float(label: str, default: float, minimum: float = 0.0, maximum: float = 1e12,  # noqa: N802
          unit: str = "", decimals: int = 3, help: str = "") -> FloatParam:
    return FloatParam(label, help, default, minimum, maximum, decimals, unit)


def Choice(label: str, choices: tuple[str, ...], default: str = "",  # noqa: N802
           help: str = "") -> ChoiceParam:
    return ChoiceParam(label, help, tuple(choices), default)


def Bool(label: str, default: bool = False, help: str = "") -> BoolParam:  # noqa: N802
    return BoolParam(label, help, default)


def Text(label: str, default: str = "", placeholder: str = "",  # noqa: N802
         help: str = "") -> TextParam:
    return TextParam(label, help, default, placeholder)


def Periph(label: str, types: tuple[str, ...], help: str = "") -> PeripheralParam:  # noqa: N802
    return PeripheralParam(label, help, tuple(t.upper() for t in types))


def Signals(label: str, types: tuple[str, ...] = ("GPIO",), min_count: int = 1,  # noqa: N802
            max_count: int | None = None, help: str = "") -> SignalsParam:
    return SignalsParam(label, help, tuple(t.upper() for t in types), min_count, max_count)


# ── Validação e resolução de um conjunto ──────────────────────────────────────

def defaults(params: dict[str, Param]) -> dict[str, Any]:
    return {k: p.default() for k, p in params.items()}


def validate(params: dict[str, Param], values: dict, project=None) -> list[str]:
    merged = {**defaults(params), **(values or {})}
    errs: list[str] = []
    for k, p in params.items():
        errs += p.validate(merged[k], project)
    unknown = set(values or {}) - set(params)
    errs += [f"Parâmetro desconhecido: {k}" for k in sorted(unknown)]
    return errs


def resolve(params: dict[str, Param], values: dict, project=None) -> SimpleNamespace:
    merged = {**defaults(params), **(values or {})}
    return SimpleNamespace(**{k: p.resolve(merged[k], project) for k, p in params.items()})


def describe(params: dict[str, Param], values: dict) -> dict[str, str]:
    merged = {**defaults(params), **(values or {})}
    return {params[k].label: params[k].describe(merged[k]) for k in params}
