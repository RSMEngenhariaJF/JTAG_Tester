"""Testes de integração ADIv5 — exercita a pilha completa:
    ADIv5 → SWDProtocol → SimulatedSWDTransport → SimulatedProbe.

Não há hardware: todas as operações são simuladas em memória.
"""

from __future__ import annotations

import pytest

from core.adiv5.adiv5 import ADIv5
from core.adiv5.constants import REG_PC, REG_R0
from core.swd.protocol import SWDProtocol
from sim.simulated_probe import SimulatedProbe
from sim.swd_transport import SimulatedSWDTransport

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def probe() -> SimulatedProbe:
    return SimulatedProbe()


@pytest.fixture()
def transport(probe: SimulatedProbe) -> SimulatedSWDTransport:
    return SimulatedSWDTransport(probe)


@pytest.fixture()
def adiv5(transport: SimulatedSWDTransport) -> ADIv5:
    proto = SWDProtocol(transport)
    adiv5 = ADIv5(proto)
    adiv5.init()
    return adiv5


@pytest.fixture()
def adiv5_with_memory() -> ADIv5:
    probe = SimulatedProbe(
        memory={
            0x2000_0000 >> 2: 0xDEAD_BEEF,
            0x2000_0004 >> 2: 0xCAFE_BABE,
        }
    )
    transport = SimulatedSWDTransport(probe)
    proto = SWDProtocol(transport)
    a = ADIv5(proto)
    a.init()
    return a


# ===========================================================================
# Inicialização
# ===========================================================================


class TestInit:
    def test_returns_dpidr(self, transport: SimulatedSWDTransport) -> None:
        proto = SWDProtocol(transport)
        adiv5 = ADIv5(proto)
        dpidr = adiv5.init()
        assert dpidr == 0x2BA0_1477

    def test_custom_dpidr(self) -> None:
        probe = SimulatedProbe(dpidr=0x0BC1_1477)
        transport = SimulatedSWDTransport(probe)
        adiv5 = ADIv5(SWDProtocol(transport))
        assert adiv5.init() == 0x0BC1_1477

    def test_init_powers_up_debug_domain(self, adiv5: ADIv5) -> None:
        # Após init(), CTRL/STAT deve ter bits de ack de power-up
        from core.adiv5.constants import CTRL_CDBGPWRUPACK, CTRL_CSYSPWRUPACK

        stat = adiv5._p.read_dp(0x04)  # DP_ADDR_CTRL_STAT
        assert stat & (CTRL_CSYSPWRUPACK | CTRL_CDBGPWRUPACK)


# ===========================================================================
# Leitura/escrita de memória
# ===========================================================================


class TestMemoryAccess:
    def test_write_and_read_mem32(self, adiv5: ADIv5) -> None:
        adiv5.write_mem32(0x2000_0000, 0x1234_5678)
        assert adiv5.read_mem32(0x2000_0000) == 0x1234_5678

    def test_read_prepopulated_memory(self, adiv5_with_memory: ADIv5) -> None:
        assert adiv5_with_memory.read_mem32(0x2000_0000) == 0xDEAD_BEEF
        assert adiv5_with_memory.read_mem32(0x2000_0004) == 0xCAFE_BABE

    def test_read_uninitialised_returns_zero(self, adiv5: ADIv5) -> None:
        assert adiv5.read_mem32(0x1000_0000) == 0

    def test_write_truncates_to_32bit(self, adiv5: ADIv5) -> None:
        adiv5.write_mem32(0x2000_0000, 0x1_FFFF_FFFF)
        assert adiv5.read_mem32(0x2000_0000) == 0xFFFF_FFFF

    def test_multiple_writes_independent_addresses(self, adiv5: ADIv5) -> None:
        adiv5.write_mem32(0x2000_0000, 0xAAAA_AAAA)
        adiv5.write_mem32(0x2000_0004, 0xBBBB_BBBB)
        assert adiv5.read_mem32(0x2000_0000) == 0xAAAA_AAAA
        assert adiv5.read_mem32(0x2000_0004) == 0xBBBB_BBBB

    def test_overwrite_memory(self, adiv5: ADIv5) -> None:
        adiv5.write_mem32(0x2000_0000, 0x1111_1111)
        adiv5.write_mem32(0x2000_0000, 0x2222_2222)
        assert adiv5.read_mem32(0x2000_0000) == 0x2222_2222

    def test_zero_value(self, adiv5: ADIv5) -> None:
        adiv5.write_mem32(0x2000_0000, 0xFFFF_FFFF)
        adiv5.write_mem32(0x2000_0000, 0x0000_0000)
        assert adiv5.read_mem32(0x2000_0000) == 0


# ===========================================================================
# Controle de execução
# ===========================================================================


class TestHaltResume:
    def test_initially_not_halted(self, adiv5: ADIv5) -> None:
        assert not adiv5.is_halted()

    def test_halt_sets_halted(self, adiv5: ADIv5) -> None:
        adiv5.halt()
        assert adiv5.is_halted()

    def test_resume_clears_halted(self, adiv5: ADIv5) -> None:
        adiv5.halt()
        adiv5.resume()
        assert not adiv5.is_halted()

    def test_multiple_halts_idempotent(self, adiv5: ADIv5) -> None:
        adiv5.halt()
        adiv5.halt()
        assert adiv5.is_halted()

    def test_resume_when_running_is_noop(self, adiv5: ADIv5) -> None:
        adiv5.resume()
        assert not adiv5.is_halted()


# ===========================================================================
# Reset de sistema
# ===========================================================================


class TestSystemReset:
    def test_reset_increments_counter(self, adiv5: ADIv5, probe: SimulatedProbe) -> None:
        adiv5.reset_system()
        assert probe._reset_count == 1

    def test_reset_clears_halt(self, adiv5: ADIv5) -> None:
        adiv5.halt()
        adiv5.reset_system()
        assert not adiv5.is_halted()

    def test_multiple_resets(self, adiv5: ADIv5, probe: SimulatedProbe) -> None:
        adiv5.reset_system()
        adiv5.reset_system()
        assert probe._reset_count == 2


# ===========================================================================
# Registradores de núcleo
# ===========================================================================


class TestCoreRegisters:
    def test_write_and_read_r0(self, adiv5: ADIv5) -> None:
        adiv5.write_core_register(REG_R0, 0xDEAD_BEEF)
        assert adiv5.read_core_register(REG_R0) == 0xDEAD_BEEF

    def test_write_and_read_pc(self, adiv5: ADIv5) -> None:
        adiv5.write_core_register(REG_PC, 0x0800_0100)
        assert adiv5.read_core_register(REG_PC) == 0x0800_0100

    def test_registers_are_independent(self, adiv5: ADIv5) -> None:
        adiv5.write_core_register(REG_R0, 0x1111_1111)
        adiv5.write_core_register(REG_PC, 0x0800_1000)
        assert adiv5.read_core_register(REG_R0) == 0x1111_1111
        assert adiv5.read_core_register(REG_PC) == 0x0800_1000

    def test_uninitialised_register_returns_zero(self, adiv5: ADIv5) -> None:
        assert adiv5.read_core_register(REG_R0) == 0

    def test_write_core_register_truncates_to_32bit(self, adiv5: ADIv5) -> None:
        adiv5.write_core_register(REG_R0, 0x1_ABCD_EFFF)
        assert adiv5.read_core_register(REG_R0) == 0xABCD_EFFF


# ===========================================================================
# Pilha completa — cenários de uso reais
# ===========================================================================


class TestEndToEnd:
    def test_halt_inspect_resume_flow(self, adiv5: ADIv5) -> None:
        adiv5.write_core_register(REG_PC, 0x0800_0200)
        adiv5.halt()
        assert adiv5.is_halted()
        pc = adiv5.read_core_register(REG_PC)
        assert pc == 0x0800_0200
        adiv5.resume()
        assert not adiv5.is_halted()

    def test_write_memory_halt_read_back(self, adiv5: ADIv5) -> None:
        adiv5.write_mem32(0x2000_0010, 0xCAFE_F00D)
        adiv5.halt()
        val = adiv5.read_mem32(0x2000_0010)
        assert val == 0xCAFE_F00D

    def test_reset_clears_registers(self, adiv5: ADIv5, probe: SimulatedProbe) -> None:
        adiv5.write_core_register(REG_R0, 0x1234)
        adiv5.reset_system()
        # Após reset, probe limpa o estado de halt; registrador ainda existe no dicionário
        assert not probe._cpu_halted

    def test_jtag_to_swd_then_init(self) -> None:
        probe = SimulatedProbe()
        transport = SimulatedSWDTransport(probe)
        proto = SWDProtocol(transport)
        # jtag_to_swd envia dois line resets + magic — transport deve conectar o probe
        proto.jtag_to_swd()
        adiv5 = ADIv5(proto)
        # Após jtag_to_swd, probe já está conectado; init chama line_reset novamente
        dpidr = adiv5.init()
        assert dpidr == 0x2BA0_1477
