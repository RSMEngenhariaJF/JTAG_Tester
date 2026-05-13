"""Probe simulado — suporta SWD e JTAG sem hardware físico.

SWD:  modela DP (Debug Port) e um MEM-AP (Access Port 0).
JTAG: modela uma cadeia de até N dispositivos com IR/DR por dispositivo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Final

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

DP_BANK_SEL_MASK: Final[int] = 0xF0
AP_SEL_MASK: Final[int] = 0xFF000000
AP_BANKSEL_MASK: Final[int] = 0x00F00000

_32BIT: Final[int] = 0xFFFF_FFFF

# ARM Cortex-M debug register addresses (byte-addressed)
_DHCSR: Final[int] = 0xE000_EDF0  # Debug Halting Control/Status
_DCRSR: Final[int] = 0xE000_EDF4  # Debug Core Register Select
_DCRDR: Final[int] = 0xE000_EDF8  # Debug Core Register Data
_AIRCR: Final[int] = 0xE000_ED0C  # Application Interrupt/Reset Control

_DHCSR_DBGKEY: Final[int] = 0xA05F_0000
_DHCSR_C_DEBUGEN: Final[int] = 1 << 0
_DHCSR_C_HALT: Final[int] = 1 << 1
_DHCSR_S_REGRDY: Final[int] = 1 << 16
_DHCSR_S_HALT: Final[int] = 1 << 17

_AIRCR_VECTKEY: Final[int] = 0x05FA_0000
_AIRCR_SYSRESETREQ: Final[int] = 1 << 2

_DCRSR_REGWNR: Final[int] = 1 << 16

# DP CTRL/STAT power-up bits
_CTRL_CSYSPWRUPREQ: Final[int] = 1 << 31
_CTRL_CDBGPWRUPREQ: Final[int] = 1 << 30
_CTRL_CSYSPWRUPACK: Final[int] = 1 << 29
_CTRL_CDBGPWRUPACK: Final[int] = 1 << 28


# ---------------------------------------------------------------------------
# SWD — tipos auxiliares
# ---------------------------------------------------------------------------


class AckError(Exception):
    """Levantada quando o DP retorna WAIT ou FAULT."""


class _Ack(Enum):
    OK = auto()
    WAIT = auto()
    FAULT = auto()


# ---------------------------------------------------------------------------
# Representação de um dispositivo na cadeia JTAG
# ---------------------------------------------------------------------------


@dataclass
class _JTAGDevice:
    idcode: int
    ir_length: int = 4
    _ir: int = field(default=0b1111, init=False)  # BYPASS por padrão
    _dr: int = field(default=0, init=False)

    # instruções conhecidas
    BYPASS: Final[int] = field(default=0b1111, init=False)
    IDCODE: Final[int] = field(default=0b0001, init=False)

    def shift_ir(self, new_ir: int) -> int:
        captured = self._ir
        self._ir = new_ir & ((1 << self.ir_length) - 1)
        return captured

    def shift_dr(self, tdi_bits: int, length: int) -> int:
        if self._ir == self.IDCODE:
            captured = self.idcode
            self._dr = tdi_bits & _32BIT
            return captured
        # BYPASS: DR é 1 bit, passa TDI direto
        captured = self._dr & 1
        self._dr = (tdi_bits >> (length - 1)) & 1
        return captured


# ---------------------------------------------------------------------------
# SimulatedProbe
# ---------------------------------------------------------------------------


class SimulatedProbe:
    """Probe simulado com suporte a SWD e JTAG.

    Parâmetros SWD
    --------------
    dpidr       : valor retornado em leituras do registrador DPIDR.
    ap0_idr     : valor retornado em leituras do IDR do AP 0 (MEM-AP).
    memory      : dicionário {endereço: valor} pré-populado (word-addressed).

    Parâmetros JTAG
    ---------------
    jtag_chain  : lista de IDCODEs dos dispositivos na cadeia (TDI→TDO).
    ir_length   : comprimento do IR de cada dispositivo (mesmo valor para todos,
                  ou lista com comprimento por dispositivo).
    """

    # ------------------------------------------------------------------
    # Construção
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        dpidr: int = 0x2BA0_1477,
        ap0_idr: int = 0x2477_0021,
        memory: dict[int, int] | None = None,
        jtag_chain: list[int] | None = None,
        ir_length: int | list[int] = 4,
    ) -> None:
        # --- SWD DP registers ---
        self._dpidr: int = dpidr & _32BIT
        self._dp_ctrl_stat: int = 0x0000_0000
        self._dp_select: int = 0x0000_0000
        self._dp_rdbuff: int = 0x0000_0000

        # --- SWD AP 0 (MEM-AP) registers ---
        self._ap0_idr: int = ap0_idr & _32BIT
        self._ap0_csw: int = 0x2300_0052
        self._ap0_tar: int = 0x0000_0000

        # --- memória simulada (word-addressed) ---
        self._memory: dict[int, int] = {k: v & _32BIT for k, v in (memory or {}).items()}

        # --- estado SWD genérico ---
        self._swd_connected: bool = False
        self._fault: bool = False

        # --- ARM debug state ---
        self._cpu_halted: bool = False
        self._core_registers: dict[int, int] = {}  # reg index → value
        self._dcrdr: int = 0
        self._reset_count: int = 0

        # --- JTAG chain ---
        idcodes = jtag_chain or [0x0BA0_0477]
        ir_lens: list[int] = (
            [ir_length] * len(idcodes) if isinstance(ir_length, int) else list(ir_length)
        )
        self._devices: list[_JTAGDevice] = [
            _JTAGDevice(idcode=idc & _32BIT, ir_length=irl)
            for idc, irl in zip(idcodes, ir_lens, strict=True)
        ]
        self._tap_state: str = "TEST_LOGIC_RESET"

    # ------------------------------------------------------------------
    # SWD — interface pública
    # ------------------------------------------------------------------

    def swd_line_reset(self) -> None:
        """Simula reset de linha SWD (≥ 50 ciclos SWDCLK high)."""
        self._swd_connected = True
        self._fault = False
        self._dp_ctrl_stat = 0x0000_0000

    def read_dp(self, reg: str) -> int:
        """Lê um registrador do Debug Port.

        Registradores suportados: 'DPIDR', 'CTRL/STAT', 'SELECT', 'RDBUFF'.
        """
        self._check_swd_connected()
        match reg:
            case "DPIDR":
                return self._dpidr
            case "CTRL/STAT":
                return self._dp_ctrl_stat
            case "SELECT":
                return self._dp_select
            case "RDBUFF":
                return self._dp_rdbuff
            case _:
                raise ValueError(f"DP register desconhecido: {reg!r}")

    def write_dp(self, reg: str, value: int) -> None:
        """Escreve um registrador do Debug Port."""
        self._check_swd_connected()
        value &= _32BIT
        match reg:
            case "CTRL/STAT":
                # Auto-acknowledge power-up requests (bits are read-only in hardware)
                stored = value & ~(_CTRL_CSYSPWRUPACK | _CTRL_CDBGPWRUPACK)
                if value & _CTRL_CSYSPWRUPREQ:
                    stored |= _CTRL_CSYSPWRUPACK
                if value & _CTRL_CDBGPWRUPREQ:
                    stored |= _CTRL_CDBGPWRUPACK
                self._dp_ctrl_stat = stored
            case "SELECT":
                self._dp_select = value
            case _:
                raise ValueError(f"DP register não gravável ou desconhecido: {reg!r}")

    def read_ap(self, ap: int, reg: str) -> int:
        """Lê um registrador de um Access Port.

        Apenas AP 0 (MEM-AP) está implementado.
        """
        self._check_swd_connected()
        if ap != 0:
            raise NotImplementedError(f"AP {ap} não simulado")
        match reg:
            case "IDR":
                return self._ap0_idr
            case "CSW":
                return self._ap0_csw
            case "TAR":
                return self._ap0_tar
            case "DRW":
                # Posted read: load new value into RDBUFF, return previous RDBUFF
                new_val = self._mem_read(self._ap0_tar)
                old_rdbuff = self._dp_rdbuff
                self._dp_rdbuff = new_val
                return old_rdbuff
            case _:
                raise ValueError(f"AP register desconhecido: {reg!r}")

    def write_ap(self, ap: int, reg: str, value: int) -> None:
        """Escreve um registrador de um Access Port."""
        self._check_swd_connected()
        if ap != 0:
            raise NotImplementedError(f"AP {ap} não simulado")
        value &= _32BIT
        match reg:
            case "CSW":
                self._ap0_csw = value
            case "TAR":
                self._ap0_tar = value
            case "DRW":
                self._mem_write(self._ap0_tar, value)
            case _:
                raise ValueError(f"AP register não gravável ou desconhecido: {reg!r}")

    def read_memory_word(self, address: int) -> int:
        """Lê uma word (32 bits) da memória simulada pelo endereço byte."""
        self._check_swd_connected()
        return self._memory.get(address >> 2, 0)

    def write_memory_word(self, address: int, value: int) -> None:
        """Escreve uma word (32 bits) na memória simulada pelo endereço byte."""
        self._check_swd_connected()
        self._memory[address >> 2] = value & _32BIT

    # ------------------------------------------------------------------
    # JTAG — interface pública
    # ------------------------------------------------------------------

    def tap_reset(self) -> None:
        """Leva o TAP para TEST-LOGIC-RESET."""
        self._tap_state = "TEST_LOGIC_RESET"
        for dev in self._devices:
            dev._ir = dev.BYPASS

    def shift_ir(self, new_ir: int, device: int = 0) -> int:
        """Carrega nova instrução no IR do dispositivo; retorna IR capturado."""
        self._tap_state = "SHIFT_IR"
        captured = self._devices[device].shift_ir(new_ir)
        self._tap_state = "RUN_TEST_IDLE"
        return captured

    def shift_dr(self, tdi: int, length: int, device: int = 0) -> int:
        """Faz shift do DR; retorna bits capturados (TDO)."""
        self._tap_state = "SHIFT_DR"
        captured = self._devices[device].shift_dr(tdi, length)
        self._tap_state = "RUN_TEST_IDLE"
        return captured

    def read_idcode(self, device: int = 0) -> int:
        """Carrega instrução IDCODE e faz shift-DR; retorna IDCODE do dispositivo."""
        self.shift_ir(self._devices[device].IDCODE, device=device)
        return self.shift_dr(0, 32, device=device)

    @property
    def chain_length(self) -> int:
        """Número de dispositivos na cadeia JTAG."""
        return len(self._devices)

    @property
    def tap_state(self) -> str:
        """Estado atual do TAP (simplificado)."""
        return self._tap_state

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _check_swd_connected(self) -> None:
        if not self._swd_connected:
            raise RuntimeError("SWD não inicializado — chame swd_line_reset() primeiro")

    def _mem_read(self, byte_addr: int) -> int:
        """Lê da memória simulada ou de debug register especial."""
        if byte_addr == _DHCSR:
            val = _DHCSR_S_REGRDY  # S_REGRDY sempre disponível
            if self._cpu_halted:
                val |= _DHCSR_S_HALT
            return val
        if byte_addr == _DCRDR:
            return self._dcrdr & _32BIT
        if byte_addr == _AIRCR:
            return 0xFA05_0000  # VECTKEY reads as 0xFA05
        return self._memory.get(byte_addr >> 2, 0)

    def _mem_write(self, byte_addr: int, value: int) -> None:
        """Escreve na memória simulada ou em debug register especial."""
        if byte_addr == _DHCSR:
            if (value & 0xFFFF_0000) == _DHCSR_DBGKEY:
                self._cpu_halted = bool(value & _DHCSR_C_HALT)
            return
        if byte_addr == _DCRSR:
            reg = value & 0x1F
            if value & _DCRSR_REGWNR:  # write to core register
                self._core_registers[reg] = self._dcrdr & _32BIT
            else:  # read core register into DCRDR
                self._dcrdr = self._core_registers.get(reg, 0)
            return
        if byte_addr == _DCRDR:
            self._dcrdr = value & _32BIT
            return
        if byte_addr == _AIRCR:
            if (value & 0xFFFF_0000) == _AIRCR_VECTKEY and value & _AIRCR_SYSRESETREQ:
                self._reset_count += 1
                self._cpu_halted = False
            return
        self._memory[byte_addr >> 2] = value & _32BIT
