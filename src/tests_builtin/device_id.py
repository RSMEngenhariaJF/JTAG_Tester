"""DeviceIdTest — verifica identidade do microcontrolador via DBGMCU_IDCODE."""

from __future__ import annotations

from core.board.config import BoardConfig, get_active_board
from core.pal.access import PeripheralAccessLayer
from tests_builtin.base import BuiltinTest, TestResult


class DeviceIdTest(BuiltinTest):
    name        = "DeviceId"
    description = "Lê DBGMCU_IDCODE e verifica DEV_ID esperado pela placa configurada"

    def __init__(self, cfg: BoardConfig | None = None) -> None:
        self._cfg = cfg

    def _run(self, pal: PeripheralAccessLayer) -> TestResult:
        cfg = self._cfg if self._cfg is not None else get_active_board()

        idcode = pal.mem.read_mem32(cfg.dbgmcu_idcode_addr)
        dev_id = idcode & 0xFFF
        rev_id = (idcode >> 16) & 0xFFFF

        if dev_id == cfg.expected_dev_id:
            return self._pass(
                f"DEV_ID=0x{dev_id:03X}  REV_ID=0x{rev_id:04X}",
                measured=dev_id,
                expected=cfg.expected_dev_id,
            )

        return self._fail(
            f"DEV_ID incorreto: obtido 0x{dev_id:03X}, esperado 0x{cfg.expected_dev_id:03X}",
            measured=dev_id,
            expected=cfg.expected_dev_id,
        )
