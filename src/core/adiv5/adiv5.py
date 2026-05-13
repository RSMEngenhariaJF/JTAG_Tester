"""Camada ADIv5 sobre SWDProtocol — acesso a memória e debug de núcleo ARM.

Implementa operações de alto nível usando o protocolo SWD bit-a-bit:
    - Inicialização do debug domain (power-up, DPIDR)
    - Leitura/escrita de memória de 32 bits via MEM-AP
    - Halt / resume / single-step
    - Leitura/escrita de registradores de núcleo (R0-R15, xPSR)
    - Reset de sistema via AIRCR

Referências:
    IHI0031C — ARM Debug Interface Architecture Specification ADIv5
    DDI0337H — Cortex-M3 Technical Reference Manual (DHCSR, DCRSR, DCRDR)
"""

from __future__ import annotations

from core.adiv5.constants import (
    AIRCR,
    AIRCR_SYSRESETREQ,
    AIRCR_VECTKEY,
    CTRL_CDBGPWRUPACK,
    CTRL_CDBGPWRUPREQ,
    CTRL_CSYSPWRUPACK,
    CTRL_CSYSPWRUPREQ,
    DCRDR,
    DCRSR,
    DCRSR_REGWNR,
    DHCSR,
    DHCSR_C_DEBUGEN,
    DHCSR_C_HALT,
    DHCSR_DBGKEY,
    DHCSR_S_HALT,
    DHCSR_S_REGRDY,
)
from core.swd.protocol import (
    AP_ADDR_DRW,
    AP_ADDR_TAR,
    DP_ADDR_CTRL_STAT,
    DP_ADDR_DPIDR,
    DP_ADDR_RDBUFF,
    DP_ADDR_SELECT,
    SWDProtocol,
)


class DebugPowerError(Exception):
    """Debug domain não respondeu ao power-up dentro do timeout."""


class ADIv5:
    """Interface ADIv5 de alto nível sobre SWDProtocol.

    Uso:
        transport = FT2232HTransport(...)   # ou SimulatedSWDTransport
        proto     = SWDProtocol(transport)
        adiv5     = ADIv5(proto)
        dpidr     = adiv5.init()
        adiv5.halt()
        pc = adiv5.read_core_register(REG_PC)
    """

    _POWERUP_TIMEOUT: int = 100

    def __init__(self, protocol: SWDProtocol) -> None:
        self._p = protocol

    # ------------------------------------------------------------------
    # Inicialização
    # ------------------------------------------------------------------

    def init(self) -> int:
        """Inicializa a conexão de debug; retorna o valor de DPIDR."""
        self._p.line_reset()
        dpidr = self._p.read_dp(DP_ADDR_DPIDR)
        self._power_up()
        self._p.write_dp(DP_ADDR_SELECT, 0x00)  # AP 0, banco 0
        return dpidr

    def _power_up(self) -> None:
        ctrl = CTRL_CSYSPWRUPREQ | CTRL_CDBGPWRUPREQ
        self._p.write_dp(DP_ADDR_CTRL_STAT, ctrl)
        acks = CTRL_CSYSPWRUPACK | CTRL_CDBGPWRUPACK
        for _ in range(self._POWERUP_TIMEOUT):
            if self._p.read_dp(DP_ADDR_CTRL_STAT) & acks:
                return
        raise DebugPowerError("Debug power-up não reconhecido pelo target")

    # ------------------------------------------------------------------
    # Acesso a memória (MEM-AP)
    # ------------------------------------------------------------------

    def read_mem32(self, addr: int) -> int:
        """Lê 32 bits do endereço byte `addr` via MEM-AP (posted read)."""
        self._set_tar(addr)
        self._p.read_ap(AP_ADDR_DRW)  # leitura postada — resultado vai para RDBUFF
        return self._p.read_dp(DP_ADDR_RDBUFF)

    def write_mem32(self, addr: int, value: int) -> None:
        """Escreve 32 bits no endereço byte `addr` via MEM-AP."""
        self._set_tar(addr)
        self._p.write_ap(AP_ADDR_DRW, value)

    def _set_tar(self, addr: int) -> None:
        self._p.write_dp(DP_ADDR_SELECT, 0x00)  # AP 0, banco 0
        self._p.write_ap(AP_ADDR_TAR, addr)

    # ------------------------------------------------------------------
    # Controle de execução
    # ------------------------------------------------------------------

    def halt(self) -> None:
        """Para o núcleo CPU."""
        self.write_mem32(DHCSR, DHCSR_DBGKEY | DHCSR_C_DEBUGEN | DHCSR_C_HALT)

    def resume(self) -> None:
        """Retoma a execução do núcleo CPU."""
        self.write_mem32(DHCSR, DHCSR_DBGKEY | DHCSR_C_DEBUGEN)

    def is_halted(self) -> bool:
        """Retorna True se o núcleo estiver parado."""
        return bool(self.read_mem32(DHCSR) & DHCSR_S_HALT)

    def step(self) -> None:
        """Executa um único passo de instrução."""
        self.write_mem32(DHCSR, DHCSR_DBGKEY | DHCSR_C_DEBUGEN | DHCSR_C_HALT | (1 << 2))

    # ------------------------------------------------------------------
    # Reset de sistema
    # ------------------------------------------------------------------

    def reset_system(self) -> None:
        """Solicita reset de sistema via AIRCR (SYSRESETREQ)."""
        self.write_mem32(AIRCR, AIRCR_VECTKEY | AIRCR_SYSRESETREQ)

    # ------------------------------------------------------------------
    # Registradores de núcleo
    # ------------------------------------------------------------------

    def read_core_register(self, reg: int) -> int:
        """Lê o registrador de núcleo `reg` (0=R0 … 15=PC, 16=xPSR)."""
        self.write_mem32(DCRSR, reg & 0x1F)
        self._wait_regrdy()
        return self.read_mem32(DCRDR)

    def write_core_register(self, reg: int, value: int) -> None:
        """Escreve `value` no registrador de núcleo `reg`."""
        self.write_mem32(DCRDR, value)
        self.write_mem32(DCRSR, DCRSR_REGWNR | (reg & 0x1F))
        self._wait_regrdy()

    def _wait_regrdy(self) -> None:
        for _ in range(self._POWERUP_TIMEOUT):
            if self.read_mem32(DHCSR) & DHCSR_S_REGRDY:
                return
        raise TimeoutError("S_REGRDY não foi sinalizado pelo target")
