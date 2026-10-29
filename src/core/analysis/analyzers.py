"""Funções de análise para circuitos e protocolos.

Cada função recebe dados brutos e devolve um objeto Measurement já com
estatísticas e status de aprovação calculados.

Funções disponíveis:
    analyze_ber        — Bit Error Rate para comunicações digitais (UART, SPI, CAN…)
    analyze_timing     — Período, jitter e desvio de frequência
    analyze_voltage    — Precisão DC, ripple e desvio de tensão
    analyze_frequency  — Desvio de frequência e estabilidade
    analyze_delay      — Atraso de propagação entre eventos

Exemplo completo (UART loopback test)::

    from core.analysis import analyze_ber, MeasurementSet

    PATTERN = bytes(range(256)) * 16          # 4096 bytes de teste
    received = uart.write_read(PATTERN)

    ms = MeasurementSet()
    ms.add(analyze_ber("uart_ber", PATTERN, received, limit_max=1e-6))

    return self._pass(measurements=ms) if ms.all_within_limits() else \\
           self._fail(f"BER = {ms.get('uart_ber').value:.2e}", measurements=ms)
"""

from __future__ import annotations

import math
import statistics

from core.analysis.metrics import Measurement


# ── BER — Bit Error Rate ──────────────────────────────────────────────────────

def analyze_ber(
    name: str,
    sent:     bytes | bytearray,
    received: bytes | bytearray,
    *,
    limit_max: float | None = None,
) -> Measurement:
    """Taxa de erro de bit (BER) por comparação de bytes.

    Conta bits diferentes entre ``sent`` e ``received`` e calcula a fração
    de bits errados sobre o total transmitido.

    Parâmetros:
        name        — identificador (ex: "uart_ber")
        sent        — bytes enviados (referência)
        received    — bytes recebidos (pode ter comprimento diferente)
        limit_max   — BER máximo aceitável (ex: 1e-6 para 10^-6)

    Retorna um Measurement com:
        value       — BER global (erros / bits_totais)
        samples     — BER por byte (útil para identificar padrões de erro)
        unit        — "err/bit"
    """
    if not sent:
        return Measurement(name=name, value=0.0, unit="err/bit",
                           limit_max=limit_max, description="Nenhum dado enviado")

    # Alinha pelo menor comprimento
    length = min(len(sent), len(received))
    total_bits = len(sent) * 8

    # Bits errados nos bytes comuns
    per_byte_ber: list[float] = []
    error_bits = 0
    for i in range(length):
        diff = bin(sent[i] ^ received[i]).count("1")
        error_bits += diff
        per_byte_ber.append(diff / 8.0)

    # Bytes perdidos (não recebidos) contam como 8 bits errados por byte
    lost = len(sent) - length
    error_bits += lost * 8
    per_byte_ber.extend([1.0] * lost)

    ber = error_bits / total_bits

    desc = (
        f"{error_bits} bits errados em {total_bits} transmitidos "
        f"({length} bytes recebidos, {lost} perdidos)"
    )

    return Measurement(
        name=name,
        value=ber,
        unit="err/bit",
        samples=per_byte_ber,
        limit_max=limit_max,
        description=desc,
    )


# ── Timing — Período e Jitter ─────────────────────────────────────────────────

def analyze_timing(
    name: str,
    timestamps_s: list[float],
    expected_period_s: float,
    *,
    tolerance_pct: float = 5.0,
    limit_jitter_pct: float | None = None,
) -> Measurement:
    """Análise de período, jitter e desvio de frequência.

    A partir de uma lista de timestamps (em segundos), calcula os períodos
    entre eventos consecutivos e mede jitter e desvio em relação ao esperado.

    Parâmetros:
        name              — identificador (ex: "pwm_period", "uart_bit_timing")
        timestamps_s      — timestamps dos eventos (em segundos, mínimo 2)
        expected_period_s — período nominal esperado (1/freq)
        tolerance_pct     — margem de aprovação do período médio (padrão: ±5%)
        limit_jitter_pct  — limite de jitter p-p em % do período (None = sem limite)

    Retorna um Measurement com:
        value       — período médio medido (segundos)
        samples     — lista de períodos individuais
        unit        — "s"
        limit_min/max — faixa aceitável do período médio
    """
    if len(timestamps_s) < 2:
        return Measurement(
            name=name, value=float("nan"), unit="s",
            description="Amostras insuficientes (mínimo 2 timestamps)",
        )

    periods = [b - a for a, b in zip(timestamps_s, timestamps_s[1:])]
    mean_period = statistics.mean(periods)
    std = statistics.stdev(periods) if len(periods) >= 2 else 0.0
    jitter_pct = (std / expected_period_s * 100) if expected_period_s > 0 else 0.0

    error_pct = abs(mean_period - expected_period_s) / expected_period_s * 100

    desc = (
        f"Período médio: {mean_period*1e6:.3f} µs, "
        f"esperado: {expected_period_s*1e6:.3f} µs, "
        f"desvio: {error_pct:.2f}%, jitter σ: {std*1e9:.1f} ns ({jitter_pct:.2f}%)"
    )

    lim_min = expected_period_s * (1 - tolerance_pct / 100)
    lim_max = expected_period_s * (1 + tolerance_pct / 100)

    m = Measurement(
        name=name,
        value=mean_period,
        unit="s",
        samples=periods,
        limit_min=lim_min,
        limit_max=lim_max,
        description=desc,
    )

    # Jitter como medição auxiliar separada (se solicitado)
    # Acesso via ms.get(name + "_jitter_pct") seria outro Measurement
    return m


def analyze_jitter(
    name: str,
    timestamps_s: list[float],
    expected_period_s: float,
    *,
    limit_max_pct: float = 2.0,
) -> Measurement:
    """Jitter pico-a-pico em % do período nominal.

    Complementar a analyze_timing — mede a variação extrema dos períodos.
    """
    if len(timestamps_s) < 3:
        return Measurement(
            name=name, value=float("nan"), unit="%",
            description="Amostras insuficientes (mínimo 3 timestamps)",
        )

    periods = [b - a for a, b in zip(timestamps_s, timestamps_s[1:])]
    pk_pk = (max(periods) - min(periods)) / expected_period_s * 100

    return Measurement(
        name=name,
        value=pk_pk,
        unit="%",
        samples=[(p / expected_period_s * 100) for p in periods],
        limit_max=limit_max_pct,
        description=f"Jitter pico-a-pico: {pk_pk:.3f}% do período",
    )


# ── Tensão — Precisão DC e Ripple ────────────────────────────────────────────

def analyze_voltage(
    name: str,
    samples_v: list[float],
    nominal_v: float,
    *,
    tolerance_pct: float = 5.0,
) -> Measurement:
    """Precisão DC de uma tensão medida em múltiplas amostras.

    Parâmetros:
        name          — identificador (ex: "v_3v3", "v_batt")
        samples_v     — lista de leituras de tensão (Volts)
        nominal_v     — tensão nominal esperada
        tolerance_pct — margem de aprovação (padrão: ±5%)

    Retorna Measurement com:
        value         — média das amostras
        unit          — "V"
    """
    if not samples_v:
        return Measurement(name=name, value=float("nan"), unit="V",
                           description="Nenhuma amostra")

    mean_v = statistics.mean(samples_v)
    error_pct = abs(mean_v - nominal_v) / nominal_v * 100 if nominal_v else 0.0

    desc = (
        f"Média: {mean_v:.4f} V, nominal: {nominal_v:.4f} V, "
        f"desvio: {error_pct:.2f}%"
    )

    return Measurement(
        name=name,
        value=mean_v,
        unit="V",
        samples=samples_v,
        limit_min=nominal_v * (1 - tolerance_pct / 100),
        limit_max=nominal_v * (1 + tolerance_pct / 100),
        description=desc,
    )


def analyze_ripple(
    name: str,
    samples_v: list[float],
    *,
    limit_max_mv: float | None = None,
) -> Measurement:
    """Ripple pico-a-pico de uma tensão (mV).

    Útil para verificar ruído em linhas de alimentação.
    """
    if len(samples_v) < 2:
        return Measurement(name=name, value=float("nan"), unit="mV",
                           description="Amostras insuficientes")

    pk_pk_mv = (max(samples_v) - min(samples_v)) * 1000
    lim = limit_max_mv  # None = sem limite

    return Measurement(
        name=name,
        value=pk_pk_mv,
        unit="mV",
        samples=[(v - statistics.mean(samples_v)) * 1000 for v in samples_v],
        limit_max=lim,
        description=f"Ripple pico-a-pico: {pk_pk_mv:.2f} mV",
    )


# ── Frequência ────────────────────────────────────────────────────────────────

def analyze_frequency(
    name: str,
    timestamps_s: list[float],
    expected_hz: float,
    *,
    tolerance_pct: float = 1.0,
) -> Measurement:
    """Desvio de frequência em relação ao valor esperado.

    Calcula a frequência média a partir dos timestamps e compara com
    o valor nominal.

    Parâmetros:
        name          — identificador (ex: "pwm_freq", "spi_clk")
        timestamps_s  — timestamps de borda (mínimo 2)
        expected_hz   — frequência nominal
        tolerance_pct — margem de aprovação (padrão: ±1%)
    """
    if len(timestamps_s) < 2:
        return Measurement(name=name, value=float("nan"), unit="Hz",
                           description="Amostras insuficientes")

    periods = [b - a for a, b in zip(timestamps_s, timestamps_s[1:])]
    mean_period = statistics.mean(periods)
    measured_hz  = 1.0 / mean_period if mean_period > 0 else float("inf")

    error_pct = abs(measured_hz - expected_hz) / expected_hz * 100

    desc = (
        f"Frequência medida: {measured_hz:.3f} Hz, "
        f"esperado: {expected_hz:.3f} Hz, desvio: {error_pct:.3f}%"
    )

    return Measurement(
        name=name,
        value=measured_hz,
        unit="Hz",
        samples=[1.0 / p for p in periods if p > 0],
        limit_min=expected_hz * (1 - tolerance_pct / 100),
        limit_max=expected_hz * (1 + tolerance_pct / 100),
        description=desc,
    )


# ── Atraso de propagação ──────────────────────────────────────────────────────

def analyze_delay(
    name: str,
    send_times_s:    list[float],
    receive_times_s: list[float],
    *,
    limit_max_ms: float | None = None,
) -> Measurement:
    """Atraso de propagação entre envio e recepção.

    Pares (send, receive) são alinhados por índice. Calcula atrasos
    individuais e estatísticas.

    Parâmetros:
        name             — identificador (ex: "uart_latency", "can_rtt")
        send_times_s     — instante de envio de cada quadro (segundos)
        receive_times_s  — instante de recepção correspondente (segundos)
        limit_max_ms     — atraso máximo aceitável em milissegundos
    """
    if not send_times_s or not receive_times_s:
        return Measurement(name=name, value=float("nan"), unit="ms",
                           description="Nenhum par de timestamps")

    length = min(len(send_times_s), len(receive_times_s))
    delays_ms = [
        (receive_times_s[i] - send_times_s[i]) * 1000
        for i in range(length)
    ]

    mean_ms = statistics.mean(delays_ms)
    desc = (
        f"Atraso médio: {mean_ms:.3f} ms, "
        f"mínimo: {min(delays_ms):.3f} ms, máximo: {max(delays_ms):.3f} ms "
        f"({length} pares)"
    )

    return Measurement(
        name=name,
        value=mean_ms,
        unit="ms",
        samples=delays_ms,
        limit_max=limit_max_ms,
        description=desc,
    )


# ── Distorção harmônica total (requer numpy) ──────────────────────────────────

def analyze_thd(
    name: str,
    samples: list[float],
    fundamental_hz: float,
    sample_rate_hz: float,
    *,
    harmonics: int = 5,
    limit_max_pct: float | None = None,
) -> Measurement:
    """Distorção Harmônica Total (THD) — requer numpy.

    Realiza FFT das amostras e calcula a THD como razão entre a energia
    das harmônicas e a fundamental.

    Parâmetros:
        samples        — lista de amostras (voltagem, corrente, etc.)
        fundamental_hz — frequência fundamental esperada
        sample_rate_hz — taxa de amostragem
        harmonics      — número de harmônicas a considerar (padrão: 5)
        limit_max_pct  — THD máximo aceitável em % (None = sem limite)
    """
    try:
        import numpy as np
    except ImportError:
        return Measurement(
            name=name, value=float("nan"), unit="%",
            description="numpy não disponível — instale com: pip install numpy",
        )

    if len(samples) < 16:
        return Measurement(name=name, value=float("nan"), unit="%",
                           description="Amostras insuficientes (mínimo 16)")

    arr = np.array(samples, dtype=float)
    n = len(arr)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate_hz)
    spectrum = np.abs(np.fft.rfft(arr)) / n

    # Encontra índice da fundamental
    fund_idx = int(round(fundamental_hz / (sample_rate_hz / n)))
    fund_power = spectrum[fund_idx] ** 2

    # Potência das harmônicas
    harm_power = 0.0
    for h in range(2, harmonics + 2):
        idx = fund_idx * h
        if idx < len(spectrum):
            harm_power += spectrum[idx] ** 2

    thd_pct = math.sqrt(harm_power / fund_power) * 100 if fund_power > 0 else float("inf")

    return Measurement(
        name=name,
        value=thd_pct,
        unit="%",
        samples=list(spectrum[:fund_idx * (harmonics + 2)]),
        limit_max=limit_max_pct,
        description=f"THD: {thd_pct:.3f}% ({harmonics} harmônicas, f0={fundamental_hz:.1f} Hz)",
    )
