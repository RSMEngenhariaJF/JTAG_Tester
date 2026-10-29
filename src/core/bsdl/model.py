"""Modelo de dados imutável para BSDL (Boundary Scan Description Language).

Hierarquia: BsdlDevice → BsdlInstruction / BsdlCell

Referência: IEEE Std 1149.1-2001 (JTAG)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BsdlInstruction:
    """Instrução JTAG com nome e opcode binário."""

    name: str      # e.g. "IDCODE", "BYPASS", "EXTEST"
    opcode: str    # string binária MSB-first, e.g. "00001"


@dataclass(frozen=True)
class BsdlCell:
    """Célula individual do Boundary Scan Register (BSR).

    A numeração segue a convenção BSDL: célula 0 é a mais próxima do TDO,
    a célula de número mais alto é a mais próxima do TDI.
    """

    num: int          # número da célula (posição no shift register)
    cell_type: str    # "BC_0", "BC_1", "BC_4", etc.
    port: str         # nome da porta ou "*" para células anônimas
    function: str     # "input"|"output2"|"output3"|"bidir"|"control"|"controlr"|"internal"
    safe: str         # "0"|"1"|"X" — valor seguro para EXTEST
    ccell: int | None    # índice da célula de controle (tristate), ou None
    disval: int | None   # valor de desabilitação no ccell, ou None
    rslt: str | None     # estado do driver desabilitado: "Z"|"0"|"1", ou None

    @property
    def is_input(self) -> bool:
        return self.function == "input"

    @property
    def is_output(self) -> bool:
        return self.function in ("output2", "output3")

    @property
    def is_bidir(self) -> bool:
        return self.function == "bidir"

    @property
    def is_control(self) -> bool:
        return self.function in ("control", "controlr")


@dataclass(frozen=True)
class BsdlDevice:
    """Dispositivo JTAG descrito por um arquivo BSDL."""

    entity_name: str
    ir_length: int
    instructions: tuple[BsdlInstruction, ...]
    idcode_pattern: str      # string binária de 32 bits MSB-first; X = don't-care
    boundary_length: int
    cells: tuple[BsdlCell, ...]   # ordenadas da mais alta (TDI) para a mais baixa (TDO)
    pin_map: dict[str, list[str]] # porta → lista de pinos físicos (sempre lista)

    # ------------------------------------------------------------------
    # Lookup de instruções
    # ------------------------------------------------------------------

    def instruction(self, name: str) -> BsdlInstruction:
        """Retorna a instrução pelo nome (case-insensitive)."""
        nu = name.upper()
        for instr in self.instructions:
            if instr.name == nu:
                return instr
        raise KeyError(f"Instrução '{name}' não encontrada em '{self.entity_name}'")

    def opcode(self, name: str) -> str:
        """Retorna o opcode binário de uma instrução pelo nome."""
        return self.instruction(name).opcode

    # ------------------------------------------------------------------
    # Lookup de células
    # ------------------------------------------------------------------

    def cells_for_port(self, port: str) -> tuple[BsdlCell, ...]:
        """Retorna todas as células associadas a uma porta (case-insensitive)."""
        pu = port.upper()
        return tuple(c for c in self.cells if c.port.upper() == pu)

    def cell(self, num: int) -> BsdlCell:
        """Retorna a célula pelo número."""
        for c in self.cells:
            if c.num == num:
                return c
        raise KeyError(f"Célula {num} não encontrada")

    # ------------------------------------------------------------------
    # IDCODE
    # ------------------------------------------------------------------

    def idcode_mask_value(self) -> tuple[int, int]:
        """Retorna (mask, value) para verificação do IDCODE ignorando bits X.

        Um bit X no padrão significa don't-care — sua posição não entra na mask.
        Uso: (lido & mask) == value
        """
        mask = 0
        value = 0
        for i, ch in enumerate(self.idcode_pattern):
            bit_pos = 31 - i  # MSB primeiro
            if ch == "1":
                mask |= 1 << bit_pos
                value |= 1 << bit_pos
            elif ch == "0":
                mask |= 1 << bit_pos
        return mask, value

    def matches_idcode(self, read_value: int) -> bool:
        """Verifica se um IDCODE lido corresponde a este dispositivo."""
        mask, value = self.idcode_mask_value()
        return (read_value & mask) == value

    # ------------------------------------------------------------------
    # Preload / EXTEST helpers
    # ------------------------------------------------------------------

    def safe_preload(self) -> list[int]:
        """Gera o vetor de preload seguro (todos os bits no valor 'safe').

        Retorna lista de `boundary_length` bits ordenada célula-alta → célula-baixa.
        Use para carregar no BSR antes de EXTEST.
        """
        bits = [0] * self.boundary_length
        for cell in self.cells:
            safe = cell.safe
            if safe == "1":
                bits[self.boundary_length - 1 - cell.num] = 1
            elif safe == "0":
                bits[self.boundary_length - 1 - cell.num] = 0
            # "X" → mantém 0
        return bits
