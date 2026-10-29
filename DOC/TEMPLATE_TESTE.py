"""TEMPLATE — Copie este arquivo e adapte para criar seu próprio teste.

Passos rápidos:
    1. Copie: cp TEMPLATE_TESTE.py TESTES_PLATAFORMA/MINHA_AREA/teste_meu.py
    2. Renomeie a classe e preencha name / description
    3. Implemente _run() com a lógica do teste
    4. Na GUI: selecione a placa → "Carregar Plugin..." → selecione o arquivo
    5. Clique "Executar Suite"

Guia completo: DOC/GUIA_CRIACAO_DE_TESTES.md
"""

# ─── Imports obrigatórios ─────────────────────────────────────────────────────
from tests_builtin.base import BuiltinTest, TestResult, TestStatus

# ─── Imports opcionais — use o que precisar ──────────────────────────────────
# from core.board.config import get_active_board   # pinos/config da placa ativa
# from instruments.usart      import UsartInstrument
# from instruments.spi        import SpiInstrument, SpiBaudDiv
# from instruments.rcc_helper import detect_pclk2
# import time


# ═════════════════════════════════════════════════════════════════════════════
# PADRÃO A — Teste portável (usa configuração do BoardConfig)
#
# Use quando o teste exercita hardware da placa (LED, botão, USART, SPI…).
# Ao trocar de placa na GUI, o teste automaticamente usa os pinos corretos
# sem nenhuma edição de código.
# ═════════════════════════════════════════════════════════════════════════════

class MeuTestePortavel(BuiltinTest):

    name        = "Meu Teste Portavel"
    description = "Descreva o que este teste verifica e quais conexões físicas são necessárias."

    def _run(self, pal) -> TestResult:
        # 1. Obtém a configuração da placa selecionada na GUI
        from core.board.config import get_active_board
        cfg = get_active_board()

        # 2. Lê parâmetros da placa (ex.: LED e botão)
        port        = cfg.led_port         # "GPIOA"
        pin         = cfg.led_pin          # 5
        clock_reg   = cfg.led_clock_reg    # "AHB1ENR"
        clock_field = cfg.led_clock_field  # "GPIOAEN"

        # 3. Habilita clock
        pal.modify_field("RCC", clock_reg, clock_field, 1)

        # 4. Salva estado original para restaurar no finally
        orig_moder = pal.read_field(port, "MODER", f"MODER{pin}")

        try:
            # 5. Sua lógica de teste aqui
            valor_lido = pal.read_field(port, "MODER", f"MODER{pin}")
            valor_ok   = 0b00   # ex.: esperado INPUT

            if valor_lido == valor_ok:
                return self._pass(
                    f"{port}.{pin} MODER={valor_lido} (OK)",
                    measured=valor_lido,
                    expected=valor_ok,
                )
            return self._fail(
                f"{port}.{pin} MODER={valor_lido}, esperado {valor_ok}",
                measured=valor_lido,
                expected=valor_ok,
            )

        finally:
            # 6. Restaura SEMPRE — mesmo se der exceção no try
            pal.modify_field(port, "MODER", f"MODER{pin}", orig_moder)


# ═════════════════════════════════════════════════════════════════════════════
# PADRÃO B — Teste com constantes fixas (verifica firmware, não hardware)
#
# Use quando o teste verifica configuração do firmware (baud rate, PWM freq…).
# As constantes são parâmetros da aplicação, não da placa física.
# ═════════════════════════════════════════════════════════════════════════════

# ─── Constantes configuráveis ─────────────────────────────────────────────────
PERIFERICO  = "USART2"    # nome do periférico no SVD
REGISTRADOR = "BRR"       # nome do registrador
CAMPO       = "DIV_Mantissa"
VALOR_OK    = 8           # valor esperado (ex.: BRR para 115200 @ 16 MHz)
# ─────────────────────────────────────────────────────────────────────────────


class MeuTesteDeConfig(BuiltinTest):

    name        = "Meu Teste de Config"
    description = "Verifica se o firmware configurou corretamente o periférico."

    def _run(self, pal) -> TestResult:
        valor_lido = pal.read_field(PERIFERICO, REGISTRADOR, CAMPO)

        if valor_lido == VALOR_OK:
            return self._pass(
                f"{PERIFERICO}.{REGISTRADOR}.{CAMPO} = {valor_lido} (OK)",
                measured=valor_lido,
                expected=VALOR_OK,
            )
        return self._fail(
            f"{PERIFERICO}.{REGISTRADOR}.{CAMPO} = {valor_lido}, "
            f"esperado {VALOR_OK}",
            measured=valor_lido,
            expected=VALOR_OK,
        )
