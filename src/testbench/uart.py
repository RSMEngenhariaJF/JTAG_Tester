"""Driver e monitor de UART/RS485 que compartilham um enlace (UartLink).

O enlace coloca os pinos do periférico em AF (TX, RX e, com DE, o pino DE),
configura a UART e restaura tudo no fim. O driver envia um byte por passo; o
monitor lê o byte recebido (eco) ou None se nada chegar.

    link = UartLink(periferico, 1200, de=True)
    tx, rx = UartTxDriver(link), UartRxMonitor(link)
"""

from __future__ import annotations

from hal.common import pin_af, restore_pin, set_af, snapshot_pin
from hal.uart import Uart
from testbench.core import Driver, Monitor


class UartLink:
    def __init__(self, periph, baud: int, *, rx: bool = True, de: bool = False,
                 de_active_low: bool = False) -> None:
        self.periph, self.baud, self.rx, self.de = periph, baud, rx, de
        self.de_active_low = de_active_low
        self.uart: Uart | None = None
        self.real_baud = 0.0
        self.errors: dict = {}
        self._snaps: list = []

    @property
    def roles(self) -> tuple[str, ...]:
        return ("TX",) + (("RX",) if self.rx else ()) + (("DE",) if self.de else ())

    def open(self, pal) -> None:
        if self.uart is not None:
            return
        for role in self.roles:
            s = self.periph.pin(role)
            self._snaps.append(snapshot_pin(pal, s.port, s.pin))
            set_af(pal, s.port, s.pin, pin_af(pal, s, self.periph.name))
        self.uart = Uart(pal, self.periph.name)
        self.real_baud = self.uart.setup(self.baud, de=self.de, de_active_low=self.de_active_low)

    def close(self, pal) -> None:
        if self.uart is not None:
            self.errors = dict(self.uart.errors)
            self.uart.restore()
            self.uart = None
        for snap in reversed(self._snaps):
            restore_pin(pal, snap)
        self._snaps = []

    @property
    def byte_s(self) -> float:
        return 10 / self.baud                       # 8N1


class UartTxDriver(Driver):
    def __init__(self, link: UartLink, name: str = "") -> None:
        self.link = link
        self.name = name or f"tx:{link.periph.name}"

    def setup(self, pal) -> None:
        self.link.open(pal)

    def apply(self, pal, value: int) -> None:
        self.link.uart.write(value)

    def teardown(self, pal) -> None:
        self.link.close(pal)


class UartRxMonitor(Monitor):
    def __init__(self, link: UartLink, name: str = "") -> None:
        self.link = link
        self.name = name or f"rx:{link.periph.name}"

    def setup(self, pal) -> None:
        self.link.open(pal)

    def sample(self, pal) -> int | None:
        try:
            return self.link.uart.read(timeout_s=3 * self.link.byte_s + 0.05)
        except TimeoutError:
            return None
