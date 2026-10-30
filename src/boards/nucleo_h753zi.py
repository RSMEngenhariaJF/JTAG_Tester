"""Configuração da placa NUCLEO-H753ZI (STM32H753ZIT6, Cortex-M7).

Pinagem (Nucleo-144, manual UM2407 — conferir a revisão da placa)
-----------------------------------------------------------------
  LED LD1 (verde)    : PB0
  LED LD2 (amarelo)  : PE1
  LED LD3 (vermelho) : PB14
  Botão USER B1      : PC13  (ativo-alto: pressionado = 1)
  USART3 TX / RX     : PD8 / PD9  (Virtual COM do STLINK-V3)

Diferenças em relação à NUCLEO-F446RE
-------------------------------------
* Conexão "under-reset": firmwares que entram em baixo consumo derrubam o
  acesso ao núcleo no modo normal. Conectando com reset, o pyOCD liga os bits
  de debug em baixo consumo (DBGMCU_CR) e o firmware é liberado em seguida.
* GPIO no AHB4 (RCC_AHB4ENR) e DBGMCU_IDCODE em 0x5C001000.
* USART e SPI do H7 têm registradores diferentes dos do F4 (ISR/TDR/RDR; SPI
  v2): os loopbacks embutidos ficam desligados (SKIP). Para velocidade de
  USART use o agente na RAM (TESTES_PLATAFORMA/H7/teste_usart_agente_h7.py).
"""

from core.board.config import BoardConfig

BOARD = BoardConfig(
    # ── Identificação ────────────────────────────────────────────────────────
    project_code = "—",
    name         = "NUCLEO-H753ZI",

    # ── Conexão ──────────────────────────────────────────────────────────────
    target               = "stm32h753zitx",   # = Mcu.UserName do CubeMX (importação .ioc)
    pyocd_target         = "stm32h743xx",     # alvo embutido no pyOCD (H753 = H743 + cripto)
    connect_mode         = "under-reset",
    resume_after_connect = True,
    gpio_clock_reg       = "AHB4ENR",
    svd_path             = "devices/stm32h753/STM32H753.svd",

    # ── Identidade do chip ───────────────────────────────────────────────────
    dbgmcu_idcode_addr = 0x5C001000,
    expected_dev_id    = 0x450,           # STM32H742/H743/H753/H750

    # ── SRAM: AXI SRAM (D1), acessível pelo debugger com o núcleo rodando ────
    sram_base = 0x24000000,

    # ── LED LD1 verde (PB0) ──────────────────────────────────────────────────
    led_port        = "GPIOB",
    led_pin         = 0,
    led_clock_reg   = "AHB4ENR",
    led_clock_field = "GPIOBEN",

    # ── Botão USER B1 (PC13, ativo-alto) ─────────────────────────────────────
    btn_port        = "GPIOC",
    btn_pin         = 13,
    btn_clock_reg   = "AHB4ENR",
    btn_clock_field = "GPIOCEN",
    btn_active_low  = False,

    # ── Clocks que devem estar habilitados pelo firmware ──────────────────────
    required_clocks = (
        ("AHB4ENR", "GPIOBEN", "GPIOB"),
        ("AHB4ENR", "GPIOCEN", "GPIOC"),
        ("AHB4ENR", "GPIOEEN", "GPIOE"),
    ),

    # ── USART / SPI: drivers atuais são do F4 → loopbacks em SKIP ────────────
    usart = None,
    spi   = None,
)
