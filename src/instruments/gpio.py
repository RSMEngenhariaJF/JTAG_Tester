"""GpioInstrument — controle de GPIO STM32 via PAL.

Abstrai a configuração de MODER, OSPEEDR, PUPDR, OTYPER e AFR[L/H]
em chamadas de alto nível, usando BSRR para set/reset atômico.

Exemplo::

    clk = ClockInstrument(pal)
    clk.enable_gpio("A")

    gpio = GpioInstrument("A", pal)
    led = gpio.pin(5)           # PA5 = LD2 na NUCLEO
    led.configure_output()
    led.set()                   # LED ON
    led.toggle()                # LED OFF

Nomes de campos SVD usados (STM32F446):
    MODER   → MODER{n}    (2 bits, pins 0-15)
    OTYPER  → OT{n}       (1 bit,  pins 0-15)
    OSPEEDR → OSPEEDR{n}  (2 bits, pins 0-15)
    PUPDR   → PUPDR{n}    (2 bits, pins 0-15)
    IDR     → IDR{n}      (1 bit,  pins 0-15)
    ODR     → ODR{n}      (1 bit,  pins 0-15)
    AFRL    → AFRL{n}     (4 bits, pins 0-7)
    AFRH    → AFRH{n}     (4 bits, pins 8-15)
"""

from __future__ import annotations

from enum import IntEnum

from core.pal.access import PeripheralAccessLayer


class GpioMode(IntEnum):
    INPUT = 0b00
    OUTPUT = 0b01
    ALTERNATE = 0b10
    ANALOG = 0b11


class GpioSpeed(IntEnum):
    LOW = 0b00
    MEDIUM = 0b01
    HIGH = 0b10
    VERY_HIGH = 0b11


class GpioPull(IntEnum):
    NONE = 0b00
    PULL_UP = 0b01
    PULL_DOWN = 0b10


def _periph_name(port: str) -> str:
    """Normaliza 'A', 'PA' ou 'GPIOA' → 'GPIOA'."""
    p = port.upper().strip()
    if p.startswith("GPIO"):
        return p[:5]      # 'GPIOA'
    if len(p) == 2 and p[0] == "P":
        return f"GPIO{p[1]}"
    if len(p) == 1:
        return f"GPIO{p}"
    raise ValueError(f"Porta GPIO não reconhecida: '{port}'")


class GpioPin:
    """Controla um único pino GPIO do STM32.

    Parâmetros
    ----------
    periph : nome do periférico SVD — ex. 'GPIOA'
    pin    : número do pino (0–15)
    pal    : PeripheralAccessLayer conectado ao alvo
    """

    def __init__(self, periph: str, pin: int, pal: PeripheralAccessLayer) -> None:
        if not 0 <= pin <= 15:
            raise ValueError(f"Pino GPIO inválido: {pin} (aceito: 0–15)")
        self._periph = periph.upper()
        self._pin = pin
        self._pal = pal

    # ------------------------------------------------------------------
    # Configuração
    # ------------------------------------------------------------------

    def configure(
        self,
        mode: GpioMode = GpioMode.INPUT,
        speed: GpioSpeed = GpioSpeed.LOW,
        pull: GpioPull = GpioPull.NONE,
        open_drain: bool = False,
        af: int | None = None,
    ) -> None:
        """Configura o pino de uma vez.

        Parâmetros
        ----------
        mode       : INPUT / OUTPUT / ALTERNATE / ANALOG
        speed      : LOW / MEDIUM / HIGH / VERY_HIGH
        pull       : NONE / PULL_UP / PULL_DOWN
        open_drain : False = push-pull (padrão), True = open-drain
        af         : Alternate Function 0–15 (só relevante em modo ALTERNATE)
        """
        n = self._pin
        self._pal.modify_field(self._periph, "MODER",   f"MODER{n}",   int(mode))
        self._pal.modify_field(self._periph, "OSPEEDR", f"OSPEEDR{n}", int(speed))
        self._pal.modify_field(self._periph, "PUPDR",   f"PUPDR{n}",   int(pull))
        self._pal.modify_field(self._periph, "OTYPER",  f"OT{n}",      int(open_drain))
        if af is not None:
            if n <= 7:
                self._pal.modify_field(self._periph, "AFRL", f"AFRL{n}", af & 0xF)
            else:
                self._pal.modify_field(self._periph, "AFRH", f"AFRH{n}", af & 0xF)

    def configure_output(
        self,
        speed: GpioSpeed = GpioSpeed.LOW,
        open_drain: bool = False,
    ) -> None:
        self.configure(mode=GpioMode.OUTPUT, speed=speed, open_drain=open_drain)

    def configure_input(self, pull: GpioPull = GpioPull.NONE) -> None:
        self.configure(mode=GpioMode.INPUT, pull=pull)

    def configure_alternate(self, af: int, speed: GpioSpeed = GpioSpeed.LOW) -> None:
        self.configure(mode=GpioMode.ALTERNATE, speed=speed, af=af)

    # ------------------------------------------------------------------
    # Leitura / escrita
    # ------------------------------------------------------------------

    def read(self) -> bool:
        """Lê o nível lógico do pino via IDR."""
        return bool(self._pal.read_field(self._periph, "IDR", f"IDR{self._pin}"))

    def set(self) -> None:
        """Força HIGH via BSRR (atômico, sem RMW)."""
        self._pal.write_reg(self._periph, "BSRR", 1 << self._pin)

    def reset(self) -> None:
        """Força LOW via BSRR (atômico, sem RMW)."""
        self._pal.write_reg(self._periph, "BSRR", 1 << (self._pin + 16))

    def write(self, value: bool) -> None:
        self.set() if value else self.reset()

    def toggle(self) -> None:
        """Inverte o estado atual (lê ODR, escreve BSRR)."""
        current = bool(self._pal.read_field(self._periph, "ODR", f"ODR{self._pin}"))
        self.write(not current)

    # ------------------------------------------------------------------
    # Propriedades de estado
    # ------------------------------------------------------------------

    @property
    def mode(self) -> GpioMode:
        return GpioMode(self._pal.read_field(self._periph, "MODER", f"MODER{self._pin}"))

    @property
    def pull(self) -> GpioPull:
        return GpioPull(self._pal.read_field(self._periph, "PUPDR", f"PUPDR{self._pin}"))

    @property
    def periph(self) -> str:
        return self._periph

    @property
    def pin(self) -> int:
        return self._pin


class GpioInstrument:
    """Instrumento para uma porta GPIO completa (PA, PB, PC, …).

    Parâmetros
    ----------
    port : letra da porta — aceita 'A', 'PA' ou 'GPIOA'
    pal  : PeripheralAccessLayer conectado ao alvo
    """

    def __init__(self, port: str, pal: PeripheralAccessLayer) -> None:
        self._periph = _periph_name(port)
        self._pal = pal
        self._cache: dict[int, GpioPin] = {}

    def pin(self, n: int) -> GpioPin:
        """Retorna (e cacheia) o GpioPin do pino n."""
        if n not in self._cache:
            self._cache[n] = GpioPin(self._periph, n, self._pal)
        return self._cache[n]

    def read_port(self) -> int:
        """Lê todos os 16 bits do IDR de uma vez."""
        return self._pal.read_reg(self._periph, "IDR") & 0xFFFF

    def write_port(self, value: int, mask: int = 0xFFFF) -> None:
        """Escreve ODR com máscara (RMW). Bits 0 na máscara são preservados."""
        current = self._pal.read_reg(self._periph, "ODR")
        updated = (current & ~mask & 0xFFFF) | (value & mask & 0xFFFF)
        self._pal.write_reg(self._periph, "ODR", updated)

    @property
    def periph(self) -> str:
        return self._periph
