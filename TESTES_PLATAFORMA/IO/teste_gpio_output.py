"""Exemplo — IO: Teste de saída GPIO.

Verifica se o pino de LED da placa selecionada na GUI consegue
ir para nível alto e baixo, lendo de volta o ODR.

Por padrão, usa os pinos definidos no BoardConfig (led_port / led_pin).
Para testar um pino diferente, substitua as constantes abaixo por
valores fixos e comente a seção "Modo automático".
"""

from tests_builtin.base import BuiltinTest, TestResult

# ─── Modo fixo: descomente e preencha para usar pino específico ───────────────
# PORT        = "GPIOA"
# PIN         = 5
# CLOCK_REG   = "AHB1ENR"
# CLOCK_FIELD = "GPIOAEN"
# ─────────────────────────────────────────────────────────────────────────────


class GpioOutputTest(BuiltinTest):
    name        = "GPIO Output"
    description = (
        "Verifica saída no pino de LED do BoardConfig: "
        "SET→ODR=1 e RESET→ODR=0 via BSRR."
    )

    def _run(self, pal) -> TestResult:
        # Modo automático: lê a placa selecionada na GUI
        from core.board.config import get_active_board
        cfg         = get_active_board()
        port        = cfg.led_port
        pin         = cfg.led_pin
        clock_reg   = cfg.led_clock_reg
        clock_field = cfg.led_clock_field

        # Habilita clock do GPIO
        pal.modify_field("RCC", clock_reg, clock_field, 1)

        # Salva estado para restaurar no finally
        orig_moder = pal.read_field(port, "MODER", f"MODER{pin}")
        orig_odr   = pal.read_field(port, "ODR",   f"ODR{pin}")

        try:
            # Configura como saída push-pull (MODER = 0b01)
            pal.modify_field(port, "MODER", f"MODER{pin}", 0b01)

            # SET via BSRR (bits[15:0] colocam o pino em nível alto)
            pal.write_reg(port, "BSRR", 1 << pin)
            level_high = pal.read_field(port, "ODR", f"ODR{pin}")

            # RESET via BSRR (bits[31:16] colocam o pino em nível baixo)
            pal.write_reg(port, "BSRR", 1 << (pin + 16))
            level_low = pal.read_field(port, "ODR", f"ODR{pin}")

            if level_high == 1 and level_low == 0:
                return self._pass(f"{port}.{pin} SET=1 RESET=0 OK")

            return self._fail(
                f"{port}.{pin} SET={level_high} RESET={level_low} "
                f"(esperado 1 e 0)",
                measured=(level_high, level_low),
                expected=(1, 0),
            )
        finally:
            # Restaura MODER e ODR originais (sempre, mesmo em erro)
            pal.modify_field(port, "MODER", f"MODER{pin}", orig_moder)
            pal.modify_field(port, "ODR",   f"ODR{pin}",   orig_odr)
