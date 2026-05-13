"""SimulatedSWDTransport — implementação de ITransport sobre SimulatedProbe.

Traduz o fluxo de bits SWD (write_bits / read_bits / turnaround) em chamadas
de alto nível no SimulatedProbe, permitindo testar ADIv5 end-to-end sem hardware.

Máquina de estados:
    IDLE
      ├─ write_bits(0xFF, 8)   → acumula high bits (line reset)
      ├─ write_bits(0x00, 8)   → se ≥50 high bits acumulados: swd_line_reset()
      ├─ write_bits(0x9EE7,16) → magic JTAG→SWD, ignora
      └─ write_bits(req, 8)    → request válido → RECV_TRN

    RECV_TRN
      └─ turnaround()          → SEND_ACK

    SEND_ACK
      └─ read_bits(3)          → retorna ACK_OK; se leitura → SEND_DATA; se escrita → WAIT_WRITE_TRN

    SEND_DATA
      └─ read_bits(32)         → retorna dados → SEND_PARITY

    SEND_PARITY
      └─ read_bits(1)          → retorna paridade → AFTER_DATA_TRN

    AFTER_DATA_TRN
      └─ turnaround()          → IDLE

    WAIT_WRITE_TRN
      └─ turnaround()          → RECV_WRITE_DATA

    RECV_WRITE_DATA
      └─ write_bits(value, 32) → RECV_WRITE_PARITY

    RECV_WRITE_PARITY
      └─ write_bits(parity, 1) → executa escrita → IDLE
"""

from __future__ import annotations

from typing import Final

from sim.simulated_probe import SimulatedProbe

# ---------------------------------------------------------------------------
# Constantes de protocolo
# ---------------------------------------------------------------------------

_ACK_OK: Final[int] = 0b001
_LINE_RESET_MIN_BITS: Final[int] = 50

# Máscara para detectar byte de request válido: start=1, stop=0, park=1
_REQ_MASK: Final[int] = 0xC1
_REQ_EXPECTED: Final[int] = 0x81

# Mapa addr → nome de registrador para DP (leitura)
_DP_READ_REGS: Final[dict[int, str]] = {
    0x00: "DPIDR",
    0x04: "CTRL/STAT",
    0x08: "RDBUFF",  # RESEND — retorna RDBUFF no simulador
    0x0C: "RDBUFF",
}

# Mapa addr → nome de registrador para DP (escrita)
_DP_WRITE_REGS: Final[dict[int, str]] = {
    0x04: "CTRL/STAT",
    0x08: "SELECT",
}

# Mapa full_addr → nome de registrador para AP 0
_AP0_REGS: Final[dict[int, str]] = {
    0x00: "CSW",
    0x04: "TAR",
    0x0C: "DRW",
    0xFC: "IDR",
}


def _even_parity(value: int, bits: int = 32) -> int:
    p = 0
    for _ in range(bits):
        p ^= value & 1
        value >>= 1
    return p


# ---------------------------------------------------------------------------
# SimulatedSWDTransport
# ---------------------------------------------------------------------------


class SimulatedSWDTransport:
    """ITransport que executa operações SWD sobre um SimulatedProbe.

    Uso típico:
        probe = SimulatedProbe()
        transport = SimulatedSWDTransport(probe)
        protocol = SWDProtocol(transport)
        adiv5 = ADIv5(protocol)
        adiv5.init()
    """

    def __init__(self, probe: SimulatedProbe) -> None:
        self._probe = probe
        self._state: str = "IDLE"
        self._high_bits: int = 0

        # Campos preenchidos ao processar o request
        self._apndp: int = 0
        self._rnw: int = 0
        self._addr: int = 0  # endereço de 2 bits expandido: 0x00/0x04/0x08/0x0C
        self._dp_select: int = 0  # cópia local do DP.SELECT para resolver banco AP

        # Resultado da operação de leitura
        self._read_data: int = 0
        self._read_parity: int = 0

        # Dado recebido durante escrita
        self._write_data: int = 0

    # ------------------------------------------------------------------
    # ITransport
    # ------------------------------------------------------------------

    def write_bits(self, value: int, count: int) -> None:
        v = value & ((1 << count) - 1)

        if self._state == "IDLE":
            self._handle_idle_write(v, count)
        elif self._state == "RECV_WRITE_DATA" and count == 32:
            self._write_data = v
            self._state = "RECV_WRITE_PARITY"
        elif self._state == "RECV_WRITE_PARITY" and count == 1:
            self._execute_write()
            self._state = "IDLE"

    def read_bits(self, count: int) -> int:
        if self._state == "SEND_ACK" and count == 3:
            return self._handle_send_ack()
        if self._state == "SEND_DATA" and count == 32:
            self._state = "SEND_PARITY"
            return self._read_data
        if self._state == "SEND_PARITY" and count == 1:
            self._state = "AFTER_DATA_TRN"
            return self._read_parity
        return 0

    def turnaround(self) -> None:
        if self._state == "RECV_TRN":
            self._state = "SEND_ACK"
        elif self._state == "AFTER_DATA_TRN":
            self._state = "IDLE"
        elif self._state == "WAIT_WRITE_TRN":
            self._state = "RECV_WRITE_DATA"

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _handle_idle_write(self, v: int, count: int) -> None:
        if count == 8:
            if v == 0xFF:
                self._high_bits += 8
            elif v == 0x00:
                if self._high_bits >= _LINE_RESET_MIN_BITS:
                    self._probe.swd_line_reset()
                self._high_bits = 0
            elif (v & _REQ_MASK) == _REQ_EXPECTED:
                self._parse_request(v)
                self._state = "RECV_TRN"
                self._high_bits = 0
            else:
                self._high_bits = 0
        elif count == 16:
            # Magic JTAG→SWD sequence — ignorar
            self._high_bits = 0

    def _parse_request(self, req: int) -> None:
        self._apndp = (req >> 1) & 1
        self._rnw = (req >> 2) & 1
        a2 = (req >> 3) & 1
        a3 = (req >> 4) & 1
        self._addr = (a3 << 3) | (a2 << 2)  # 0x00, 0x04, 0x08, or 0x0C

    def _handle_send_ack(self) -> int:
        if self._rnw:
            self._read_data, self._read_parity = self._execute_read()
            self._state = "SEND_DATA"
        else:
            self._state = "WAIT_WRITE_TRN"
        return _ACK_OK

    def _ap_full_addr(self) -> int:
        bank = (self._dp_select >> 4) & 0xF
        return (bank << 4) | self._addr

    def _execute_read(self) -> tuple[int, int]:
        if self._apndp == 0:
            reg = _DP_READ_REGS.get(self._addr, "RDBUFF")
            data = self._probe.read_dp(reg)
        else:
            ap = (self._dp_select >> 24) & 0xFF
            reg = _AP0_REGS.get(self._ap_full_addr(), "DRW")
            data = self._probe.read_ap(ap, reg)
        return data & 0xFFFF_FFFF, _even_parity(data)

    def _execute_write(self) -> None:
        value = self._write_data & 0xFFFF_FFFF
        if self._apndp == 0:
            reg = _DP_WRITE_REGS.get(self._addr)
            if reg is None:
                return  # ABORT e outros — ignorar no simulador
            if reg == "SELECT":
                self._dp_select = value
            self._probe.write_dp(reg, value)
        else:
            ap = (self._dp_select >> 24) & 0xFF
            reg = _AP0_REGS.get(self._ap_full_addr(), "DRW")
            self._probe.write_ap(ap, reg, value)
