"""ClockTest — verifica clocks essenciais definidos no BoardConfig."""

from __future__ import annotations

from core.board.config import BoardConfig, get_active_board
from core.pal.access import PeripheralAccessLayer
from tests_builtin.base import BuiltinTest, TestResult


class ClockTest(BuiltinTest):
    name        = "Clocks"
    description = "Verifica clocks obrigatórios definidos no BoardConfig (required_clocks)"

    def __init__(self, cfg: BoardConfig | None = None) -> None:
        self._cfg = cfg

    def _run(self, pal: PeripheralAccessLayer) -> TestResult:
        cfg = self._cfg if self._cfg is not None else get_active_board()

        missing: list[str] = []
        for reg, field, label in cfg.required_clocks:
            if not pal.read_field("RCC", reg, field):
                missing.append(label)

        if missing:
            return self._fail(
                f"Clock(s) desabilitado(s): {', '.join(missing)}",
                measured=missing,
                expected=[lbl for _, _, lbl in cfg.required_clocks],
            )

        labels = [lbl for _, _, lbl in cfg.required_clocks]
        return self._pass(f"Clocks habilitados: {', '.join(labels)}")
