"""Varredura de baud rate do USART executada por stub de RAM (STM32H7).

O host configura o chip via SWD (clock do USART = HSI 64 MHz, pino TX em
half-duplex, sem fio externo), carrega stubs/stm32h7/usart_sweep.c e coleta um
StepResult por baud rate numa queue.Queue enquanto o stub roda.

Layout da caixa de correio: idêntico ao de stubs/stm32h7/usart_sweep.c.
"""

from __future__ import annotations

import queue
import time
from dataclasses import dataclass, field
from importlib import resources

from core.agent.agent import IAgentTarget, RingReader, TargetAgent, words_to_bytes
from core.analysis import analyze_ber
from core.analysis.metrics import Measurement

# ── Memória (AXI SRAM / DTCM) ────────────────────────────────────────────────
CODE_ADDR:  int = 0x2400_0000
MBOX_ADDR:  int = 0x2400_4000
RX_BUF:     int = 0x2401_0000
STACK_TOP:  int = 0x2002_0000          # topo da DTCM (128 KiB)

# Caixa de correio (índices de palavra)
M_MAGIC, M_STATUS, M_NSTEPS, M_NBYTES, M_USART, M_HEAD, M_TAIL, M_RBSIZE = range(8)
STEPS_OFF:  int = 16
RB_OFF:     int = 128
REC_WORDS:  int = 8
RB_SIZE:    int = 32
MBOX_WORDS: int = RB_OFF + RB_SIZE * REC_WORDS
MAX_STEPS:  int = (RB_OFF - STEPS_OFF) // 3
MAX_BYTES:  int = 4096

MAGIC:      int = 0x5354_5542          # "STUB"
ST_DONE:    int = 2

STUB_BIN:   str = "stm32h7_usart_sweep.bin"

# ── Registradores STM32H7 (RM0433) ───────────────────────────────────────────
RCC = 0x5802_4400
RCC_CR, RCC_CFGR, RCC_D2CCIP2R, RCC_AHB4ENR, RCC_APB1LENR = 0x00, 0x10, 0x54, 0xE0, 0xE8
GPIOD = 0x5802_0C00
USART3 = 0x4000_4800
USART_CR1, USART_CR2, USART_CR3, USART_PRESC = 0x00, 0x04, 0x08, 0x2C
CR1_OVER8 = 1 << 15
CR3_HDSEL = 1 << 3
HSI_HZ = 64_000_000

DEFAULT_BAUDS: tuple[int, ...] = (
    115_200, 460_800, 921_600, 1_000_000, 2_000_000, 3_000_000,
    4_000_000, 5_333_333, 6_400_000, 8_000_000,
)


def pattern(i: int) -> int:
    """Mesmo padrão do stub: byte alto de i * 2654435761 (32 bits)."""
    return ((i * 2654435761) & 0xFFFFFFFF) >> 24


def brr_for(baud: int, f_ck: int = HSI_HZ) -> tuple[int, int, float]:
    """Calcula (BRR, bits extras de CR1, baud real). OVER16 quando possível, senão OVER8.

    RM0433: USARTDIV >= 16 nos dois modos; em OVER8, BRR[3:0] = USARTDIV[3:0] >> 1.
    """
    div16 = round(f_ck / baud)
    if div16 >= 16:
        return div16, 0, f_ck / div16
    div8 = round(2 * f_ck / baud)
    if div8 < 16:
        raise ValueError(f"{baud} baud acima do máximo com f_ck={f_ck} Hz ({f_ck // 8})")
    brr = (div8 & 0xFFF0) | ((div8 & 0xF) >> 1)
    return brr, CR1_OVER8, 2 * f_ck / div8


@dataclass
class StepResult:
    """Resultado de um passo da varredura (um baud rate)."""
    baud_nominal: int
    baud_real: float
    sent: int
    received: int
    byte_errors: int
    overrun: int
    framing: int
    noise: int
    cycles: int
    f_core: int = HSI_HZ
    ber: Measurement | None = field(default=None, repr=False)

    @property
    def seconds(self) -> float:
        return self.cycles / self.f_core

    @property
    def throughput_bps(self) -> float:
        """Taxa efetiva de bits no fio (start + 8 dados + stop) medida pelo DWT."""
        return self.received * 10 / self.seconds if self.cycles else 0.0

    @property
    def ok(self) -> bool:
        return (self.received == self.sent and self.byte_errors == 0
                and self.overrun == 0 and self.framing == 0 and self.noise == 0)


def setup_h7_usart3(t: IAgentTarget) -> None:
    """Prepara USART3 em PD8 (half-duplex), kernel clock HSI. Núcleo parado após reset."""
    def rmw(addr: int, mask: int, value: int) -> None:
        t.write_mem32(addr, (t.read_mem32(addr) & ~mask) | value)

    cfgr = t.read_mem32(RCC + RCC_CFGR)
    if (cfgr >> 3) & 0x7 != 0:
        raise RuntimeError(
            f"SYSCLK não está no HSI (RCC_CFGR=0x{cfgr:08X}) — faça reset_and_halt antes"
        )
    if (t.read_mem32(RCC + RCC_CR) >> 3) & 0x3 != 0:
        raise RuntimeError("HSIDIV ≠ 1: HSI não está em 64 MHz")

    rmw(RCC + RCC_AHB4ENR, 1 << 3, 1 << 3)          # GPIODEN
    rmw(RCC + RCC_APB1LENR, 1 << 18, 1 << 18)       # USART3EN
    rmw(RCC + RCC_D2CCIP2R, 0x7, 0b011)             # USART234578SEL = hsi_ker_ck

    rmw(GPIOD + 0x00, 0x3 << 16, 0x2 << 16)         # MODER8   = AF
    rmw(GPIOD + 0x04, 1 << 8, 0)                    # OTYPER8  = push-pull
    rmw(GPIOD + 0x08, 0x3 << 16, 0x3 << 16)         # OSPEEDR8 = very high
    rmw(GPIOD + 0x0C, 0x3 << 16, 0x1 << 16)         # PUPDR8   = pull-up
    rmw(GPIOD + 0x24, 0xF, 7)                       # AFRH: PD8 = AF7 (USART3_TX)

    t.write_mem32(USART3 + USART_CR1, 0)
    t.write_mem32(USART3 + USART_CR2, 0)
    t.write_mem32(USART3 + USART_CR3, CR3_HDSEL)
    t.write_mem32(USART3 + USART_PRESC, 0)


def load_stub() -> bytes:
    return resources.files("core.agent").joinpath("bin", STUB_BIN).read_bytes()


def run_sweep(
    t: IAgentTarget,
    bauds: tuple[int, ...] = DEFAULT_BAUDS,
    n_bytes: int = 1024,
    out: queue.Queue | None = None,
    timeout_s: float = 30.0,
    stub: bytes | None = None,
) -> list[StepResult]:
    """Executa a varredura. Cada StepResult também vai para `out` assim que chega.

    Pré-condição: núcleo parado logo após reset (t.reset_and_halt()).
    Ao final, `out` recebe None como sentinela.
    """
    if not 4 <= n_bytes <= MAX_BYTES or n_bytes % 4:
        raise ValueError(f"n_bytes deve ser múltiplo de 4 entre 4 e {MAX_BYTES}")
    if not 1 <= len(bauds) <= MAX_STEPS:
        raise ValueError(f"de 1 a {MAX_STEPS} baud rates por varredura")

    steps = [brr_for(b) for b in bauds]
    setup_h7_usart3(t)

    agent = TargetAgent(t)
    agent.load(stub if stub is not None else load_stub(), CODE_ADDR)

    mbox = [0] * MBOX_WORDS
    mbox[M_NSTEPS], mbox[M_NBYTES], mbox[M_USART], mbox[M_RBSIZE] = (
        len(bauds), n_bytes, USART3, RB_SIZE)
    for i, ((brr, cr1x, _), baud) in enumerate(zip(steps, bauds, strict=True)):
        frame_cycles = 10 * HSI_HZ // baud
        mbox[STEPS_OFF + 3 * i: STEPS_OFF + 3 * i + 3] = [
            brr, cr1x, n_bytes * frame_cycles * 4 + HSI_HZ // 1000,   # 4x o ideal + 1 ms
        ]
    t.write_block32(MBOX_ADDR, mbox)

    ring = RingReader(t, MBOX_ADDR + 4 * M_HEAD, MBOX_ADDR + 4 * M_TAIL,
                      MBOX_ADDR + 4 * RB_OFF, RB_SIZE, REC_WORDS)
    sent_ref = bytes(pattern(i) for i in range(n_bytes))
    results: list[StepResult] = []

    def collect() -> None:
        for rec in ring.drain():
            step, _brr, sent, received, err, ore, fe_ne, cycles = rec
            baud = bauds[step]
            raw = words_to_bytes(t.read_block32(RX_BUF + step * n_bytes, n_bytes // 4))
            r = StepResult(
                baud_nominal=baud, baud_real=steps[step][2], sent=sent, received=received,
                byte_errors=err, overrun=ore, framing=fe_ne >> 16, noise=fe_ne & 0xFFFF,
                cycles=cycles,
            )
            r.ber = analyze_ber(f"uart_ber_{baud}", sent_ref, raw[:received], limit_max=0.0)
            results.append(r)
            if out is not None:
                out.put(r)

    agent.start(CODE_ADDR, STACK_TOP)
    try:
        deadline = time.monotonic() + timeout_s
        while not t.is_halted():
            collect()
            if time.monotonic() > deadline:
                t.halt()
                raise TimeoutError(f"stub não terminou em {timeout_s} s ({len(results)} passos)")
            time.sleep(0.02)
        collect()
        if t.read_mem32(MBOX_ADDR + 4 * M_MAGIC) != MAGIC:
            raise RuntimeError("stub não iniciou (MAGIC ausente) — verifique endereço e núcleo")
        if t.read_mem32(MBOX_ADDR + 4 * M_STATUS) != ST_DONE:
            raise RuntimeError("stub parou antes de terminar (falha ou breakpoint inesperado)")
    finally:
        if out is not None:
            out.put(None)
    return results


def max_reliable_baud(results: list[StepResult]) -> StepResult | None:
    """Maior baud rate cujo passo e todos os anteriores passaram sem erro."""
    best = None
    for r in sorted(results, key=lambda r: r.baud_nominal):
        if not r.ok:
            break
        best = r
    return best
