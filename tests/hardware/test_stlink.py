"""Testes de hardware via ST-Link on-board (NUCLEO) — adaptador pyOCD.

Executar (NUCLEO USB conectado):
    pytest tests/hardware/test_stlink.py -m hardware -v --stlink

Todos os testes são pulados automaticamente se --stlink não for fornecido.
"""

from __future__ import annotations

import pytest

from core.adiv5.constants import DHCSR, DHCSR_S_HALT, REG_PC, REG_R0

_EXPECTED_DPIDR = 0x2BA01477  # STM32F446RE Cortex-M4 SWJ-DP


# ===========================================================================
# Gate da Fase 1 — leitura de DPIDR via ST-Link
# ===========================================================================


@pytest.mark.hardware
class TestPhase1GateStLink:
    """Gate da Fase 1 (via ST-Link): confirma leitura real do DPIDR."""

    def test_gate_fase1_dpidr_via_stlink(self, stlink_adiv5: object) -> None:
        dpidr = stlink_adiv5.init()  # type: ignore[union-attr]
        print(f"\n  *** GATE FASE 1 (ST-Link) ***  DPIDR = 0x{dpidr:08X}")
        assert dpidr == _EXPECTED_DPIDR, (
            f"DPIDR esperado 0x{_EXPECTED_DPIDR:08X}, obtido 0x{dpidr:08X}"
        )

    def test_dpidr_bit0_always_1(self, stlink_adiv5: object) -> None:
        dpidr = stlink_adiv5.init()  # type: ignore[union-attr]
        assert dpidr & 1, f"Bit 0 do DPIDR deve ser 1 (ARM ADIv5 §2.3): 0x{dpidr:08X}"


# ===========================================================================
# Acesso a memória (SRAM)
# ===========================================================================


@pytest.mark.hardware
class TestMemoryAccessStLink:
    _SRAM = 0x2000_0000  # STM32F446RE: 128 KB SRAM @ 0x20000000

    def test_write_and_read_back(self, stlink_adiv5: object) -> None:
        stlink_adiv5.write_mem32(self._SRAM, 0xDEAD_BEEF)  # type: ignore[union-attr]
        assert stlink_adiv5.read_mem32(self._SRAM) == 0xDEAD_BEEF  # type: ignore[union-attr]

    def test_multiple_words(self, stlink_adiv5: object) -> None:
        addrs = [self._SRAM + i * 4 for i in range(4)]
        vals = [0xAAAA_AAAA, 0xBBBB_BBBB, 0xCCCC_CCCC, 0xDDDD_DDDD]
        for addr, val in zip(addrs, vals, strict=True):
            stlink_adiv5.write_mem32(addr, val)  # type: ignore[union-attr]
        for addr, val in zip(addrs, vals, strict=True):
            assert stlink_adiv5.read_mem32(addr) == val  # type: ignore[union-attr]


# ===========================================================================
# Halt / resume
# ===========================================================================


@pytest.mark.hardware
class TestHaltResumeStLink:
    def test_halt_and_is_halted(self, stlink_adiv5: object) -> None:
        stlink_adiv5.halt()  # type: ignore[union-attr]
        assert stlink_adiv5.is_halted(), "Core não parou após halt()"  # type: ignore[union-attr]

    def test_resume_and_not_halted(self, stlink_adiv5: object) -> None:
        stlink_adiv5.halt()  # type: ignore[union-attr]
        stlink_adiv5.resume()  # type: ignore[union-attr]
        assert not stlink_adiv5.is_halted(), "Core não retomou após resume()"  # type: ignore[union-attr]

    def test_dhcsr_s_halt_bit(self, stlink_adiv5: object) -> None:
        stlink_adiv5.halt()  # type: ignore[union-attr]
        dhcsr = stlink_adiv5.read_mem32(DHCSR)  # type: ignore[union-attr]
        assert dhcsr & DHCSR_S_HALT, f"S_HALT não setado: DHCSR=0x{dhcsr:08X}"


# ===========================================================================
# Registradores de núcleo
# ===========================================================================


@pytest.mark.hardware
class TestCoreRegistersStLink:
    def test_write_read_r0(self, stlink_adiv5: object) -> None:
        stlink_adiv5.halt()  # type: ignore[union-attr]
        stlink_adiv5.write_core_register(REG_R0, 0x1234_5678)  # type: ignore[union-attr]
        assert stlink_adiv5.read_core_register(REG_R0) == 0x1234_5678  # type: ignore[union-attr]

    def test_pc_is_nonzero(self, stlink_adiv5: object) -> None:
        stlink_adiv5.halt()  # type: ignore[union-attr]
        pc = stlink_adiv5.read_core_register(REG_PC)  # type: ignore[union-attr]
        assert pc != 0, "PC = 0 sugere falha de comunicação"

    def test_restore_r0(self, stlink_adiv5: object) -> None:
        stlink_adiv5.halt()  # type: ignore[union-attr]
        original = stlink_adiv5.read_core_register(REG_R0)  # type: ignore[union-attr]
        stlink_adiv5.write_core_register(REG_R0, 0xDEAD_CAFE)  # type: ignore[union-attr]
        stlink_adiv5.write_core_register(REG_R0, original)  # type: ignore[union-attr]
        assert stlink_adiv5.read_core_register(REG_R0) == original  # type: ignore[union-attr]
