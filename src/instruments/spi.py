"""SpiInstrument — configura e monitora SPI do STM32F446.

Registradores usados:
    CR1.SPE, MSTR, CPOL, CPHA, BR, DFF, SSM, SSI, LSBFIRST
    SR.TXE, RXNE, BSY, OVR, MODF
"""

from __future__ import annotations

from enum import IntEnum

from core.pal.access import PeripheralAccessLayer


class SpiBaudDiv(IntEnum):
    """Divisor de clock APB → SPI (campo BR[2:0] no CR1)."""
    DIV_2   = 0b000   # f_APB / 2
    DIV_4   = 0b001   # f_APB / 4
    DIV_8   = 0b010   # f_APB / 8
    DIV_16  = 0b011   # f_APB / 16
    DIV_32  = 0b100   # f_APB / 32
    DIV_64  = 0b101   # f_APB / 64
    DIV_128 = 0b110   # f_APB / 128
    DIV_256 = 0b111   # f_APB / 256


_PERIPH: dict[int, str] = {
    1: "SPI1", 2: "SPI2", 3: "SPI3", 4: "SPI4",
}

# SPI mode → (CPOL, CPHA)
_SPI_MODE: dict[int, tuple[int, int]] = {
    0: (0, 0),
    1: (0, 1),
    2: (1, 0),
    3: (1, 1),
}


class SpiInstrument:
    """Configura e monitora uma porta SPI do STM32F446.

    Parâmetros
    ----------
    n   : número do SPI (1-4)
    pal : PeripheralAccessLayer conectado ao alvo
    """

    def __init__(self, n: int, pal: PeripheralAccessLayer) -> None:
        if n not in _PERIPH:
            raise KeyError(f"SPI{n} não existe no STM32F446 (aceito: 1-4)")
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
        mode:       int        = 0,
        baud_div:   SpiBaudDiv = SpiBaudDiv.DIV_256,
        data_16bit: bool       = False,
        lsb_first:  bool       = False,
        master:     bool       = True,
        sw_nss:     bool       = True,
    ) -> None:
        """Configura modo, divisor de clock, frame format e gestão de NSS.

        Parâmetros
        ----------
        mode      : modo SPI 0-3 (define CPOL e CPHA)
        baud_div  : divisor de clock APB para SPI
        data_16bit: False=8 bits, True=16 bits
        lsb_first : False=MSB first (padrão), True=LSB first
        master    : True=master, False=slave
        sw_nss    : True=NSS gerenciado por software (SSM=1, SSI=1)
        """
        if mode not in _SPI_MODE:
            raise ValueError(f"Modo SPI inválido: {mode} (aceito: 0-3)")
        cpol, cpha = _SPI_MODE[mode]

        self._pal.modify_field(self._periph, "CR1", "CPOL",     cpol)
        self._pal.modify_field(self._periph, "CR1", "CPHA",     cpha)
        self._pal.modify_field(self._periph, "CR1", "BR",       int(baud_div))
        self._pal.modify_field(self._periph, "CR1", "DFF",      int(data_16bit))
        self._pal.modify_field(self._periph, "CR1", "LSBFIRST", int(lsb_first))
        self._pal.modify_field(self._periph, "CR1", "MSTR",     int(master))
        self._pal.modify_field(self._periph, "CR1", "SSM",      int(sw_nss))
        self._pal.modify_field(self._periph, "CR1", "SSI",      int(sw_nss))

    def enable(self) -> None:
        """Habilita SPI (CR1.SPE=1)."""
        self._pal.modify_field(self._periph, "CR1", "SPE", 1)

    def disable(self) -> None:
        """Desabilita SPI (CR1.SPE=0)."""
        self._pal.modify_field(self._periph, "CR1", "SPE", 0)

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def is_enabled(self) -> bool:
        return bool(self._pal.read_field(self._periph, "CR1", "SPE"))

    @property
    def is_busy(self) -> bool:
        return bool(self._pal.read_field(self._periph, "SR", "BSY"))

    @property
    def is_tx_empty(self) -> bool:
        return bool(self._pal.read_field(self._periph, "SR", "TXE"))

    @property
    def is_rx_ready(self) -> bool:
        return bool(self._pal.read_field(self._periph, "SR", "RXNE"))

    @property
    def has_overrun(self) -> bool:
        return bool(self._pal.read_field(self._periph, "SR", "OVR"))

    @property
    def has_mode_fault(self) -> bool:
        return bool(self._pal.read_field(self._periph, "SR", "MODF"))

    @property
    def mode(self) -> int:
        """Retorna o modo SPI atual (0-3) derivado de CPOL e CPHA."""
        cpol = self._pal.read_field(self._periph, "CR1", "CPOL")
        cpha = self._pal.read_field(self._periph, "CR1", "CPHA")
        for m, (c, h) in _SPI_MODE.items():
            if c == cpol and h == cpha:
                return m
        return -1

    def transfer_byte(self, data: int, timeout_ms: float = 100.0) -> int:
        """Envia um byte e retorna o byte recebido (full-duplex).

        Aguarda TXE antes de escrever e RXNE antes de ler.
        """
        import time
        # Aguarda DR de TX disponível
        deadline = time.perf_counter() + timeout_ms / 1000
        while not self.is_tx_empty:
            if time.perf_counter() > deadline:
                raise TimeoutError(f"{self._periph}: TXE timeout ({timeout_ms} ms)")
        self._pal.write_reg(self._periph, "DR", int(data) & 0xFF)
        # Aguarda dado recebido
        deadline = time.perf_counter() + timeout_ms / 1000
        while not self.is_rx_ready:
            if time.perf_counter() > deadline:
                raise TimeoutError(f"{self._periph}: RXNE timeout ({timeout_ms} ms)")
        return self._pal.read_reg(self._periph, "DR") & 0xFF

    def read_status(self) -> int:
        """Lê o registrador SR completo."""
        return self._pal.read_reg(self._periph, "SR")
