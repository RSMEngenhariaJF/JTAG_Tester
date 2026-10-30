"""Exemplo — IO: Teste de saída GPIO.

Verifica se o pino de LED da placa selecionada na GUI consegue ir para nível
alto e baixo, lendo de volta o ODR. Montado como bancada modular (src/testbench):

    estímulo  Levels([1, 0])     — SET e RESET
    driver    GpioOutputDriver   — saída push-pull, níveis elétricos (raw)
    monitor   GpioLatchMonitor   — lê o ODR
    decisão   FollowsDrive       — o ODR acompanhou os dois níveis?

Por padrão, usa o pino de LED do BoardConfig (led_port / led_pin). Para testar
outro pino, troque o Signal em build() — ou use o bloco "Piscar LED" no
Plano de testes, que escolhe os pinos pelo Pinout do projeto.
"""

from testbench import ComposedTest, Testbench
from testbench.decision import FollowsDrive
from testbench.gpio import GpioLatchMonitor, GpioOutputDriver
from testbench.stimulus import Levels
from tests_builtin.params import Signal


class GpioOutputTest(ComposedTest):
    name        = "GPIO Output"
    description = (
        "Verifica saída no pino de LED do BoardConfig: "
        "SET→ODR=1 e RESET→ODR=0 via BSRR."
    )

    def build(self) -> Testbench:
        from core.board.config import get_active_board
        cfg = get_active_board()
        self.led = Signal("led", cfg.led_port, cfg.led_pin)
        drv = GpioOutputDriver(self.led, raw=True)
        mon = GpioLatchMonitor(self.led, raw=True)
        return Testbench([drv], [mon], Levels(drv.name, [1, 0]),
                         [FollowsDrive(mon.name, drv.name, label="led")])

    def summary(self, trace, verdicts) -> str:
        lidos = trace.series(f"odr:{self.led.name}")
        estado = "OK" if all(v.ok for v in verdicts) else "(esperado 1 e 0)"
        return f"{self.led.port}.{self.led.pin} SET={lidos[0]} RESET={lidos[1]} {estado}" \
            if len(lidos) == 2 else "; ".join(v.message for v in verdicts)
