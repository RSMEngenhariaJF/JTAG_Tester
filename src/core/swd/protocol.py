"""Protocolo SWD bit-a-bit — ARM ADIv5 (IHI0031C).

Camada de protocolo pura: não abre porta USB, não toca hardware.
Depende de ITransport, que o adaptador FT2232H implementará no Sprint 05.

Mapeamento de pinos FT2232H (MPSSE, canal A):
    ADBUS0  TCK   → SWDCLK
    ADBUS1  TDI   → SWDIO (saída)  ─┐ ligados via resistor ~470 Ω
    ADBUS2  TDO   ← SWDIO (entrada) ─┘ com pull-up externo
    ADBUS3  TMS   → não usado em SWD (pode ser nSRST)
Direção MPSSE: 0x0B (ADBUS0, ADBUS1, ADBUS3 = saída; ADBUS2 = entrada)

Referências:
    IHI0031C — ARM Debug Interface Architecture Specification ADIv5.0 to ADIv5.2
    AN_108   — FTDI MPSSE Command Processor (LSB-first, -ve clock out / +ve clock in)
"""

from __future__ import annotations

from typing import Final, Protocol

from core.swd.errors import AckError, ParityError

# ---------------------------------------------------------------------------
# Constantes de protocolo
# ---------------------------------------------------------------------------

ACK_OK: Final[int] = 0b001
ACK_WAIT: Final[int] = 0b010
ACK_FAULT: Final[int] = 0b100

# Endereços DP (A[3:2]) — ARM ADIv5 tabela 2-5
DP_ADDR_DPIDR: Final[int] = 0x00  # leitura; ABORT no write
DP_ADDR_ABORT: Final[int] = 0x00  # escrita
DP_ADDR_CTRL_STAT: Final[int] = 0x04
DP_ADDR_SELECT: Final[int] = 0x08  # escrita; RESEND no read
DP_ADDR_RDBUFF: Final[int] = 0x0C  # leitura

# Endereços MEM-AP (A[3:2]) — ARM ADIv5 tabela 7-4
AP_ADDR_CSW: Final[int] = 0x00
AP_ADDR_TAR: Final[int] = 0x04
AP_ADDR_DRW: Final[int] = 0x0C
AP_ADDR_IDR: Final[int] = 0xFC  # banco 0xF
AP_ADDR_BASE: Final[int] = 0xF8  # banco 0xF

# Sequência de seleção JTAG→SWD (IHI0031C §5.2.1)
_JTAG_TO_SWD_SEQ: Final[int] = 0x9EE7

_LINE_RESET_BITS: Final[int] = 56  # spec exige ≥ 50
_IDLE_BITS: Final[int] = 8

_MASK32: Final[int] = 0xFFFF_FFFF


# ---------------------------------------------------------------------------
# Interface de transporte
# ---------------------------------------------------------------------------


class ITransport(Protocol):
    """Interface mínima para transporte SWD bit-a-bit (LSB first).

    Implementações concretas:
        Sprint 05 — FT2232HTransport (pyftdi MPSSE, canal A)
        Testes    — MockTransport (grava bits, retorna respostas pré-configuradas)
    """

    def write_bits(self, value: int, count: int) -> None:
        """Envia `count` bits de `value`, LSB primeiro, pelo SWDIO (saída)."""
        ...

    def read_bits(self, count: int) -> int:
        """Lê `count` bits do SWDIO (entrada), LSB primeiro."""
        ...

    def turnaround(self) -> None:
        """Um ciclo de clock com SWDIO liberado (troca de direção)."""
        ...


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------


def _even_parity(value: int, bits: int = 32) -> int:
    """Paridade par (XOR de todos os bits) — usada em request e dados."""
    p = 0
    for _ in range(bits):
        p ^= value & 1
        value >>= 1
    return p


def _build_request(apndp: int, rnw: int, addr: int) -> int:
    """Monta o byte de request de 8 bits (IHI0031C §4.3).

    Bit 0: Start = 1
    Bit 1: APnDP
    Bit 2: RnW
    Bit 3: A[2]
    Bit 4: A[3]
    Bit 5: Parity (par sobre bits 1..4)
    Bit 6: Stop = 0
    Bit 7: Park = 1
    """
    a2 = (addr >> 2) & 1
    a3 = (addr >> 3) & 1
    parity = _even_parity(apndp | (rnw << 1) | (a2 << 2) | (a3 << 3), 4)
    return (
        1  # start
        | (apndp << 1)
        | (rnw << 2)
        | (a2 << 3)
        | (a3 << 4)
        | (parity << 5)
        # bit 6 = stop = 0
        | (1 << 7)  # park
    )


# ---------------------------------------------------------------------------
# Protocolo SWD
# ---------------------------------------------------------------------------


class SWDProtocol:
    """Implementação do protocolo SWD sobre ITransport.

    Uso típico:
        proto = SWDProtocol(transport)
        proto.jtag_to_swd()          # ou line_reset() se já em modo SWD
        dpidr = proto.read_dp(DP_ADDR_DPIDR)
        proto.write_dp(DP_ADDR_SELECT, 0x00)
        idr   = proto.read_ap(AP_ADDR_IDR)
    """

    def __init__(self, transport: ITransport) -> None:
        self._t = transport

    # ------------------------------------------------------------------
    # Inicialização / reset
    # ------------------------------------------------------------------

    def line_reset(self) -> None:
        """Reseta a linha SWD: ≥50 ciclos SWDCLK com SWDIO=HIGH + idle.

        Spec: IHI0031C §5.2 — usado antes e depois da sequência JTAG→SWD.
        """
        full, rem = divmod(_LINE_RESET_BITS, 8)
        for _ in range(full):
            self._t.write_bits(0xFF, 8)
        if rem:
            self._t.write_bits((1 << rem) - 1, rem)
        self._t.write_bits(0x00, _IDLE_BITS)

    def jtag_to_swd(self) -> None:
        """Sequência completa de ativação SWD a partir de um estado JTAG.

        Sequência (IHI0031C §5.2.1):
            1. Line reset
            2. Magic 16-bit 0x9EE7 (LSB first)
            3. Line reset
            4. 8 ciclos idle (SWDIO=LOW)
        """
        self.line_reset()
        self._t.write_bits(_JTAG_TO_SWD_SEQ, 16)
        # segundo line reset (sem idle entre a sequência e o reset)
        full, rem = divmod(_LINE_RESET_BITS, 8)
        for _ in range(full):
            self._t.write_bits(0xFF, 8)
        if rem:
            self._t.write_bits((1 << rem) - 1, rem)
        self._t.write_bits(0x00, _IDLE_BITS)

    # ------------------------------------------------------------------
    # Acesso ao DP (Debug Port)
    # ------------------------------------------------------------------

    def read_dp(self, addr: int) -> int:
        """Lê um registrador do DP; retorna valor de 32 bits."""
        return self._read(apndp=0, addr=addr)

    def write_dp(self, addr: int, value: int) -> None:
        """Escreve um registrador do DP."""
        self._write(apndp=0, addr=addr, value=value)

    # ------------------------------------------------------------------
    # Acesso ao AP (Access Port)
    # ------------------------------------------------------------------

    def read_ap(self, addr: int) -> int:
        """Lê um registrador do AP selecionado em DP.SELECT."""
        return self._read(apndp=1, addr=addr)

    def write_ap(self, addr: int, value: int) -> None:
        """Escreve um registrador do AP selecionado em DP.SELECT."""
        self._write(apndp=1, addr=addr, value=value)

    # ------------------------------------------------------------------
    # Primitivas internas
    # ------------------------------------------------------------------

    def _read(self, apndp: int, addr: int) -> int:
        req = _build_request(apndp=apndp, rnw=1, addr=addr)
        self._t.write_bits(req, 8)

        ack = self._recv_ack()
        if ack != ACK_OK:
            self._t.turnaround()  # devolve controle do bus
            raise AckError(ack)

        data = self._t.read_bits(32)
        recv_par = self._t.read_bits(1)
        self._t.turnaround()  # host retoma controle

        exp_par = _even_parity(data)
        if recv_par != exp_par:
            raise ParityError(data, recv_par, exp_par)
        return data

    def _write(self, apndp: int, addr: int, value: int) -> None:
        req = _build_request(apndp=apndp, rnw=0, addr=addr)
        self._t.write_bits(req, 8)

        ack = self._recv_ack()
        self._t.turnaround()  # host retoma controle
        if ack != ACK_OK:
            raise AckError(ack)

        value &= _MASK32
        self._t.write_bits(value, 32)
        self._t.write_bits(_even_parity(value), 1)

    def _recv_ack(self) -> int:
        """Turnaround + leitura dos 3 bits de ACK."""
        self._t.turnaround()
        return self._t.read_bits(3)
