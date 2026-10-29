"""ButtonTest — verifica o botão de usuário definido no BoardConfig."""

from __future__ import annotations

from core.board.config import BoardConfig, get_active_board
from core.pal.access import PeripheralAccessLayer
from tests_builtin.base import BuiltinTest, TestResult


class ButtonTest(BuiltinTest):
    name        = "Button"
    description = "Verifica botão de usuário: modo INPUT e leitura do estado lógico"

    def __init__(self, cfg: BoardConfig | None = None) -> None:
        self._cfg = cfg

    def _run(self, pal: PeripheralAccessLayer) -> TestResult:
        cfg  = self._cfg if self._cfg is not None else get_active_board()
        port = cfg.btn_port
        pin  = cfg.btn_pin

        # Habilita clock da porta GPIO do botão
        pal.modify_field("RCC", cfg.btn_clock_reg, cfg.btn_clock_field, 1)

        moder_val = pal.read_field(port, "MODER", f"MODER{pin}")

        # MODER = 0b00 → entrada
        if moder_val != 0b00:
            return self._fail(
                f"{port}{pin} não está em modo INPUT "
                f"(MODER{pin}={moder_val:#04b}, esperado 0b00)",
                measured=moder_val,
                expected=0b00,
            )

        state = bool(pal.read_field(port, "IDR", f"IDR{pin}"))
        if cfg.btn_active_low:
            label = "HIGH (solto)" if state else "LOW (pressionado)"
        else:
            label = "HIGH (pressionado)" if state else "LOW (solto)"

        return self._pass(f"{port}{pin} legível: {label}", measured=state)
