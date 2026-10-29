"""Exemplo: teste UART com análise de BER, latência e timing.

Demonstra o uso do módulo core.analysis em um teste real de bring-up.
Este arquivo é executado como plugin ou via pytest diretamente.

Uso:
    pytest TESTES_PLATAFORMA/exemplos/test_uart_analysis_example.py -v
"""

from __future__ import annotations

from core.analysis import (
    MeasurementSet,
    active_limits,
    analyze_ber,
    analyze_delay,
    analyze_timing,
)
from core.project.config import get_active_project
from tests_builtin.base import BuiltinTest, TestResult

# Padrão de loopback: varredura de todos os bytes
_TEST_PATTERN = bytes(range(256)) * 4   # 1024 bytes


class UartBerTest(BuiltinTest):
    """Bit Error Rate — loopback UART a 115200 bps.

    Envia _TEST_PATTERN via USART2 e compara com o recebido.
    Limites: BER ≤ 10^-6 (padrão UART industrial).
    """

    name        = "uart_ber"
    description = "BER USART2 loopback — 1024 bytes, limite 1e-6"

    def _run(self, pal) -> TestResult:
        proj = get_active_project()
        if proj is None or not proj.has_pin("uart2_tx"):
            return self._skip("Projeto sem pino uart2_tx configurado")

        # ── Obter periférico via ProjectConfig ─────────────────────────
        tx_def  = proj.pin("uart2_tx")
        baudrate = tx_def.peripheral.params.get("baudrate", 115200)

        # Em hardware real, usar UsartInstrument:
        #   from core.instruments.usart import UsartInstrument
        #   uart = UsartInstrument(tx_def.peripheral.name, pal)
        #   uart.configure(baudrate=baudrate)
        #   uart.enable()
        #   uart.write(_TEST_PATTERN)
        #   received = uart.read(len(_TEST_PATTERN), timeout_ms=500)
        #
        # Aqui simulamos para o exemplo:
        received = _TEST_PATTERN  # loopback perfeito (simulação)

        # active_limits() lê do perfil vinculado ao projeto (ou vazio se não houver)
        ms = MeasurementSet()
        ms.add(analyze_ber("uart_ber", _TEST_PATTERN, received,
                           **active_limits("uart_ber")))

        if ms.all_within_limits():
            return self._pass(
                f"BER = {ms.get('uart_ber').value:.2e} @ {baudrate} bps",
                measurements=ms,
            )
        return self._fail(
            f"BER fora do limite: {ms.get('uart_ber').value:.2e} > 1e-6",
            measurements=ms,
        )


class UartLatencyTest(BuiltinTest):
    """Latência de round-trip UART (RTT) — mede atraso médio de eco.

    Envia 16 quadros de 64 bytes e mede o tempo de resposta de cada um.
    Limite: RTT médio ≤ 5 ms a 115200 bps.
    """

    name        = "uart_rtt"
    description = "Latência round-trip USART2 — 16 quadros 64 B, limite 5 ms"

    def _run(self, pal) -> TestResult:
        import time

        proj = get_active_project()
        if proj is None or not proj.has_pin("uart2_tx"):
            return self._skip("Projeto sem pino uart2_tx configurado")

        frame = bytes([0xAA, 0x55] * 32)  # 64 bytes por quadro

        # Em hardware real:
        #   send_times, recv_times = [], []
        #   for _ in range(16):
        #       t0 = time.perf_counter()
        #       uart.write(frame)
        #       uart.read(len(frame), timeout_ms=100)
        #       t1 = time.perf_counter()
        #       send_times.append(t0); recv_times.append(t1)
        #
        # Simulação:
        send_times = [i * 0.002 for i in range(16)]
        recv_times = [t + 0.0008 for t in send_times]   # ~0.8 ms RTT

        ms = MeasurementSet()
        # Pega o limite do perfil ativo; fallback para 5 ms se não configurado
        rtt_lim = active_limits("uart_rtt").get("limit_max") or 5.0
        ms.add(analyze_delay("uart_rtt", send_times, recv_times, limit_max_ms=rtt_lim))

        rtt = ms.get("uart_rtt")
        if ms.all_within_limits():
            return self._pass(f"RTT médio = {rtt.value:.2f} ms", measurements=ms)
        return self._fail(f"RTT fora do limite: {rtt.value:.2f} ms > 5 ms", measurements=ms)


class UartTimingTest(BuiltinTest):
    """Verificação do período de bit UART.

    Mede o período real de bit e compara com o esperado para o baudrate.
    Tolerância: ±2%.
    """

    name        = "uart_bit_timing"
    description = "Período de bit USART2 — desvio máximo ±2%"

    def _run(self, pal) -> TestResult:
        proj = get_active_project()
        if proj is None or not proj.has_pin("uart2_tx"):
            return self._skip("Projeto sem pino uart2_tx configurado")

        tx_def   = proj.pin("uart2_tx")
        baudrate = tx_def.peripheral.params.get("baudrate", 115200)
        expected_period_s = 1.0 / baudrate

        # Em hardware real, capturar bordas do pino TX com lógica analisadora
        # ou osciloscópio via VISA e calcular períodos de bit.
        # Simulação: períodos perfeitos
        ts = [i * expected_period_s for i in range(51)]

        ms = MeasurementSet()
        timing_kw = active_limits("bit_period")   # {"tolerance_pct": X} do perfil
        if "tolerance_pct" not in timing_kw:
            timing_kw["tolerance_pct"] = 2.0       # padrão se sem perfil ativo
        ms.add(analyze_timing("bit_period", ts, expected_period_s, **timing_kw))

        m = ms.get("bit_period")
        dev_pct = abs(m.value - expected_period_s) / expected_period_s * 100
        if ms.all_within_limits():
            return self._pass(
                f"Período = {m.value*1e6:.3f} µs, desvio = {dev_pct:.3f}%",
                measurements=ms,
            )
        return self._fail(
            f"Período fora de ±2%: desvio = {dev_pct:.3f}%",
            measured=m.value,
            expected=expected_period_s,
            measurements=ms,
        )


# Suite exportada para uso como plugin
PLUGIN_SUITE = (UartBerTest(), UartLatencyTest(), UartTimingTest())
