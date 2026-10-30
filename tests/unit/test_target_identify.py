"""Testes unitários de core.target.identify — memória simulada, sem hardware.

Execução:
    pytest tests/unit/test_target_identify.py -v
"""

from __future__ import annotations

import pytest

from core.target import McuInfo, identify
from core.target.identify import CPUID_ADDR, ROM_PIDR_BASE

_DPIDR = 0x2BA01477

# CPUID Cortex-M4 r0p1 (implementer ARM 0x41, partno 0xC24)
_CPUID_M4 = 0x410FC241
# CPUID Cortex-M0+ r0p1
_CPUID_M0P = 0x410CC601
# CPUID Cortex-M7 r1p0
_CPUID_M7 = 0x411FC270


class FakeMem:
    """Memória esparsa: endereços ausentes levantam erro (como bus fault)."""

    def __init__(self, data: dict[int, int]) -> None:
        self._data = data
        self.reads: list[int] = []

    def read_mem32(self, addr: int) -> int:
        self.reads.append(addr)
        if addr not in self._data:
            raise RuntimeError(f"fault @ 0x{addr:08X}")
        return self._data[addr]


def _rom_st() -> dict[int, int]:
    """PIDR da ROM table com JEP106 da ST (cont 0, id 0x20)."""
    return {
        ROM_PIDR_BASE + 0x00: 0x00,   # PIDR4: continuation 0
        ROM_PIDR_BASE + 0x14: 0x00,   # PIDR1[7:4] = id[3:0] = 0
        ROM_PIDR_BASE + 0x18: 0x0A,   # PIDR2: JEDEC=1, id[6:4]=2
    }


class TestIdentifyStm32:
    def test_f446(self) -> None:
        mem = FakeMem({CPUID_ADDR: _CPUID_M4, 0xE0042000: 0x10006421, **_rom_st()})
        info = identify(mem, _DPIDR)
        assert info.family == "STM32F446"
        assert info.core == "Cortex-M4"
        assert info.core_revision == "r0p1"
        assert info.dev_id == 0x421
        assert info.rev_id == 0x1000
        assert info.vendor == "STMicroelectronics"
        assert info.idcode_addr == 0xE0042000

    def test_g0_uses_m0_address_first(self) -> None:
        mem = FakeMem({CPUID_ADDR: _CPUID_M0P, 0x40015800: 0x20006460})
        info = identify(mem, _DPIDR)
        assert info.family == "STM32G07x/G08x"
        assert info.idcode_addr == 0x40015800
        assert 0xE0042000 not in mem.reads

    def test_f7_falls_back_after_h7_address(self) -> None:
        mem = FakeMem({CPUID_ADDR: _CPUID_M7, 0xE0042000: 0x10016449})
        info = identify(mem, _DPIDR)
        assert info.family == "STM32F74x/F75x"
        assert info.idcode_addr == 0xE0042000

    def test_summary_lists_main_fields(self) -> None:
        mem = FakeMem({CPUID_ADDR: _CPUID_M4, 0xE0042000: 0x10006421, **_rom_st()})
        text = identify(mem, _DPIDR).summary()
        assert "STM32F446" in text
        assert "Cortex-M4" in text
        assert "0x421" in text
        assert "2BA01477" in text


class TestIdentifyPartial:
    def test_non_stm32_reports_core_only(self) -> None:
        mem = FakeMem({CPUID_ADDR: _CPUID_M4})
        info = identify(mem, _DPIDR)
        assert info.family is None
        assert info.dev_id is None
        assert info.name == "Cortex-M4"

    def test_unknown_dev_id_is_ignored(self) -> None:
        mem = FakeMem({CPUID_ADDR: _CPUID_M4, 0xE0042000: 0x10000FFF})
        assert identify(mem, _DPIDR).idcode is None

    def test_nothing_readable(self) -> None:
        info = identify(FakeMem({}), _DPIDR)
        assert info == McuInfo(_DPIDR, None, None, None, None)
        assert info.name == "desconhecido"

    def test_rom_without_jedec_bit_has_no_vendor(self) -> None:
        rom = _rom_st()
        rom[ROM_PIDR_BASE + 0x18] = 0x02
        assert identify(FakeMem(rom), _DPIDR).vendor is None

    @pytest.mark.parametrize(
        ("cpuid", "core"),
        [(0x410CC200, "Cortex-M0"), (0x412FC230, "Cortex-M3"), (0x410FD210, "Cortex-M33")],
    )
    def test_core_names(self, cpuid: int, core: str) -> None:
        assert identify(FakeMem({CPUID_ADDR: cpuid}), _DPIDR).core == core


class TestIdentifyMultipleAps:
    def test_h7_core_inaccessible_dbgmcu_on_ap2(self) -> None:
        """Caso real (STLINK-V3 + STM32H74x/H75x): AP0 devolve lixo, DBGMCU via AP2."""
        garbage = 0xA05F0000

        class GarbageMem:
            def read_mem32(self, addr: int) -> int:
                return garbage

        ap2 = FakeMem({0xE00E1000: 0x20036450})
        info = identify([GarbageMem(), ap2], 0x6BA02477)
        assert info.cpuid is None            # 0xA05F0000 não é CPUID ARM
        assert info.vendor is None
        assert info.family == "STM32H74x/H75x"
        assert info.rev_id == 0x2003
        assert info.idcode_addr == 0xE00E1000

    def test_cpuid_taken_from_first_valid_ap(self) -> None:
        ap0 = FakeMem({})
        ap1 = FakeMem({CPUID_ADDR: _CPUID_M4, 0xE0042000: 0x10006421})
        info = identify([ap0, ap1], _DPIDR)
        assert info.core == "Cortex-M4"
        assert info.family == "STM32F446"
