"""Simuladores de hardware para desenvolvimento e CI sem hardware físico."""

from sim.simulated_probe import SimulatedProbe
from sim.swd_transport import SimulatedSWDTransport

__all__ = ["SimulatedProbe", "SimulatedSWDTransport"]
