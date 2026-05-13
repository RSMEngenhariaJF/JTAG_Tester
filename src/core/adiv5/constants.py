"""Constantes ADIv5 — ARM Debug Interface Architecture Specification."""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Endereços de registradores ARM Cortex-M (memory-mapped)
# ---------------------------------------------------------------------------

DHCSR: Final[int] = 0xE000_EDF0  # Debug Halting Control/Status Register
DCRSR: Final[int] = 0xE000_EDF4  # Debug Core Register Select Register
DCRDR: Final[int] = 0xE000_EDF8  # Debug Core Register Data Register
AIRCR: Final[int] = 0xE000_ED0C  # Application Interrupt/Reset Control Register

# ---------------------------------------------------------------------------
# DHCSR bits
# ---------------------------------------------------------------------------

DHCSR_DBGKEY: Final[int] = 0xA05F_0000  # Chave de escrita (bits 31:16)
DHCSR_C_DEBUGEN: Final[int] = 1 << 0  # Enable debug
DHCSR_C_HALT: Final[int] = 1 << 1  # Halt the core
DHCSR_C_STEP: Final[int] = 1 << 2  # Single-step
DHCSR_S_REGRDY: Final[int] = 1 << 16  # Register transfer complete (read-only)
DHCSR_S_HALT: Final[int] = 1 << 17  # Core is halted (read-only)
DHCSR_S_LOCKUP: Final[int] = 1 << 19  # Core is locked up (read-only)

# ---------------------------------------------------------------------------
# DCRSR bits
# ---------------------------------------------------------------------------

DCRSR_REGWNR: Final[int] = 1 << 16  # 1=write, 0=read core register

# ---------------------------------------------------------------------------
# AIRCR bits
# ---------------------------------------------------------------------------

AIRCR_VECTKEY: Final[int] = 0x05FA_0000  # Chave de escrita (bits 31:16)
AIRCR_SYSRESETREQ: Final[int] = 1 << 2  # System reset request

# ---------------------------------------------------------------------------
# DP CTRL/STAT power-up bits
# ---------------------------------------------------------------------------

CTRL_CSYSPWRUPREQ: Final[int] = 1 << 31  # System power-up request
CTRL_CDBGPWRUPREQ: Final[int] = 1 << 30  # Debug power-up request
CTRL_CSYSPWRUPACK: Final[int] = 1 << 29  # System power-up acknowledge (read-only)
CTRL_CDBGPWRUPACK: Final[int] = 1 << 28  # Debug power-up acknowledge (read-only)

# ---------------------------------------------------------------------------
# Core register indices (ARM Cortex-M)
# ---------------------------------------------------------------------------

REG_R0: Final[int] = 0
REG_R1: Final[int] = 1
REG_R2: Final[int] = 2
REG_R3: Final[int] = 3
REG_R12: Final[int] = 12
REG_SP: Final[int] = 13
REG_LR: Final[int] = 14
REG_PC: Final[int] = 15
REG_XPSR: Final[int] = 16
