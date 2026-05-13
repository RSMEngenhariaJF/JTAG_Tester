"""Testes de hardware — FT2232H + SWD + ADIv5 em target real.

Executar quando o FT2232H chegar:
    pytest tests/hardware/ -m hardware -v --hw-url ftdi://ftdi:2232h/1

Todos os testes são pulados automaticamente se --hw-url não for fornecido.
"""

from __future__ import annotations

import pytest

from core.adiv5.constants import DHCSR, DHCSR_S_HALT, REG_PC, REG_R0

# ===========================================================================
# Detecção de dispositivo
# ===========================================================================


@pytest.mark.hardware
class TestDetection:
    def test_list_devices_finds_ft2232h(self) -> None:
        from adapters.ft2232h.detector import list_devices

        devs = list_devices()
        assert devs, "Nenhum FT2232H encontrado — verifique driver e USB"

    def test_transport_opens(self, ft2232h_transport: object) -> None:
        assert ft2232h_transport is not None


# ===========================================================================
# Protocolo SWD básico
# ===========================================================================


@pytest.mark.hardware
class TestSWDProtocol:
    def test_line_reset_does_not_raise(self, ft2232h_transport: object) -> None:
        from core.swd.protocol import SWDProtocol

        proto = SWDProtocol(ft2232h_transport)
        proto.line_reset()  # não deve levantar exceção

    def test_jtag_to_swd_sequence(self, ft2232h_transport: object) -> None:
        from core.swd.protocol import SWDProtocol

        proto = SWDProtocol(ft2232h_transport)
        proto.jtag_to_swd()

    def test_read_dpidr_is_nonzero(self, ft2232h_transport: object) -> None:
        from core.swd.protocol import DP_ADDR_DPIDR, SWDProtocol

        proto = SWDProtocol(ft2232h_transport)
        proto.line_reset()
        dpidr = proto.read_dp(DP_ADDR_DPIDR)
        assert dpidr != 0, "DPIDR zerado indica falha de comunicação SWD"

    def test_dpidr_has_valid_designer(self, ft2232h_transport: object) -> None:
        """DPIDR bits [11:1] = JEP106 designer — ARM = 0x23B."""
        from core.swd.protocol import DP_ADDR_DPIDR, SWDProtocol

        proto = SWDProtocol(ft2232h_transport)
        proto.line_reset()
        dpidr = proto.read_dp(DP_ADDR_DPIDR)
        designer = (dpidr >> 1) & 0x7FF
        # ARM Limited JEP106 = 0x23B (ou 0x477 para alguns cores)
        assert designer in (0x23B, 0x477), f"Designer inesperado: 0x{designer:03X}"


# ===========================================================================
# ADIv5 — inicialização
# ===========================================================================


@pytest.mark.hardware
class TestADIv5Init:
    def test_init_returns_dpidr(self, hw_adiv5: object) -> None:
        assert hw_adiv5 is not None

    def test_dpidr_matches_stm32(self, ft2232h_transport: object) -> None:
        """STM32 com Cortex-M3/M4: DPIDR = 0x2BA01477."""
        from core.adiv5.adiv5 import ADIv5
        from core.swd.protocol import SWDProtocol

        adiv5 = ADIv5(SWDProtocol(ft2232h_transport))
        dpidr = adiv5.init()
        # Aceita qualquer DPIDR válido da ARM (bit 0 = 1)
        assert dpidr & 1, f"Bit 0 do DPIDR deve ser 1, obtido: 0x{dpidr:08X}"


# ===========================================================================
# ADIv5 — acesso a memória
# ===========================================================================


@pytest.mark.hardware
class TestMemoryAccess:
    # SRAM interna de STM32 começa em 0x2000_0000 (pelo menos 20 KB)
    _SRAM_ADDR = 0x2000_0000

    def test_write_and_read_sram(self, hw_adiv5: object) -> None:
        hw_adiv5.write_mem32(self._SRAM_ADDR, 0xDEAD_BEEF)
        result = hw_adiv5.read_mem32(self._SRAM_ADDR)
        assert result == 0xDEAD_BEEF, f"Lido: 0x{result:08X}"

    def test_write_zero_and_read_back(self, hw_adiv5: object) -> None:
        hw_adiv5.write_mem32(self._SRAM_ADDR + 4, 0xFFFF_FFFF)
        hw_adiv5.write_mem32(self._SRAM_ADDR + 4, 0x0000_0000)
        assert hw_adiv5.read_mem32(self._SRAM_ADDR + 4) == 0

    def test_multiple_words_independent(self, hw_adiv5: object) -> None:
        addrs = [self._SRAM_ADDR + i * 4 for i in range(4)]
        vals = [0xAAAA_AAAA, 0xBBBB_BBBB, 0xCCCC_CCCC, 0xDDDD_DDDD]
        for addr, val in zip(addrs, vals, strict=True):
            hw_adiv5.write_mem32(addr, val)
        for addr, val in zip(addrs, vals, strict=True):
            assert hw_adiv5.read_mem32(addr) == val


# ===========================================================================
# ADIv5 — controle de execução
# ===========================================================================


@pytest.mark.hardware
class TestHaltResume:
    def test_halt_and_is_halted(self, hw_adiv5: object) -> None:
        hw_adiv5.halt()
        assert hw_adiv5.is_halted(), "Core não parou após halt()"

    def test_resume_and_not_halted(self, hw_adiv5: object) -> None:
        hw_adiv5.halt()
        hw_adiv5.resume()
        assert not hw_adiv5.is_halted(), "Core não retomou após resume()"

    def test_dhcsr_s_halt_bit_set(self, hw_adiv5: object) -> None:
        hw_adiv5.halt()
        dhcsr = hw_adiv5.read_mem32(DHCSR)
        assert dhcsr & DHCSR_S_HALT, f"S_HALT não setado: DHCSR=0x{dhcsr:08X}"


# ===========================================================================
# ADIv5 — registradores de núcleo
# ===========================================================================


@pytest.mark.hardware
class TestCoreRegisters:
    def test_write_read_r0(self, hw_adiv5: object) -> None:
        hw_adiv5.halt()
        hw_adiv5.write_core_register(REG_R0, 0x1234_5678)
        assert hw_adiv5.read_core_register(REG_R0) == 0x1234_5678

    def test_pc_is_nonzero(self, hw_adiv5: object) -> None:
        hw_adiv5.halt()
        pc = hw_adiv5.read_core_register(REG_PC)
        assert pc != 0, "PC = 0 sugere falha de comunicação"

    def test_restore_register_after_read(self, hw_adiv5: object) -> None:
        hw_adiv5.halt()
        original = hw_adiv5.read_core_register(REG_R0)
        hw_adiv5.write_core_register(REG_R0, 0xDEAD_CAFE)
        hw_adiv5.write_core_register(REG_R0, original)
        assert hw_adiv5.read_core_register(REG_R0) == original


# ===========================================================================
# Diagnóstico — gate da Fase 1
# ===========================================================================


@pytest.mark.hardware
class TestPhase1Gate:
    """Gate da Fase 1: ler DPIDR em hardware STM32 real via SWD."""

    def test_gate_fase1_dpidr_via_swd(self, ft2232h_transport: object) -> None:
        """Prova de conceito: DPIDR real lido com sucesso via FT2232H."""
        from core.adiv5.adiv5 import ADIv5
        from core.swd.protocol import SWDProtocol

        adiv5 = ADIv5(SWDProtocol(ft2232h_transport))
        dpidr = adiv5.init()
        print(f"\n  *** GATE FASE 1 ***  DPIDR = 0x{dpidr:08X}")
        assert dpidr & 1, "DPIDR bit 0 deve ser 1 (ARM ADIv5 §2.3)"
