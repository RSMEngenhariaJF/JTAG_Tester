"""BoardConfig — descrição portável de uma placa-alvo.

Cada placa suportada expõe uma instância ``BOARD: BoardConfig`` em
``src/boards/<nome_da_placa>.py``.

Para mudar de placa basta:
    1. Criar/selecionar o arquivo em src/boards/
    2. Chamar set_active_board(BOARD) na inicialização (ou via GUI)

Os testes embutidos leem a configuração em tempo de execução via
get_active_board(), mas aceitam uma instância explícita no construtor
para testes unitários offline:

    LedTest(BOARD_F446).run(fake_pal)   # sem hardware, sem estado global
"""

from __future__ import annotations

from dataclasses import dataclass


# ── Blocos de configuração de pino ────────────────────────────────────────────

@dataclass(frozen=True)
class PinConfig:
    """Descreve um pino GPIO com Alternate Function."""

    port: str   # "GPIOA"
    pin:  int   # 5
    af:   int   # 5  (valor do campo AFRx, ex.: AF5 = SPI1 no F4)

    # Helpers para montar nomes de campos SVD
    @property
    def moder_field(self) -> str:
        return f"MODER{self.pin}"

    @property
    def afr_reg(self) -> str:
        return "AFRH" if self.pin >= 8 else "AFRL"

    @property
    def afr_field(self) -> str:
        prefix = "AFRH" if self.pin >= 8 else "AFRL"
        return f"{prefix}{self.pin}"

    @property
    def odr_field(self) -> str:
        return f"ODR{self.pin}"

    @property
    def idr_field(self) -> str:
        return f"IDR{self.pin}"


@dataclass(frozen=True)
class UsartConfig:
    """Configuração de USART para o teste de loopback."""
    n:             int         # número da USART (1, 2, ...)
    tx:            PinConfig
    rx:            PinConfig
    clock_reg:     str         # "APB2ENR"
    clock_field:   str         # "USART1EN"
    loopback_baud: int = 9600


@dataclass(frozen=True)
class SpiConfig:
    """Configuração de SPI para o teste de loopback."""
    n:            int         # número da SPI (1, 2, ...)
    sck:          PinConfig
    miso:         PinConfig
    mosi:         PinConfig
    clock_reg:    str         # "APB2ENR"
    clock_field:  str         # "SPI1EN"


# ── Configuração completa de placa ────────────────────────────────────────────

@dataclass(frozen=True)
class BoardConfig:
    """Configuração completa de uma placa-alvo.

    Todos os campos são imutáveis (frozen=True).
    Crie uma instância ``BOARD`` em ``src/boards/<nome>.py`` e
    registre-a com ``set_active_board(BOARD)`` ao iniciar a aplicação.

    Campos
    ------
    project_code   Código de projeto associado, ex. "2180.0720.00".
                   Aparece no título da janela para identificar a config ativa.
    name           Nome legível da placa, ex. "NUCLEO-F446RE".
    target         String de alvo do pyOCD, ex. "stm32f446retx".
    svd_path       Caminho relativo à raiz do repositório para o SVD.
    """

    # ── Identificação ────────────────────────────────────────────────────────
    project_code: str    # "2180.0720.00"
    name:         str    # "NUCLEO-F446RE"

    # ── Conexão ──────────────────────────────────────────────────────────────
    target:   str   # "stm32f446retx"
    svd_path: str   # "devices/stm32f446/STM32F446.svd"

    # ── Identidade do chip ───────────────────────────────────────────────────
    dbgmcu_idcode_addr: int   # 0xE0042000
    expected_dev_id:    int   # 0x421

    # ── SRAM ─────────────────────────────────────────────────────────────────
    sram_base: int   # 0x20000000

    # ── LED ──────────────────────────────────────────────────────────────────
    led_port:        str   # "GPIOA"
    led_pin:         int   # 5
    led_clock_reg:   str   # "AHB1ENR"
    led_clock_field: str   # "GPIOAEN"

    # ── Botão ────────────────────────────────────────────────────────────────
    btn_port:        str    # "GPIOC"
    btn_pin:         int    # 13
    btn_clock_reg:   str    # "AHB1ENR"
    btn_clock_field: str    # "GPIOCEN"
    btn_active_low:  bool   # True → pressionado = nível 0

    # ── Clocks obrigatórios (verificados pelo ClockTest) ─────────────────────
    # Cada tupla: (registrador_rcc, campo_svd, label_legível)
    # Ex.: ("AHB1ENR", "GPIOAEN", "GPIOA")
    required_clocks: tuple[tuple[str, str, str], ...]

    # ── Periféricos seriais ───────────────────────────────────────────────────
    usart: UsartConfig
    spi:   SpiConfig

    def __str__(self) -> str:
        return f"{self.project_code} — {self.name}"


# ── Singleton global ──────────────────────────────────────────────────────────

_active: BoardConfig | None = None


def set_active_board(cfg: BoardConfig) -> None:
    """Define a placa ativa globalmente (chamado pela GUI ou CLI)."""
    global _active
    _active = cfg


def get_active_board() -> BoardConfig:
    """Retorna a placa ativa. Lança RuntimeError se nenhuma foi definida."""
    if _active is None:
        raise RuntimeError(
            "Nenhuma placa configurada. "
            "Chame set_active_board(BOARD) ou selecione uma placa na GUI."
        )
    return _active
