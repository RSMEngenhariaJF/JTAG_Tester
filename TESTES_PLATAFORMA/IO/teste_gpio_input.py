"""Exemplo — IO: Leitura de pino de entrada.

Verifica se o pino de botão da placa selecionada na GUI pode ser lido e
reporta o estado atual (HIGH ou LOW). Montado como bancada modular (src/testbench):

    estímulo  Sample(1)         — uma leitura, sem acionar nada
    monitor   GpioInputMonitor  — pino como entrada, nível elétrico (raw)
    decisão   Report            — registra o nível (não reprova)

Por padrão, usa o pino de botão do BoardConfig (btn_port / btn_pin). Para
conferir um nível esperado, use o bloco "GPIO — Nível de entrada" no Plano de
testes.
"""

from testbench import ComposedTest, Testbench
from testbench.decision import Report
from testbench.gpio import GpioInputMonitor
from testbench.stimulus import Sample
from tests_builtin.params import Signal


class GpioInputTest(ComposedTest):
    name        = "GPIO Input"
    description = (
        "Lê o pino de botão do BoardConfig como entrada "
        "e reporta o nível lógico atual."
    )

    def build(self) -> Testbench:
        from core.board.config import get_active_board
        cfg = get_active_board()
        self.btn = Signal("botao", cfg.btn_port, cfg.btn_pin, cfg.btn_active_low)
        mon = GpioInputMonitor(self.btn, configure=True, raw=True)

        def rotulo(level: int) -> str:
            if self.btn.active_low:
                return "HIGH (solto)" if level else "LOW (pressionado)"
            return "HIGH (pressionado)" if level else "LOW (solto)"

        return Testbench(monitors=[mon], stimulus=Sample(1),
                         decisions=[Report(mon.name, describe=rotulo,
                                           label=f"{self.btn.port}.{self.btn.pin}")])

    def summary(self, trace, verdicts) -> str:
        return verdicts[0].message.replace("=", " = ", 1)
