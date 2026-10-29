"""Exemplo — UART: Loopback USART (TX → RX).

Reutiliza o UsartLoopbackTest embutido na plataforma.
Os pinos, a USART e o baud rate são lidos automaticamente
do BoardConfig selecionado na GUI.

Na NUCLEO-F446RE (board padrão):
    D8  (PA9  = USART1_TX)  ──►──  D2 (PA10 = USART1_RX)

Para outra placa, altere o arquivo em src/boards/<nome>.py —
nenhuma linha de código de teste precisa mudar.
"""

from tests_builtin.usart_loopback import UsartLoopbackTest  # noqa: F401

# UsartLoopbackTest é uma subclasse de BuiltinTest.
# O PluginLoader encontra e instancia automaticamente.
# Ao executar, chama get_active_board() para obter pinos e USART.
