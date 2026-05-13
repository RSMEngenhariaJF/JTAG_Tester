"""Adaptador FT2232H — transporte SWD físico via pyftdi MPSSE."""

from adapters.ft2232h.detector import FT2232HDevice, list_devices
from adapters.ft2232h.transport import FT2232HTransport

__all__ = ["FT2232HDevice", "FT2232HTransport", "list_devices"]
