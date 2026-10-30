"""Drivers e monitores de GPIO.

Valores lógicos: True = ATIVO, levando em conta o "ativo baixo" do Pinout
(um LED com catodo no pino acende em 0). Use raw=True para trabalhar com o
nível elétrico (0/1) sem a inversão.

Cada componente salva o estado do pino no setup() e o restaura no teardown().
"""

from __future__ import annotations

from itertools import pairwise

from hal.common import PULL, enable_clock, restore_pin, snapshot_pin
from testbench.core import Driver, Monitor


def _level(value, active_low: bool, raw: bool) -> int:
    return int(bool(value)) if raw else int(bool(value)) ^ int(active_low)


def _logical(level: int, active_low: bool, raw: bool) -> int | bool:
    return level if raw else bool(level ^ int(active_low))


class _PinComponent:
    def __init__(self, signal, raw: bool = False) -> None:
        self.signal = signal          # tests_builtin.params.Signal (name, port, pin, active_low)
        self.raw = raw
        self._snap = None

    def _save(self, pal) -> None:
        enable_clock(pal, self.signal.port)
        self._snap = snapshot_pin(pal, self.signal.port, self.signal.pin)

    def _restore(self, pal) -> None:
        if self._snap is not None:
            restore_pin(pal, self._snap)
            self._snap = None


# ── Drivers ───────────────────────────────────────────────────────────────────


class GpioOutputDriver(_PinComponent, Driver):
    """Configura o pino como saída push-pull e aplica níveis via BSRR.

    initial: valor aplicado no setup (None = mantém o ODR atual).
    """

    def __init__(self, signal, *, initial=None, raw: bool = False, name: str = "") -> None:
        super().__init__(signal, raw)
        self.name = name or f"out:{signal.name}"
        self.initial = initial

    def setup(self, pal) -> None:
        self._save(pal)
        if self.initial is not None:
            self.apply(pal, self.initial)
        s = self.signal
        pal.modify_field(s.port, "MODER", f"MODER{s.pin}", 0b01)

    def apply(self, pal, value) -> None:
        s = self.signal
        lvl = _level(value, s.active_low, self.raw)
        pal.write_reg(s.port, "BSRR", 1 << (s.pin if lvl else s.pin + 16))

    def teardown(self, pal) -> None:
        self._restore(pal)


class GpioPullDriver(_PinComponent, Driver):
    """Deixa o pino como entrada e aplica a configuração de pull do passo.

    Valores aceitos: "pull-up", "pull-down", "nenhum".
    """

    def __init__(self, signal, name: str = "") -> None:
        super().__init__(signal)
        self.name = name or f"pull:{signal.name}"

    def setup(self, pal) -> None:
        self._save(pal)
        s = self.signal
        pal.modify_field(s.port, "MODER", f"MODER{s.pin}", 0b00)

    def apply(self, pal, value) -> None:
        s = self.signal
        pal.modify_field(s.port, "PUPDR", f"PUPDR{s.pin}", PULL[value])

    def teardown(self, pal) -> None:
        self._restore(pal)


# ── Monitores ─────────────────────────────────────────────────────────────────


class GpioInputMonitor(_PinComponent, Monitor):
    """Lê o nível do pino (IDR).

    configure: coloca o pino como entrada no setup (False = só lê, sem mexer).
    pull: "manter", "nenhum", "pull-up" ou "pull-down" durante a leitura.
    """

    def __init__(self, signal, *, configure: bool = True, pull: str = "manter",
                 raw: bool = False, name: str = "") -> None:
        super().__init__(signal, raw)
        self.name = name or f"in:{signal.name}"
        self.configure = configure
        self.pull = pull

    def setup(self, pal) -> None:
        if not self.configure and self.pull == "manter":
            return
        self._save(pal)
        s = self.signal
        if self.pull != "manter":
            pal.modify_field(s.port, "PUPDR", f"PUPDR{s.pin}", PULL[self.pull])
        if self.configure:
            pal.modify_field(s.port, "MODER", f"MODER{s.pin}", 0b00)

    def sample(self, pal):
        s = self.signal
        return _logical(pal.read_field(s.port, "IDR", f"IDR{s.pin}"), s.active_low, self.raw)

    def teardown(self, pal) -> None:
        self._restore(pal)


class GpioLatchMonitor(_PinComponent, Monitor):
    """Lê o registrador de saída (ODR): confere o que o driver escreveu."""

    def __init__(self, signal, *, raw: bool = False, name: str = "") -> None:
        super().__init__(signal, raw)
        self.name = name or f"odr:{signal.name}"

    def sample(self, pal):
        s = self.signal
        return _logical(pal.read_field(s.port, "ODR", f"ODR{s.pin}"), s.active_low, self.raw)


class GpioActivityMonitor(_PinComponent, Monitor):
    """Amostra o pino N vezes seguidas (sem mexer no modo): sinal vivo ou parado?

    Amostra: dict "alto_pct" (fração das leituras em 1) e "transicoes". As
    leituras saem no ritmo do SWD (~0,1 a 1 ms), sem relação com o sinal: servem
    para ver se o pino comuta e estimar o duty grosseiramente, não para medir
    tempo (para isso, use o osciloscópio).
    """

    def __init__(self, signal, *, samples: int = 400, name: str = "") -> None:
        super().__init__(signal, raw=True)
        self.samples = samples
        self.name = name or f"atividade:{signal.name}"

    def sample(self, pal) -> dict:
        s = self.signal
        addr = pal.address_of(s.port, "IDR")
        bit = 1 << s.pin
        reads = [bool(pal.mem.read_mem32(addr) & bit) for _ in range(self.samples)]
        trans = sum(a != b for a, b in pairwise(reads))
        return {"alto_pct": 100 * sum(reads) / len(reads), "transicoes": trans}
