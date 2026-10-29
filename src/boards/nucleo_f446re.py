"""Configuração da placa NUCLEO-F446RE (STM32F446RE).

Para usar esta placa, chame na inicialização da aplicação::

    from boards.nucleo_f446re import BOARD
    from core.board.config import set_active_board
    set_active_board(BOARD)

Para criar uma configuração derivada (ex.: mesmo chip, outro projeto)::

    from boards.nucleo_f446re import BOARD
    import dataclasses
    MEU_BOARD = dataclasses.replace(BOARD, project_code="2180.0720.01")

Pinagem (conector CN9 da NUCLEO-F446RE)
-----------------------------------------
  LED LD2    : PA5  (D13)
  Botão USER : PC13
  USART1 TX  : PA9  (D8)   AF7 — loopback: conectar D8 a D2
  USART1 RX  : PA10 (D2)   AF7
  SPI1 SCK   : PA5  (D13)  AF5 — compartilhado com LED LD2
  SPI1 MISO  : PA6  (D12)  AF5 — loopback: conectar D11 a D12
  SPI1 MOSI  : PA7  (D11)  AF5
"""

from core.board.config import BoardConfig, PinConfig, SpiConfig, UsartConfig

BOARD = BoardConfig(
    # ── Identificação ────────────────────────────────────────────────────────
    project_code = "—",            # preencha com o código do projeto, ex. "2180.0720.00"
    name         = "NUCLEO-F446RE",

    # ── Conexão via pyOCD ─────────────────────────────────────────────────────
    target   = "stm32f446retx",
    svd_path = "devices/stm32f446/STM32F446.svd",

    # ── Identidade do chip ────────────────────────────────────────────────────
    dbgmcu_idcode_addr = 0xE0042000,
    expected_dev_id    = 0x421,       # STM32F446

    # ── SRAM interna ─────────────────────────────────────────────────────────
    sram_base = 0x20000000,

    # ── LED LD2 (PA5, D13) ────────────────────────────────────────────────────
    led_port        = "GPIOA",
    led_pin         = 5,
    led_clock_reg   = "AHB1ENR",
    led_clock_field = "GPIOAEN",

    # ── Botão USER (PC13, ativo-baixo com pull-up) ────────────────────────────
    btn_port        = "GPIOC",
    btn_pin         = 13,
    btn_clock_reg   = "AHB1ENR",
    btn_clock_field = "GPIOCEN",
    btn_active_low  = True,

    # ── Clocks que devem estar habilitados pelo firmware ──────────────────────
    required_clocks = (
        ("AHB1ENR", "GPIOAEN", "GPIOA"),
        ("AHB1ENR", "GPIOCEN", "GPIOC"),
    ),

    # ── USART1 loopback: D8 (PA9/TX) ──► D2 (PA10/RX) ───────────────────────
    usart = UsartConfig(
        n            = 1,
        tx           = PinConfig(port="GPIOA", pin=9,  af=7),
        rx           = PinConfig(port="GPIOA", pin=10, af=7),
        clock_reg    = "APB2ENR",
        clock_field  = "USART1EN",
        loopback_baud = 9600,
    ),

    # ── SPI1 loopback: D11 (PA7/MOSI) ──► D12 (PA6/MISO) ────────────────────
    spi = SpiConfig(
        n           = 1,
        sck         = PinConfig(port="GPIOA", pin=5, af=5),
        miso        = PinConfig(port="GPIOA", pin=6, af=5),
        mosi        = PinConfig(port="GPIOA", pin=7, af=5),
        clock_reg   = "APB2ENR",
        clock_field = "SPI1EN",
    ),
)
