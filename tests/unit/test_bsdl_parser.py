"""Testes unitários do parser BSDL — valida CortexMx.bsd e STM32F446_LQFP64.bsd."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.bsdl.model import BsdlCell, BsdlDevice, BsdlInstruction
from core.bsdl.parser import parse

_DEVICES = Path(__file__).parents[2] / "devices" / "stm32f446"
_CORTEX = _DEVICES / "CortexMx.bsd"
_STM32 = _DEVICES / "STM32F446_LQFP64.bsd"


@pytest.fixture(scope="module")
def cortex() -> BsdlDevice:
    return parse(_CORTEX)


@pytest.fixture(scope="module")
def stm32() -> BsdlDevice:
    return parse(_STM32)


# ===========================================================================
# CortexMx — metadados básicos
# ===========================================================================


class TestCortexMetadata:
    def test_entity_name(self, cortex: BsdlDevice) -> None:
        assert cortex.entity_name == "CortexMx"

    def test_ir_length(self, cortex: BsdlDevice) -> None:
        assert cortex.ir_length == 4

    def test_boundary_length(self, cortex: BsdlDevice) -> None:
        assert cortex.boundary_length == 1

    def test_has_cells(self, cortex: BsdlDevice) -> None:
        assert len(cortex.cells) == 1

    def test_single_cell_is_internal(self, cortex: BsdlDevice) -> None:
        c = cortex.cells[0]
        assert c.num == 0
        assert c.function == "internal"


class TestCortexInstructions:
    def test_has_bypass(self, cortex: BsdlDevice) -> None:
        assert cortex.opcode("BYPASS") == "1111"

    def test_has_idcode(self, cortex: BsdlDevice) -> None:
        assert cortex.opcode("IDCODE") == "1110"

    def test_has_extest(self, cortex: BsdlDevice) -> None:
        assert cortex.opcode("EXTEST") == "0000"

    def test_has_sample(self, cortex: BsdlDevice) -> None:
        assert cortex.opcode("SAMPLE") == "0010"

    def test_missing_instruction_raises(self, cortex: BsdlDevice) -> None:
        with pytest.raises(KeyError):
            cortex.opcode("NONEXISTENT")


class TestCortexIdcode:
    # CortexMx IDCODE: XXXX + 1011101000000000 + 01000111011 + 1
    # mask  = 0x0FFFFFFF
    # value = (0xBA00 << 12) | (0x23B << 1) | 1 = 0x0BA00477
    def test_idcode_pattern_length(self, cortex: BsdlDevice) -> None:
        assert len(cortex.idcode_pattern) == 32

    def test_idcode_pattern_starts_with_xxxx(self, cortex: BsdlDevice) -> None:
        assert cortex.idcode_pattern[:4] == "XXXX"

    def test_idcode_mask(self, cortex: BsdlDevice) -> None:
        mask, _ = cortex.idcode_mask_value()
        assert mask == 0x0FFFFFFF

    def test_idcode_value(self, cortex: BsdlDevice) -> None:
        _, value = cortex.idcode_mask_value()
        assert value == 0x0BA00477

    def test_matches_idcode_with_any_version(self, cortex: BsdlDevice) -> None:
        # A versão nos 4 bits superiores pode variar
        for version in range(16):
            idcode = (version << 28) | 0x0BA00477
            assert cortex.matches_idcode(idcode), f"version={version} falhou"

    def test_does_not_match_wrong_idcode(self, cortex: BsdlDevice) -> None:
        assert not cortex.matches_idcode(0xDEADBEEF)


# ===========================================================================
# STM32F446_LQFP64 — metadados básicos
# ===========================================================================


class TestStm32Metadata:
    def test_entity_name(self, stm32: BsdlDevice) -> None:
        assert stm32.entity_name == "STM32F446_LQFP64"

    def test_ir_length(self, stm32: BsdlDevice) -> None:
        assert stm32.ir_length == 5

    def test_boundary_length(self, stm32: BsdlDevice) -> None:
        assert stm32.boundary_length == 328

    def test_cell_count(self, stm32: BsdlDevice) -> None:
        assert len(stm32.cells) == 328


class TestStm32Instructions:
    def test_bypass(self, stm32: BsdlDevice) -> None:
        assert stm32.opcode("BYPASS") == "11111"

    def test_extest(self, stm32: BsdlDevice) -> None:
        assert stm32.opcode("EXTEST") == "00000"

    def test_sample(self, stm32: BsdlDevice) -> None:
        assert stm32.opcode("SAMPLE") == "00010"

    def test_idcode(self, stm32: BsdlDevice) -> None:
        assert stm32.opcode("IDCODE") == "00001"

    def test_preload_same_as_sample(self, stm32: BsdlDevice) -> None:
        assert stm32.opcode("PRELOAD") == stm32.opcode("SAMPLE")


class TestStm32Idcode:
    # STM32F446 IDCODE: XXXX + 0110010000100001 + 00000100000 + 1
    # part = 0x6421, mfr = 0x20
    # value = (0x6421 << 12) | (0x20 << 1) | 1 = 0x06421041
    def test_idcode_pattern_length(self, stm32: BsdlDevice) -> None:
        assert len(stm32.idcode_pattern) == 32

    def test_idcode_mask(self, stm32: BsdlDevice) -> None:
        mask, _ = stm32.idcode_mask_value()
        assert mask == 0x0FFFFFFF

    def test_idcode_value(self, stm32: BsdlDevice) -> None:
        _, value = stm32.idcode_mask_value()
        assert value == 0x06421041

    def test_matches_idcode_with_any_version(self, stm32: BsdlDevice) -> None:
        for version in range(16):
            idcode = (version << 28) | 0x06421041
            assert stm32.matches_idcode(idcode)

    def test_does_not_match_cortex_idcode(self, stm32: BsdlDevice) -> None:
        # IDCODE do CortexMx não deve casar com o STM32 boundary scan TAP
        assert not stm32.matches_idcode(0x2BA00477)


# ===========================================================================
# STM32F446_LQFP64 — mapa de pinos
# ===========================================================================


class TestStm32PinMap:
    _EXPECTED: dict[str, list[str]] = {
        "JTDI":  ["50"],
        "JTCK":  ["49"],
        "JTDO":  ["55"],
        "JTRST": ["56"],
        "JTMS":  ["46"],
        "NRST":  ["7"],
        "PA0":   ["14"],
        "PA5":   ["21"],
        "PB10":  ["29"],
        "PC13":  ["2"],
        "PD2":   ["54"],
        "BOOT0": ["60"],
    }

    @pytest.mark.parametrize("port,pins", _EXPECTED.items())
    def test_pin_map_entry(self, stm32: BsdlDevice, port: str, pins: list[str]) -> None:
        assert stm32.pin_map[port] == pins, f"{port}: esperado {pins}"

    def test_vdd_has_multiple_pins(self, stm32: BsdlDevice) -> None:
        # VDD : (19, 32, 48, 64)
        assert sorted(stm32.pin_map["VDD"]) == ["19", "32", "48", "64"]

    def test_vss_has_multiple_pins(self, stm32: BsdlDevice) -> None:
        assert sorted(stm32.pin_map["VSS"]) == ["18", "31", "47", "63"]


# ===========================================================================
# STM32F446_LQFP64 — células BSR
# ===========================================================================


class TestStm32Cells:
    def test_cells_ordered_high_to_low(self, stm32: BsdlDevice) -> None:
        nums = [c.num for c in stm32.cells]
        assert nums == sorted(nums, reverse=True)

    def test_highest_cell_is_327(self, stm32: BsdlDevice) -> None:
        assert stm32.cells[0].num == 327

    def test_lowest_cell_is_0(self, stm32: BsdlDevice) -> None:
        assert stm32.cells[-1].num == 0

    def test_cell_lookup_by_num(self, stm32: BsdlDevice) -> None:
        c = stm32.cell(252)
        assert c.num == 252
        assert c.function == "control"

    def test_cell_missing_raises(self, stm32: BsdlDevice) -> None:
        with pytest.raises(KeyError):
            stm32.cell(9999)


class TestStm32CellsForPort:
    def test_pa0_has_two_cells(self, stm32: BsdlDevice) -> None:
        # PA0 tem output3 (251) e input (250); a CONTROL (252) tem porta "*"
        cells = stm32.cells_for_port("PA0")
        assert len(cells) == 2

    def test_pa0_control_cell(self, stm32: BsdlDevice) -> None:
        c = stm32.cell(252)
        assert c.is_control
        assert c.port == "*"
        assert c.safe == "1"

    def test_pa0_output_cell(self, stm32: BsdlDevice) -> None:
        c = stm32.cell(251)
        assert c.port.upper() == "PA0"
        assert c.is_output
        assert c.ccell == 252
        assert c.disval == 1
        assert c.rslt == "Z"

    def test_pa0_input_cell(self, stm32: BsdlDevice) -> None:
        c = stm32.cell(250)
        assert c.port.upper() == "PA0"
        assert c.is_input
        assert c.cell_type == "BC_4"
        assert c.ccell is None

    def test_pa0_case_insensitive(self, stm32: BsdlDevice) -> None:
        assert len(stm32.cells_for_port("pa0")) == 2

    def test_unknown_port_returns_empty(self, stm32: BsdlDevice) -> None:
        assert stm32.cells_for_port("NONEXISTENT") == ()

    def test_boot0_is_input_only(self, stm32: BsdlDevice) -> None:
        # BOOT0 célula 12 é BC_4 INPUT
        cells = stm32.cells_for_port("BOOT0")
        assert len(cells) == 1
        assert cells[0].is_input


class TestStm32InternalCells:
    def test_internal_cells_have_no_port(self, stm32: BsdlDevice) -> None:
        internal = [c for c in stm32.cells if c.function == "internal"]
        assert all(c.port == "*" for c in internal)

    def test_internal_cells_have_no_ccell(self, stm32: BsdlDevice) -> None:
        internal = [c for c in stm32.cells if c.function == "internal"]
        assert all(c.ccell is None for c in internal)

    def test_at_least_half_cells_are_internal(self, stm32: BsdlDevice) -> None:
        internal_count = sum(1 for c in stm32.cells if c.function == "internal")
        assert internal_count > len(stm32.cells) // 2


# ===========================================================================
# BsdlDevice.safe_preload()
# ===========================================================================


class TestSafePreload:
    def test_preload_length_matches_boundary(self, stm32: BsdlDevice) -> None:
        bits = stm32.safe_preload()
        assert len(bits) == stm32.boundary_length

    def test_preload_all_bits_are_0_or_1(self, stm32: BsdlDevice) -> None:
        bits = stm32.safe_preload()
        assert all(b in (0, 1) for b in bits)

    def test_control_cells_preloaded_to_safe_1(self, stm32: BsdlDevice) -> None:
        bits = stm32.safe_preload()
        for cell in stm32.cells:
            if cell.safe == "1":
                # célula N ocupa posição (boundary_length - 1 - N) no vetor
                idx = stm32.boundary_length - 1 - cell.num
                assert bits[idx] == 1, f"célula {cell.num} deveria ser 1"
