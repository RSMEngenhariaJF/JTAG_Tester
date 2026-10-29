"""SRAMTest — verifica leitura/escrita na SRAM interna."""

from __future__ import annotations

from core.board.config import BoardConfig, get_active_board
from core.pal.access import PeripheralAccessLayer
from tests_builtin.base import BuiltinTest, TestResult

_PATTERN = 0xA5A5A5A5


class SRAMTest(BuiltinTest):
    name        = "SRAM"
    description = "Escreve padrão 0xA5A5A5A5 no sram_base e verifica leitura"

    def __init__(self, cfg: BoardConfig | None = None) -> None:
        self._cfg = cfg

    def _run(self, pal: PeripheralAccessLayer) -> TestResult:
        cfg  = self._cfg if self._cfg is not None else get_active_board()
        addr = cfg.sram_base

        original = pal.mem.read_mem32(addr)
        try:
            pal.mem.write_mem32(addr, _PATTERN)
            readback = pal.mem.read_mem32(addr)
            if readback != _PATTERN:
                return self._fail(
                    f"R/W mismatch em 0x{addr:08X}: "
                    f"escrito 0x{_PATTERN:08X}, lido 0x{readback:08X}",
                    measured=readback,
                    expected=_PATTERN,
                )
            return self._pass(
                f"0x{addr:08X}: R/W OK (padrão 0x{_PATTERN:08X})",
                measured=addr,
            )
        finally:
            pal.mem.write_mem32(addr, original)
