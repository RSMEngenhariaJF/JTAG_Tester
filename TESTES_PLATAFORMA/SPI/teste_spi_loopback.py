"""Exemplo — SPI: Loopback SPI (MOSI → MISO).

Reutiliza o SpiLoopbackTest embutido na plataforma.
Os pinos, a SPI e o divisor de clock são lidos automaticamente
do BoardConfig selecionado na GUI.

Na NUCLEO-F446RE (board padrão):
    D11 (PA7 = SPI1_MOSI)  ──►──  D12 (PA6 = SPI1_MISO)
    (PA5 = SPI1_SCK compartilha o LED LD2 — piscará brevemente)

Para outra placa, altere o arquivo em src/boards/<nome>.py —
nenhuma linha de código de teste precisa mudar.
"""

from tests_builtin.spi_loopback import SpiLoopbackTest  # noqa: F401

# SpiLoopbackTest é uma subclasse de BuiltinTest.
# O PluginLoader encontra e instancia automaticamente.
# Ao executar, chama get_active_board() para obter pinos e SPI.
