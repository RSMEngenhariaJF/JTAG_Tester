"""Fixtures compartilhadas entre todos os níveis de teste."""

from __future__ import annotations

import pytest

from sim.simulated_probe import SimulatedProbe


@pytest.fixture()
def probe() -> SimulatedProbe:
    """Probe SWD padrão já inicializado (swd_line_reset chamado)."""
    p = SimulatedProbe()
    p.swd_line_reset()
    return p


@pytest.fixture()
def probe_raw() -> SimulatedProbe:
    """Probe sem swd_line_reset — para testar estado não inicializado."""
    return SimulatedProbe()


@pytest.fixture()
def probe_jtag() -> SimulatedProbe:
    """Probe JTAG com cadeia de 2 dispositivos."""
    return SimulatedProbe(jtag_chain=[0x0BA0_0477, 0x2BA0_1477])


@pytest.fixture()
def probe_with_memory() -> SimulatedProbe:
    """Probe SWD com memória pré-populada."""
    p = SimulatedProbe(memory={0x0: 0xDEAD_BEEF, 0x1: 0xCAFE_BABE})
    p.swd_line_reset()
    return p
