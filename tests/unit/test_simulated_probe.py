"""Testes unitários do SimulatedProbe — cobertura ≥ 70% em sim/."""

from __future__ import annotations

import pytest

from sim.simulated_probe import SimulatedProbe

# ===========================================================================
# SWD — inicialização e estado
# ===========================================================================


class TestSWDInit:
    def test_not_connected_before_reset(self, probe_raw: SimulatedProbe) -> None:
        with pytest.raises(RuntimeError, match="swd_line_reset"):
            probe_raw.read_dp("DPIDR")

    def test_connected_after_line_reset(self, probe_raw: SimulatedProbe) -> None:
        probe_raw.swd_line_reset()
        assert probe_raw.read_dp("DPIDR") != 0

    def test_default_dpidr(self, probe: SimulatedProbe) -> None:
        assert probe.read_dp("DPIDR") == 0x2BA0_1477

    def test_custom_dpidr(self) -> None:
        p = SimulatedProbe(dpidr=0xDEAD_BEEF)
        p.swd_line_reset()
        assert p.read_dp("DPIDR") == 0xDEAD_BEEF

    def test_line_reset_clears_fault(self) -> None:
        p = SimulatedProbe()
        p.swd_line_reset()
        p._fault = True  # simula falha interna
        p.swd_line_reset()
        assert not p._fault


# ===========================================================================
# SWD — leitura/escrita DP
# ===========================================================================


class TestSWDDP:
    def test_read_ctrl_stat_default(self, probe: SimulatedProbe) -> None:
        assert probe.read_dp("CTRL/STAT") == 0

    def test_write_and_read_ctrl_stat(self, probe: SimulatedProbe) -> None:
        probe.write_dp("CTRL/STAT", 0x5000_0000)
        assert probe.read_dp("CTRL/STAT") == 0x5000_0000

    def test_write_and_read_select(self, probe: SimulatedProbe) -> None:
        probe.write_dp("SELECT", 0x0000_00F0)
        assert probe.read_dp("SELECT") == 0x0000_00F0

    def test_read_rdbuff(self, probe: SimulatedProbe) -> None:
        assert probe.read_dp("RDBUFF") == 0

    def test_read_unknown_reg_raises(self, probe: SimulatedProbe) -> None:
        with pytest.raises(ValueError, match="desconhecido"):
            probe.read_dp("INVALID")

    def test_write_unknown_reg_raises(self, probe: SimulatedProbe) -> None:
        with pytest.raises(ValueError, match="não gravável"):
            probe.write_dp("DPIDR", 0)

    def test_value_truncated_to_32bit(self, probe: SimulatedProbe) -> None:
        probe.write_dp("CTRL/STAT", 0x1_5000_0000)
        assert probe.read_dp("CTRL/STAT") == 0x5000_0000


# ===========================================================================
# SWD — leitura/escrita AP (MEM-AP)
# ===========================================================================


class TestSWDAP:
    def test_read_ap0_idr(self, probe: SimulatedProbe) -> None:
        assert probe.read_ap(0, "IDR") == 0x2477_0021

    def test_custom_ap0_idr(self) -> None:
        p = SimulatedProbe(ap0_idr=0x1234_5678)
        p.swd_line_reset()
        assert p.read_ap(0, "IDR") == 0x1234_5678

    def test_write_and_read_csw(self, probe: SimulatedProbe) -> None:
        probe.write_ap(0, "CSW", 0x2300_0012)
        assert probe.read_ap(0, "CSW") == 0x2300_0012

    def test_write_tar_and_read_drw_zero(self, probe: SimulatedProbe) -> None:
        probe.write_ap(0, "TAR", 0x2000_0000)
        assert probe.read_ap(0, "DRW") == 0

    def test_write_and_read_drw_via_memory(self, probe: SimulatedProbe) -> None:
        probe.write_ap(0, "TAR", 0x0000_0004)
        probe.write_ap(0, "DRW", 0xABCD_1234)
        probe.write_ap(0, "TAR", 0x0000_0004)
        assert probe.read_ap(0, "DRW") == 0xABCD_1234

    def test_unknown_ap_raises(self, probe: SimulatedProbe) -> None:
        with pytest.raises(NotImplementedError, match="AP 1"):
            probe.read_ap(1, "IDR")

    def test_unknown_ap_write_raises(self, probe: SimulatedProbe) -> None:
        with pytest.raises(NotImplementedError, match="AP 2"):
            probe.write_ap(2, "CSW", 0)

    def test_read_unknown_ap_reg_raises(self, probe: SimulatedProbe) -> None:
        with pytest.raises(ValueError, match="desconhecido"):
            probe.read_ap(0, "BOGUS")

    def test_write_unknown_ap_reg_raises(self, probe: SimulatedProbe) -> None:
        with pytest.raises(ValueError, match="não gravável"):
            probe.write_ap(0, "IDR", 0)


# ===========================================================================
# SWD — memória
# ===========================================================================


class TestSWDMemory:
    def test_read_prepopulated_memory(self, probe_with_memory: SimulatedProbe) -> None:
        assert probe_with_memory.read_memory_word(0x0000_0000) == 0xDEAD_BEEF
        assert probe_with_memory.read_memory_word(0x0000_0004) == 0xCAFE_BABE

    def test_read_uninitialised_address_returns_zero(self, probe: SimulatedProbe) -> None:
        assert probe.read_memory_word(0xFFFF_0000) == 0

    def test_write_and_read_memory(self, probe: SimulatedProbe) -> None:
        probe.write_memory_word(0x2000_0000, 0x1234_5678)
        assert probe.read_memory_word(0x2000_0000) == 0x1234_5678

    def test_memory_word_truncated(self, probe: SimulatedProbe) -> None:
        probe.write_memory_word(0x0, 0x1_FFFF_FFFF)
        assert probe.read_memory_word(0x0) == 0xFFFF_FFFF

    def test_memory_not_accessible_before_reset(self, probe_raw: SimulatedProbe) -> None:
        with pytest.raises(RuntimeError):
            probe_raw.read_memory_word(0x0)


# ===========================================================================
# JTAG — TAP e chain
# ===========================================================================


class TestJTAG:
    def test_default_chain_length(self) -> None:
        p = SimulatedProbe()
        assert p.chain_length == 1

    def test_custom_chain_length(self, probe_jtag: SimulatedProbe) -> None:
        assert probe_jtag.chain_length == 2

    def test_tap_reset_state(self) -> None:
        p = SimulatedProbe()
        p.tap_reset()
        assert p.tap_state == "TEST_LOGIC_RESET"

    def test_read_idcode_default_device(self) -> None:
        p = SimulatedProbe(jtag_chain=[0x0BA0_0477])
        assert p.read_idcode(device=0) == 0x0BA0_0477

    def test_read_idcode_second_device(self, probe_jtag: SimulatedProbe) -> None:
        assert probe_jtag.read_idcode(device=1) == 0x2BA0_1477

    def test_shift_ir_returns_previous(self) -> None:
        p = SimulatedProbe()
        first_capture = p.shift_ir(0b0001)
        assert first_capture == 0b1111  # BYPASS era o IR inicial

    def test_bypass_shift_dr(self) -> None:
        p = SimulatedProbe()
        p.tap_reset()
        # IR em BYPASS (0b1111), shift-DR de 1 bit deve retornar 0
        captured = p.shift_dr(1, 1)
        assert captured == 0

    def test_idcode_instruction_selects_idcode_dr(self) -> None:
        idcode = 0x12345678
        p = SimulatedProbe(jtag_chain=[idcode])
        # Carrega instrução IDCODE (0b0001)
        p.shift_ir(0b0001)
        result = p.shift_dr(0, 32)
        assert result == idcode

    def test_state_after_shift_ir(self) -> None:
        p = SimulatedProbe()
        p.shift_ir(0b0001)
        assert p.tap_state == "RUN_TEST_IDLE"

    def test_state_after_shift_dr(self) -> None:
        p = SimulatedProbe()
        p.shift_dr(0, 32)
        assert p.tap_state == "RUN_TEST_IDLE"

    def test_custom_ir_length(self) -> None:
        p = SimulatedProbe(jtag_chain=[0xABCD], ir_length=5)
        # IR de 5 bits: o valor carregado deve ser mascarado
        p.shift_ir(0b11111)
        captured = p.shift_ir(0b00001)
        assert captured == 0b11111

    def test_multiple_idcode_reads_consistent(self) -> None:
        p = SimulatedProbe(jtag_chain=[0xDEAD_CAFE])
        for _ in range(3):
            assert p.read_idcode() == 0xDEAD_CAFE
