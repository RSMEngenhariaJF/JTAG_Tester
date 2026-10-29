"""LedTest — testa o LED de status definido no BoardConfig."""

from __future__ import annotations

from core.board.config import BoardConfig, get_active_board
from core.pal.access import PeripheralAccessLayer
from tests_builtin.base import BuiltinTest, TestResult


class LedTest(BuiltinTest):
    name        = "LED"
    description = "Testa LED de status: habilita saída, SET/RESET via BSRR, verifica ODR"

    def __init__(self, cfg: BoardConfig | None = None) -> None:
        self._cfg = cfg

    def _run(self, pal: PeripheralAccessLayer) -> TestResult:
        cfg  = self._cfg if self._cfg is not None else get_active_board()
        port = cfg.led_port
        pin  = cfg.led_pin

        # Habilita clock da porta GPIO do LED
        pal.modify_field("RCC", cfg.led_clock_reg, cfg.led_clock_field, 1)

        original_moder = pal.read_field(port, "MODER", f"MODER{pin}")
        original_odr   = pal.read_field(port, "ODR",   f"ODR{pin}")

        try:
            # Configura como saída push-pull (MODER = 0b01)
            pal.modify_field(port, "MODER", f"MODER{pin}", 0b01)

            # SET via BSRR (bits[15:0] setam o pino)
            pal.write_reg(port, "BSRR", 1 << pin)
            nivel_alto = pal.read_field(port, "ODR", f"ODR{pin}")

            # RESET via BSRR (bits[31:16] resetam o pino)
            pal.write_reg(port, "BSRR", 1 << (pin + 16))
            nivel_baixo = pal.read_field(port, "ODR", f"ODR{pin}")

            if nivel_alto == 1 and nivel_baixo == 0:
                return self._pass(
                    f"LED {port}{pin}: SET=1 RESET=0 via BSRR OK"
                )
            return self._fail(
                f"LED {port}{pin}: SET={nivel_alto} RESET={nivel_baixo} (esperado 1 e 0)",
                measured=(nivel_alto, nivel_baixo),
                expected=(1, 0),
            )

        finally:
            pal.modify_field(port, "MODER", f"MODER{pin}", original_moder)
            pal.modify_field(port, "ODR",   f"ODR{pin}",   original_odr)
