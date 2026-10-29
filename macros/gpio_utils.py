"""Macros utilitárias para operações GPIO.

Carregue este arquivo na GUI ou com::

    from core.macros import load_macros
    load_macros("macros/gpio_utils.py")

Depois use nos testes::

    from core.macros import get_macro

    get_macro("reset_board")(pal, hold_ms=100)
    get_macro("led_blink")(pal, n=5)
    ok = get_macro("button_wait")(pal, timeout_ms=3000)
"""

from __future__ import annotations

import time

from core.macros import macro
from core.project.config import get_active_project


# ── Reset ─────────────────────────────────────────────────────────────────────

@macro(category="GPIO")
def reset_board(pal, *, hold_ms: int = 100, signal: str = "reset") -> None:
    """Pulsa o pino de reset da placa pelo tempo especificado.

    Parâmetros:
        hold_ms — duração do pulso de reset em ms (padrão: 100)
        signal  — nome do sinal de reset no ProjectConfig (padrão: "reset")

    O pino é tratado como ativo-baixo se ``PinDef.active_low == True``.
    """
    from core.instruments.gpio import GpioInstrument

    proj = get_active_project()
    if proj is None or not proj.has_pin(signal):
        raise RuntimeError(
            f"Sinal '{signal}' não definido no projeto. "
            "Configure o pino de reset no ProjectConfig."
        )

    pin_def = proj.pin(signal)
    gpio    = GpioInstrument(pin_def.port, pal)
    pin     = gpio.pin(pin_def.pin)

    # Asserta reset (lógica invertida se active_low)
    if pin_def.active_low:
        pin.clear()
    else:
        pin.set()

    time.sleep(hold_ms / 1000.0)

    # Desasserta
    if pin_def.active_low:
        pin.set()
    else:
        pin.clear()

    time.sleep(0.05)   # aguarda MCU iniciar


# ── LED ───────────────────────────────────────────────────────────────────────

@macro(category="GPIO")
def led_blink(pal, *, n: int = 3, period_ms: int = 200, signal: str = "led") -> None:
    """Pisca o LED N vezes com o período especificado.

    Parâmetros:
        n         — número de piscadas (padrão: 3)
        period_ms — período de cada piscada em ms (padrão: 200)
        signal    — nome do sinal no ProjectConfig (padrão: "led")
    """
    from core.instruments.gpio import GpioInstrument

    proj = get_active_project()
    if proj is None or not proj.has_pin(signal):
        raise RuntimeError(f"Sinal '{signal}' não definido no projeto.")

    pin_def = proj.pin(signal)
    gpio    = GpioInstrument(pin_def.port, pal)
    pin     = gpio.pin(pin_def.pin)
    half    = period_ms / 2000.0

    for _ in range(n):
        pin.set()
        time.sleep(half)
        pin.clear()
        time.sleep(half)


@macro(category="GPIO")
def led_set(pal, *, state: bool = True, signal: str = "led") -> None:
    """Liga ou desliga o LED.

    Parâmetros:
        state  — True para ligar, False para desligar
        signal — nome do sinal no ProjectConfig (padrão: "led")
    """
    from core.instruments.gpio import GpioInstrument

    proj = get_active_project()
    if proj is None or not proj.has_pin(signal):
        raise RuntimeError(f"Sinal '{signal}' não definido no projeto.")

    pin_def = proj.pin(signal)
    gpio    = GpioInstrument(pin_def.port, pal)
    pin     = gpio.pin(pin_def.pin)
    pin.set() if state else pin.clear()


# ── Botão / entrada digital ───────────────────────────────────────────────────

@macro(category="GPIO")
def button_wait(pal, *, timeout_ms: int = 5000, signal: str = "button") -> bool:
    """Aguarda o acionamento de um botão ou entrada digital.

    Retorna True se o botão foi pressionado dentro do timeout, False caso contrário.

    Parâmetros:
        timeout_ms — tempo máximo de espera em ms (padrão: 5000)
        signal     — nome do sinal no ProjectConfig (padrão: "button")
    """
    from core.instruments.gpio import GpioInstrument

    proj = get_active_project()
    if proj is None or not proj.has_pin(signal):
        raise RuntimeError(f"Sinal '{signal}' não definido no projeto.")

    pin_def  = proj.pin(signal)
    gpio     = GpioInstrument(pin_def.port, pal)
    pin      = gpio.pin(pin_def.pin)
    deadline = time.perf_counter() + timeout_ms / 1000.0
    pressed_level = 0 if pin_def.active_low else 1   # nível lógico quando pressionado

    while time.perf_counter() < deadline:
        if pin.read() == pressed_level:
            return True
        time.sleep(0.010)

    return False


@macro(category="GPIO")
def read_gpio(pal, *, signal: str) -> int:
    """Lê o estado atual de um pino GPIO.

    Retorna 0 ou 1 (nível lógico elétrico, sem inversão por active_low).

    Parâmetros:
        signal — nome do sinal no ProjectConfig (obrigatório)
    """
    from core.instruments.gpio import GpioInstrument

    proj = get_active_project()
    if proj is None or not proj.has_pin(signal):
        raise RuntimeError(f"Sinal '{signal}' não definido no projeto.")

    pin_def = proj.pin(signal)
    gpio    = GpioInstrument(pin_def.port, pal)
    return gpio.pin(pin_def.pin).read()


# ── Sequências compostas ──────────────────────────────────────────────────────

@macro(category="GPIO", description="Ciclo completo: reset → aguarda 200 ms → LED pisca 3x")
def power_on_sequence(pal, *, reset_ms: int = 100) -> None:
    """Sequência de inicialização padrão.

    Executa reset da placa, aguarda estabilização e sinaliza com LED.
    """
    reset_board(pal, hold_ms=reset_ms)
    time.sleep(0.2)
    led_blink(pal, n=3, period_ms=150)
