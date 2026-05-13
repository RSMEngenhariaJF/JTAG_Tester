"""FT2232HTransport — implementação de ITransport usando FT2232H via pyftdi MPSSE.

Pinagem (canal A, modo MPSSE):
    ADBUS0  TCK  → SWDCLK          (output)
    ADBUS1  TDI  → SWDIO saída     (output quando host drive)  ─┐ resistor ~470 Ω
    ADBUS2  TDO  ← SWDIO entrada   (input sempre)             ─┘ pull-up 10 kΩ externo
    ADBUS3  TMS  → nRST            (output, opcional)

Referências:
    AN_108  — FTDI MPSSE Command Processor (LSB-first, comandos 0x1B / 0x2A)
    IHI0031C — ARM ADIv5 SWD timing: dado muda na borda de descida, captura na subida

Pré-requisitos (hardware):
    - Driver libusb instalado para canal A do FT2232H (veja privada/doc/HARDWARE_SETUP.md)
    - pip install pyftdi

Nota de bit-order (MPSSE bit-mode):
    write_bits: comando 0x1B — bit 0 do byte vai primeiro na linha (LSB-first ✓)
    read_bits:  comando 0x2A — primeiro bit recebido armazenado em bit (8-count) do byte
                retorno: raw_byte >> (8-count) reconstrói o valor original corretamente
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyftdi.ftdi import Ftdi as _Ftdi

# ---------------------------------------------------------------------------
# Constantes MPSSE (AN_108, tabela 3-6)
# ---------------------------------------------------------------------------

# Escrita de bits/bytes — dados na borda de descida, LSB primeiro
_CMD_BITS_OUT: int = 0x1B  # clock bits out, falling edge, LSB first
_CMD_BYTES_OUT: int = 0x19  # clock bytes out, falling edge, LSB first

# Leitura de bits/bytes — captura na borda de subida, LSB primeiro
_CMD_BITS_IN: int = 0x2A  # clock bits in, rising edge, LSB first
_CMD_BYTES_IN: int = 0x28  # clock bytes in, rising edge, LSB first

# Controle de pinos GPIO baixos (ADBUS[7:0])
_CMD_SET_LOW: int = 0x80  # Set Data Bits Low Byte: [cmd, value, direction]

# Descarga imediata do buffer TX → garante que os dados chegam ao FTDI sem espera
_CMD_FLUSH: int = 0x87

# ---------------------------------------------------------------------------
# Configuração de pinos ADBUS
# ---------------------------------------------------------------------------

_PIN_SWDCLK: int = 0x01  # ADBUS0 — TCK → SWDCLK
_PIN_SWDIO_O: int = 0x02  # ADBUS1 — TDI → SWDIO (host→target)
_PIN_SWDIO_I: int = 0x04  # ADBUS2 — TDO ← SWDIO (target→host)
_PIN_NRST: int = 0x08  # ADBUS3 — TMS → nRST

# Máscara de direção (1 = output): CLK, TDI e nRST como saída; TDO como entrada
_DIR_HOST: int = _PIN_SWDCLK | _PIN_SWDIO_O | _PIN_NRST  # 0x0B
_DIR_TARGET: int = _PIN_SWDCLK | _PIN_NRST  # 0x09 (TDI vira input)

_PINS_IDLE: int = 0x08  # nRST=1 (deasserted), CLK=0, TDI=0

_MAX_BITS_PER_CMD: int = 8  # bit-mode MPSSE: 1-8 bits por comando


# ---------------------------------------------------------------------------
# FT2232HTransport
# ---------------------------------------------------------------------------


class FT2232HTransport:
    """ITransport concreto para FT2232H via pyftdi MPSSE (canal A).

    Parâmetros
    ----------
    url        : URL pyftdi do dispositivo, p.ex. "ftdi://ftdi:2232h/1"
                 (use FT2232HDetector.list_devices() para descobrir a URL)
    frequency  : frequência SWDCLK em Hz — padrão 1 MHz (máx. ~30 MHz)
    nrst_pin   : True para usar ADBUS3 como nRST (padrão True)
    """

    def __init__(
        self,
        url: str = "ftdi://ftdi:2232h/1",
        frequency: float = 1_000_000,
        nrst_pin: bool = True,
    ) -> None:
        try:
            from pyftdi.ftdi import Ftdi
        except ImportError as exc:
            raise ImportError("pyftdi não instalado — execute: pip install pyftdi") from exc

        self._ftdi: _Ftdi = Ftdi()
        self._nrst = nrst_pin
        dir_mask = _DIR_HOST if nrst_pin else (_DIR_HOST & ~_PIN_NRST)
        self._dir_host = dir_mask
        self._dir_target = _DIR_TARGET & dir_mask

        self._ftdi.open_mpsse_from_url(
            url,
            direction=self._dir_host,
            initial=_PINS_IDLE,
            frequency=frequency,
        )
        self._host_driving: bool = True

    # ------------------------------------------------------------------
    # ITransport
    # ------------------------------------------------------------------

    def write_bits(self, value: int, count: int) -> None:
        """Envia `count` bits de `value`, LSB primeiro, dados na borda de descida."""
        if not self._host_driving:
            self._take_bus()

        v = value & ((1 << count) - 1)
        cmd = self._build_write_cmd(v, count)
        self._ftdi.write_data(cmd)

    def read_bits(self, count: int) -> int:
        """Lê `count` bits, LSB primeiro (captura na borda de subida). Retorna int."""
        cmd, full_bytes, rem_bits = self._build_read_cmd(count)
        self._ftdi.write_data(cmd)
        return self._decode_read(full_bytes, rem_bits)

    def turnaround(self) -> None:
        """Um ciclo de clock com SWDIO liberado — troca a direção do barramento."""
        if self._host_driving:
            # Host libera o barramento; target vai assumir o controle de SWDIO
            self._release_bus()
            # Pulso de clock enquanto host não está dirigindo (target pode começar)
            self._ftdi.write_data(bytes([_CMD_BITS_IN, 0, _CMD_FLUSH]))
            self._ftdi.read_data_bytes(1, attempt=10)  # descarta bit capturado
        else:
            # Target libera o barramento; host retoma o controle
            # Último pulso enquanto target ainda pode estar dirigindo
            self._ftdi.write_data(bytes([_CMD_BITS_IN, 0, _CMD_FLUSH]))
            self._ftdi.read_data_bytes(1, attempt=10)  # descarta
            self._take_bus()

    # ------------------------------------------------------------------
    # Controle de reset de sistema (nRST via ADBUS3)
    # ------------------------------------------------------------------

    def assert_nrst(self) -> None:
        """Puxa nRST para LOW (reset ativo)."""
        if not self._nrst_pin:
            raise RuntimeError("nRST não habilitado neste transporte")
        self._ftdi.write_data(bytes([_CMD_SET_LOW, _PINS_IDLE & ~_PIN_NRST, self._dir_host]))

    def deassert_nrst(self) -> None:
        """Libera nRST (HIGH — reset inativo)."""
        self._ftdi.write_data(bytes([_CMD_SET_LOW, _PINS_IDLE, self._dir_host]))

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> FT2232HTransport:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Fecha a conexão com o FT2232H."""
        self._ftdi.close()

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _release_bus(self) -> None:
        """ADBUS1 vira input — host para de dirigir SWDIO."""
        self._ftdi.write_data(bytes([_CMD_SET_LOW, _PINS_IDLE, self._dir_target]))
        self._host_driving = False

    def _take_bus(self) -> None:
        """ADBUS1 vira output — host retoma controle de SWDIO."""
        self._ftdi.write_data(bytes([_CMD_SET_LOW, _PINS_IDLE, self._dir_host]))
        self._host_driving = True

    @staticmethod
    def _build_write_cmd(value: int, count: int) -> bytes:
        """Monta sequência MPSSE para escrever `count` bits de `value`."""
        full_bytes, rem = divmod(count, 8)
        cmd = bytearray()
        if full_bytes:
            n = full_bytes - 1
            payload = value.to_bytes(full_bytes, "little")
            cmd += bytes([_CMD_BYTES_OUT, n & 0xFF, (n >> 8) & 0xFF]) + payload
        if rem:
            rem_val = (value >> (full_bytes * 8)) & ((1 << rem) - 1)
            cmd += bytes([_CMD_BITS_OUT, rem - 1, rem_val])
        return bytes(cmd)

    @staticmethod
    def _build_read_cmd(count: int) -> tuple[bytes, int, int]:
        """Monta sequência MPSSE para ler `count` bits + flush."""
        full_bytes, rem = divmod(count, 8)
        cmd = bytearray()
        if full_bytes:
            n = full_bytes - 1
            cmd += bytes([_CMD_BYTES_IN, n & 0xFF, (n >> 8) & 0xFF])
        if rem:
            cmd += bytes([_CMD_BITS_IN, rem - 1])
        cmd += bytes([_CMD_FLUSH])
        return bytes(cmd), full_bytes, rem

    def _decode_read(self, full_bytes: int, rem_bits: int) -> int:
        """Lê e decodifica bytes do FTDI após um comando de leitura."""
        result = 0
        if full_bytes:
            raw = self._ftdi.read_data_bytes(full_bytes, attempt=10)
            result = int.from_bytes(raw, "little")
        if rem_bits:
            raw = self._ftdi.read_data_bytes(1, attempt=10)
            # AN_108: primeiro bit recebido fica em bit (8-count) do byte retornado.
            # raw[0] >> (8 - rem_bits) reconstrói o valor na ordem LSB-first correta.
            result |= (raw[0] >> (8 - rem_bits)) << (full_bytes * 8)
        return result
