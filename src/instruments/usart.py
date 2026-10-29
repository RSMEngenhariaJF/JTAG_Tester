"""UsartInstrument — configura e monitora USART/UART do STM32F446.

Registradores usados:
    BRR.DIV_Mantissa, DIV_Fraction
    CR1.UE, TE, RE, M, PCE, PS
    CR2.STOP
    SR.TXE, TC, RXNE, ORE
"""

from __future__ import annotations

from enum import Enum, IntEnum

from core.pal.access import PeripheralAccessLayer


class WordLength(IntEnum):
    BITS_8 = 0
    BITS_9 = 1


class Parity(Enum):
    NONE = None
    EVEN = 0
    ODD  = 1


class StopBits(IntEnum):
    ONE      = 0b00  # 1 stop bit
    HALF     = 0b01  # 0.5 stop bits (smartcard)
    TWO      = 0b10  # 2 stop bits
    ONE_HALF = 0b11  # 1.5 stop bits (smartcard)


_PERIPH: dict[int, str] = {
    1: "USART1", 2: "USART2", 3: "USART3",
    4: "UART4",  5: "UART5",  6: "USART6",
}


def _baud_divider(baud: int, f_clk: int) -> tuple[int, int]:
    """Retorna (DIV_Mantissa, DIV_Fraction) para OVER8=0."""
    usartdiv_x16 = f_clk // baud
    return usartdiv_x16 >> 4, usartdiv_x16 & 0xF


class UsartInstrument:
    """Configura e monitora uma porta USART/UART do STM32F446.

    Parâmetros
    ----------
    n   : número da USART (1-6; UART4=4, UART5=5)
    pal : PeripheralAccessLayer conectado ao alvo
    """

    def __init__(self, n: int, pal: PeripheralAccessLayer) -> None:
        if n not in _PERIPH:
            raise KeyError(f"USART{n} não existe no STM32F446 (aceito: 1-6)")
        self._periph = _PERIPH[n]
        self._pal    = pal

    @property
    def periph(self) -> str:
        return self._periph

    # ------------------------------------------------------------------
    # Configuração
    # ------------------------------------------------------------------

    def configure(
        self,
        baud:        int        = 115_200,
        word_length: WordLength = WordLength.BITS_8,
        parity:      Parity     = Parity.NONE,
        stop:        StopBits   = StopBits.ONE,
        f_clk:       int        = 16_000_000,
    ) -> None:
        """Configura baud rate, word length, paridade e stop bits.

        Não habilita automaticamente — chame enable() depois.
        Assume OVER8=0 (16x oversampling).
        """
        mantissa, fraction = _baud_divider(baud, f_clk)
        self._pal.modify_field(self._periph, "BRR", "DIV_Mantissa", mantissa)
        self._pal.modify_field(self._periph, "BRR", "DIV_Fraction", fraction)

        self._pal.modify_field(self._periph, "CR1", "M",    int(word_length))
        self._pal.modify_field(self._periph, "CR2", "STOP", int(stop))

        if parity is Parity.NONE:
            self._pal.modify_field(self._periph, "CR1", "PCE", 0)
        else:
            self._pal.modify_field(self._periph, "CR1", "PCE", 1)
            self._pal.modify_field(self._periph, "CR1", "PS",  parity.value)

    def enable(self, tx: bool = True, rx: bool = True) -> None:
        """Habilita USART e, opcionalmente, TX e/ou RX."""
        self._pal.modify_field(self._periph, "CR1", "UE", 1)
        self._pal.modify_field(self._periph, "CR1", "TE", int(tx))
        self._pal.modify_field(self._periph, "CR1", "RE", int(rx))

    def disable(self) -> None:
        """Desabilita USART (UE=0)."""
        self._pal.modify_field(self._periph, "CR1", "UE", 0)

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def is_enabled(self) -> bool:
        return bool(self._pal.read_field(self._periph, "CR1", "UE"))

    @property
    def is_tx_enabled(self) -> bool:
        return bool(self._pal.read_field(self._periph, "CR1", "TE"))

    @property
    def is_rx_enabled(self) -> bool:
        return bool(self._pal.read_field(self._periph, "CR1", "RE"))

    @property
    def is_tx_empty(self) -> bool:
        return bool(self._pal.read_field(self._periph, "SR", "TXE"))

    @property
    def is_rx_ready(self) -> bool:
        return bool(self._pal.read_field(self._periph, "SR", "RXNE"))

    @property
    def is_transfer_complete(self) -> bool:
        return bool(self._pal.read_field(self._periph, "SR", "TC"))

    @property
    def has_overrun_error(self) -> bool:
        return bool(self._pal.read_field(self._periph, "SR", "ORE"))

    def send_byte(self, data: int, timeout_ms: float = 100.0) -> None:
        """Escreve um byte no DR aguardando TXE (transmit empty)."""
        import time
        deadline = time.perf_counter() + timeout_ms / 1000
        while not self.is_tx_empty:
            if time.perf_counter() > deadline:
                raise TimeoutError(f"{self._periph}: TXE timeout ({timeout_ms} ms)")
        self._pal.write_reg(self._periph, "DR", int(data) & 0xFF)

    def receive_byte(self, timeout_ms: float = 200.0) -> int:
        """Aguarda RXNE e retorna o byte recebido."""
        import time
        deadline = time.perf_counter() + timeout_ms / 1000
        while not self.is_rx_ready:
            if time.perf_counter() > deadline:
                raise TimeoutError(f"{self._periph}: RXNE timeout ({timeout_ms} ms)")
        return self._pal.read_reg(self._periph, "DR") & 0xFF

    def read_status(self) -> int:
        """Lê o registrador SR completo."""
        return self._pal.read_reg(self._periph, "SR")
