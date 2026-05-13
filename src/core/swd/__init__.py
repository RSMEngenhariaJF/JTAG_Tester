"""Protocolo SWD (Serial Wire Debug) — ARM ADIv5 IHI0031."""

from core.swd.errors import AckError, ParityError, SWDError
from core.swd.protocol import (
    ACK_FAULT,
    ACK_OK,
    ACK_WAIT,
    AP_ADDR_BASE,
    AP_ADDR_CSW,
    AP_ADDR_DRW,
    AP_ADDR_IDR,
    AP_ADDR_TAR,
    DP_ADDR_ABORT,
    DP_ADDR_CTRL_STAT,
    DP_ADDR_DPIDR,
    DP_ADDR_RDBUFF,
    DP_ADDR_SELECT,
    ITransport,
    SWDProtocol,
)

__all__ = [
    "ACK_FAULT",
    "ACK_OK",
    "ACK_WAIT",
    "AP_ADDR_BASE",
    "AP_ADDR_CSW",
    "AP_ADDR_DRW",
    "AP_ADDR_IDR",
    "AP_ADDR_TAR",
    "DP_ADDR_ABORT",
    "DP_ADDR_CTRL_STAT",
    "DP_ADDR_DPIDR",
    "DP_ADDR_RDBUFF",
    "DP_ADDR_SELECT",
    "AckError",
    "ITransport",
    "ParityError",
    "SWDError",
    "SWDProtocol",
]
