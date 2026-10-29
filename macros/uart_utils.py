"""Macros utilitárias para operações UART / USART.

Uso::

    from core.macros import get_macro

    ms = get_macro("uart_loopback_ber")(pal, n_bytes=4096)
    ms = get_macro("uart_send_pattern")(pal, pattern=b"\\xAA\\x55")
    ok = get_macro("uart_echo_check")(pal, message=b"HELLO")
"""

from __future__ import annotations

from core.macros import macro
from core.project.config import get_active_project


# ── BER loopback ──────────────────────────────────────────────────────────────

@macro(category="UART")
def uart_loopback_ber(
    pal,
    *,
    n_bytes:      int   = 1024,
    uart_signal:  str   = "uart2_tx",
) -> "MeasurementSet":
    """BER loopback UART — envia padrão e calcula taxa de erro de bit.

    Requer pino uart_signal configurado no ProjectConfig com peripheral.name
    apontando para o USART (ex: "USART2") e baudrate em peripheral.params.

    Retorna um MeasurementSet com a métrica "uart_ber".

    Parâmetros:
        n_bytes      — total de bytes a transmitir (padrão: 1024)
        uart_signal  — nome do sinal TX no ProjectConfig (padrão: "uart2_tx")

    Uso::

        ms = get_macro("uart_loopback_ber")(pal, n_bytes=4096)
        if not ms.all_within_limits():
            return self._fail("BER fora do limite", measurements=ms)
    """
    from core.analysis import MeasurementSet, active_limits, analyze_ber
    from core.instruments.usart import UsartInstrument

    proj = get_active_project()
    if proj is None or not proj.has_pin(uart_signal):
        raise RuntimeError(f"Sinal '{uart_signal}' não definido no projeto.")

    pin_def  = proj.pin(uart_signal)
    baudrate = pin_def.peripheral.params.get("baudrate", 115200)
    uart     = UsartInstrument(pin_def.peripheral.name, pal)
    uart.configure(baudrate=baudrate)
    uart.enable()

    # Padrão de varredura completa + repetição
    base    = bytes(range(256))
    repeats = max(1, n_bytes // 256)
    pattern = base * repeats

    uart.write(pattern)
    received = uart.read(len(pattern), timeout_ms=int(len(pattern) * 10 / baudrate * 1000) + 500)

    uart.disable()

    ms = MeasurementSet()
    ms.add(analyze_ber("uart_ber", pattern, received, **active_limits("uart_ber")))
    return ms


# ── Echo check ────────────────────────────────────────────────────────────────

@macro(category="UART")
def uart_echo_check(
    pal,
    *,
    message:     bytes = b"PING",
    uart_signal: str   = "uart2_tx",
    timeout_ms:  int   = 500,
) -> bool:
    """Envia uma mensagem e verifica se o eco é idêntico.

    Retorna True se recebeu exatamente o mesmo conteúdo enviado.

    Parâmetros:
        message     — bytes a enviar (padrão: b"PING")
        uart_signal — sinal TX no ProjectConfig (padrão: "uart2_tx")
        timeout_ms  — timeout de recepção em ms (padrão: 500)
    """
    from core.instruments.usart import UsartInstrument

    proj = get_active_project()
    if proj is None or not proj.has_pin(uart_signal):
        raise RuntimeError(f"Sinal '{uart_signal}' não definido no projeto.")

    pin_def  = proj.pin(uart_signal)
    baudrate = pin_def.peripheral.params.get("baudrate", 115200)
    uart     = UsartInstrument(pin_def.peripheral.name, pal)
    uart.configure(baudrate=baudrate)
    uart.enable()

    uart.write(message)
    received = uart.read(len(message), timeout_ms=timeout_ms)

    uart.disable()
    return received == message


# ── Envio de padrão ───────────────────────────────────────────────────────────

@macro(category="UART")
def uart_send_pattern(
    pal,
    *,
    pattern:     bytes = b"\xAA\x55",
    repeat:      int   = 100,
    uart_signal: str   = "uart2_tx",
) -> bytes:
    """Envia um padrão repetido e retorna os bytes recebidos.

    Útil para captura com analisador lógico ou osciloscópio durante o envio.

    Parâmetros:
        pattern     — padrão de bytes a repetir
        repeat      — número de repetições (padrão: 100)
        uart_signal — sinal TX no ProjectConfig (padrão: "uart2_tx")
    """
    from core.instruments.usart import UsartInstrument

    proj = get_active_project()
    if proj is None or not proj.has_pin(uart_signal):
        raise RuntimeError(f"Sinal '{uart_signal}' não definido no projeto.")

    pin_def  = proj.pin(uart_signal)
    baudrate = pin_def.peripheral.params.get("baudrate", 115200)
    uart     = UsartInstrument(pin_def.peripheral.name, pal)
    uart.configure(baudrate=baudrate)
    uart.enable()

    data = pattern * repeat
    uart.write(data)
    received = uart.read(len(data), timeout_ms=2000)

    uart.disable()
    return received


# ── Latência round-trip ───────────────────────────────────────────────────────

@macro(category="UART")
def uart_rtt_measure(
    pal,
    *,
    n_frames:    int = 16,
    frame_size:  int = 64,
    uart_signal: str = "uart2_tx",
) -> "MeasurementSet":
    """Mede a latência de round-trip (RTT) da UART.

    Envia N quadros e registra o tempo de envio/recepção de cada um.
    Retorna MeasurementSet com "uart_rtt" em ms.

    Parâmetros:
        n_frames    — número de quadros a enviar (padrão: 16)
        frame_size  — tamanho de cada quadro em bytes (padrão: 64)
        uart_signal — sinal TX no ProjectConfig (padrão: "uart2_tx")
    """
    import time

    from core.analysis import MeasurementSet, active_limits, analyze_delay
    from core.instruments.usart import UsartInstrument

    proj = get_active_project()
    if proj is None or not proj.has_pin(uart_signal):
        raise RuntimeError(f"Sinal '{uart_signal}' não definido no projeto.")

    pin_def  = proj.pin(uart_signal)
    baudrate = pin_def.peripheral.params.get("baudrate", 115200)
    uart     = UsartInstrument(pin_def.peripheral.name, pal)
    uart.configure(baudrate=baudrate)
    uart.enable()

    frame       = bytes([0xAA, 0x55] * (frame_size // 2))
    send_times:  list[float] = []
    recv_times:  list[float] = []

    for _ in range(n_frames):
        t0 = time.perf_counter()
        uart.write(frame)
        uart.read(len(frame), timeout_ms=200)
        t1 = time.perf_counter()
        send_times.append(t0)
        recv_times.append(t1)

    uart.disable()

    # Pega o limite do perfil ativo (key "uart_rtt", valor em ms)
    rtt_limit = active_limits("uart_rtt").get("limit_max")

    ms = MeasurementSet()
    ms.add(analyze_delay("uart_rtt", send_times, recv_times,
                         limit_max_ms=rtt_limit))
    return ms
