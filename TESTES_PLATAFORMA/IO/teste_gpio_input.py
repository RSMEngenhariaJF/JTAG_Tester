"""Exemplo — IO: Leitura de pino de entrada.

Verifica se o pino de botão da placa selecionada na GUI pode ser
lido e reporta o estado atual (HIGH ou LOW).

Por padrão, usa os pinos definidos no BoardConfig (btn_port / btn_pin).
Para testar um pino diferente, substitua as constantes abaixo.
"""

from tests_builtin.base import BuiltinTest, TestResult

# ─── Modo fixo: descomente e preencha para usar pino específico ───────────────
# PORT        = "GPIOC"
# PIN         = 13
# CLOCK_REG   = "AHB1ENR"
# CLOCK_FIELD = "GPIOCEN"
# ACTIVE_LOW  = True   # True = pressionado é nível 0 (com pull-up)
# ─────────────────────────────────────────────────────────────────────────────


class GpioInputTest(BuiltinTest):
    name        = "GPIO Input"
    description = (
        "Lê o pino de botão do BoardConfig como entrada "
        "e reporta o nível lógico atual."
    )

    def _run(self, pal) -> TestResult:
        # Modo automático: lê a placa selecionada na GUI
        from core.board.config import get_active_board
        cfg         = get_active_board()
        port        = cfg.btn_port
        pin         = cfg.btn_pin
        clock_reg   = cfg.btn_clock_reg
        clock_field = cfg.btn_clock_field
        active_low  = cfg.btn_active_low

        pal.modify_field("RCC", clock_reg, clock_field, 1)

        orig_moder = pal.read_field(port, "MODER", f"MODER{pin}")
        try:
            # Garante modo entrada (MODER = 0b00)
            pal.modify_field(port, "MODER", f"MODER{pin}", 0b00)
            level = bool(pal.read_field(port, "IDR", f"IDR{pin}"))

            if active_low:
                label = "HIGH (solto)" if level else "LOW (pressionado)"
            else:
                label = "HIGH (pressionado)" if level else "LOW (solto)"

            return self._pass(
                f"{port}.{pin} = {label}",
                measured=level,
            )
        finally:
            pal.modify_field(port, "MODER", f"MODER{pin}", orig_moder)
