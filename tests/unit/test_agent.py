"""Testes unitários de core.agent — alvo simulado, sem hardware.

O FakeTarget implementa IAgentTarget sobre um dicionário de palavras e, no
resume(), executa em Python o mesmo protocolo de stubs/stm32h7/usart_sweep.c.

Execução:
    pytest tests/unit/test_agent.py -v
"""

from __future__ import annotations

import queue

import pytest

from core.agent.agent import (
    REG_PC,
    REG_SP,
    REG_XPSR,
    RingReader,
    TargetAgent,
    bytes_to_words,
    words_to_bytes,
)
from core.agent.usart_sweep import (
    CODE_ADDR,
    CR1_OVER8,
    M_HEAD,
    M_MAGIC,
    M_NBYTES,
    M_NSTEPS,
    M_RBSIZE,
    M_STATUS,
    M_TAIL,
    MAGIC,
    MBOX_ADDR,
    RB_OFF,
    RCC,
    RCC_CFGR,
    REC_WORDS,
    RX_BUF,
    ST_DONE,
    STACK_TOP,
    STEPS_OFF,
    StepResult,
    brr_for,
    max_reliable_baud,
    pattern,
    run_sweep,
)

STUB = bytes(range(16))


class FakeTarget:
    """Memória de palavras + núcleo simulado que roda o protocolo do stub."""

    def __init__(self, corrupt_steps: frozenset[int] = frozenset(), run_stub: bool = True) -> None:
        self.mem: dict[int, int] = {}
        self.regs: dict[int, int] = {}
        self.halted = True
        self.corrupt_steps = corrupt_steps
        self.run_stub = run_stub

    # IAgentTarget
    def read_mem32(self, addr: int) -> int:
        return self.mem.get(addr, 0)

    def write_mem32(self, addr: int, value: int) -> None:
        self.mem[addr] = value & 0xFFFFFFFF

    def read_block32(self, addr: int, count: int) -> list[int]:
        return [self.read_mem32(addr + 4 * i) for i in range(count)]

    def write_block32(self, addr: int, words: list[int]) -> None:
        for i, w in enumerate(words):
            self.write_mem32(addr + 4 * i, w)

    def halt(self) -> None:
        self.halted = True

    def is_halted(self) -> bool:
        return self.halted

    def write_core_register(self, reg: int, value: int) -> None:
        self.regs[reg] = value

    def resume(self) -> None:
        self.halted = False
        if self.run_stub:
            self._stub()

    # Execução simulada (mesma lógica do .c, sem tempo real)
    def _mb(self, i: int) -> int:
        return self.read_mem32(MBOX_ADDR + 4 * i)

    def _stub(self) -> None:
        n, nsteps, rbsize = self._mb(M_NBYTES), self._mb(M_NSTEPS), self._mb(M_RBSIZE)
        self.write_mem32(MBOX_ADDR + 4 * M_MAGIC, MAGIC)
        for s in range(nsteps):
            data = bytearray(pattern(i) for i in range(n))
            err = 0
            if s in self.corrupt_steps:
                data[3] ^= 0x01
                err = 1
            self.write_block32(RX_BUF + s * n, bytes_to_words(bytes(data)))
            head = self._mb(M_HEAD)
            assert head - self._mb(M_TAIL) < rbsize
            rec = [s, self._mb(STEPS_OFF + 3 * s), n, n, err, 0, 0, n * 100]
            self.write_block32(MBOX_ADDR + 4 * (RB_OFF + (head % rbsize) * REC_WORDS), rec)
            self.write_mem32(MBOX_ADDR + 4 * M_HEAD, head + 1)
        self.write_mem32(MBOX_ADDR + 4 * M_STATUS, ST_DONE)
        self.halted = True


# ── agent.py ──────────────────────────────────────────────────────────────────

class TestWords:
    def test_roundtrip_pads_to_word(self) -> None:
        words = bytes_to_words(b"\x01\x02\x03\x04\x05")
        assert words == [0x04030201, 0x05]
        assert words_to_bytes(words)[:5] == b"\x01\x02\x03\x04\x05"


class TestTargetAgent:
    def test_load_writes_and_verifies(self) -> None:
        t = FakeTarget()
        TargetAgent(t).load(STUB, CODE_ADDR)
        assert words_to_bytes(t.read_block32(CODE_ADDR, 4)) == STUB

    def test_load_detects_bad_ram(self) -> None:
        t = FakeTarget()
        t.write_block32 = lambda addr, words: None   # RAM não grava
        with pytest.raises(RuntimeError, match="Verificação"):
            TargetAgent(t).load(STUB, CODE_ADDR)

    def test_start_sets_thumb_entry_and_resumes(self) -> None:
        t = FakeTarget(run_stub=False)
        TargetAgent(t).start(CODE_ADDR | 1, STACK_TOP)
        assert t.regs == {REG_SP: STACK_TOP, REG_PC: CODE_ADDR, REG_XPSR: 1 << 24}
        assert not t.halted


class TestRingReader:
    def _ring(self, t: FakeTarget, size: int = 4) -> RingReader:
        return RingReader(t, 0x100, 0x104, 0x200, size, 2)

    def test_drain_reads_pending_and_advances_tail(self) -> None:
        t = FakeTarget()
        t.write_block32(0x200, [1, 10, 2, 20, 3, 30])
        t.write_mem32(0x100, 3)
        assert self._ring(t).drain() == [[1, 10], [2, 20], [3, 30]]
        assert t.read_mem32(0x104) == 3
        assert self._ring(t).drain() == []

    def test_drain_wraps_around(self) -> None:
        t = FakeTarget()
        t.write_block32(0x200, [4, 40, 1, 1, 1, 1, 3, 30])   # slots 0..3
        t.write_mem32(0x100, 5)
        t.write_mem32(0x104, 3)
        assert self._ring(t).drain() == [[3, 30], [4, 40]]

    def test_corrupt_indices_raise(self) -> None:
        t = FakeTarget()
        t.write_mem32(0x100, 10)
        with pytest.raises(RuntimeError, match="corrompida"):
            self._ring(t).drain()


# ── usart_sweep.py ────────────────────────────────────────────────────────────

class TestBrr:
    def test_over16_when_possible(self) -> None:
        brr, cr1x, real = brr_for(1_000_000)
        assert (brr, cr1x, real) == (64, 0, 1_000_000)

    def test_over8_above_fck_over_16(self) -> None:
        brr, cr1x, real = brr_for(8_000_000)          # USARTDIV = 16
        assert cr1x == CR1_OVER8
        assert brr == 0x10 and real == 8_000_000
        brr, _, real = brr_for(6_400_000)             # USARTDIV = 20 = 0x14
        assert brr == 0x12 and real == 6_400_000

    def test_above_max_raises(self) -> None:
        with pytest.raises(ValueError, match="acima do máximo"):
            brr_for(10_000_000)


def _ready_target(**kw) -> FakeTarget:
    t = FakeTarget(**kw)
    t.write_mem32(RCC + RCC_CFGR, 0)        # SYSCLK = HSI
    return t


class TestRunSweep:
    def test_results_queue_and_ber(self) -> None:
        t = _ready_target()
        q: queue.Queue = queue.Queue()
        res = run_sweep(t, bauds=(115_200, 1_000_000), n_bytes=64, out=q, stub=STUB)
        assert [r.baud_nominal for r in res] == [115_200, 1_000_000]
        assert all(r.ok and r.ber is not None and r.ber.value == 0 for r in res)
        assert [q.get_nowait() for _ in range(3)] == [*res, None]
        assert t.regs[REG_PC] == CODE_ADDR

    def test_corrupted_step_has_bit_errors(self) -> None:
        t = _ready_target(corrupt_steps=frozenset({1}))
        res = run_sweep(t, bauds=(1_000_000, 2_000_000, 4_000_000), n_bytes=64, stub=STUB)
        assert [r.ok for r in res] == [True, False, True]
        assert res[1].ber.value == pytest.approx(1 / (64 * 8))
        assert max_reliable_baud(res).baud_nominal == 1_000_000

    def test_refuses_when_not_on_hsi(self) -> None:
        t = FakeTarget()
        t.write_mem32(RCC + RCC_CFGR, 0x1B)   # SYSCLK = PLL (firmware rodando)
        with pytest.raises(RuntimeError, match="HSI"):
            run_sweep(t, n_bytes=64, stub=STUB)

    def test_stub_that_never_starts(self) -> None:
        t = _ready_target(run_stub=False)
        t.resume = lambda: setattr(t, "halted", True)   # para sem rodar
        with pytest.raises(RuntimeError, match="MAGIC"):
            run_sweep(t, bauds=(1_000_000,), n_bytes=64, stub=STUB)

    def test_timeout_halts_core(self) -> None:
        t = _ready_target(run_stub=False)
        q: queue.Queue = queue.Queue()
        with pytest.raises(TimeoutError):
            run_sweep(t, bauds=(1_000_000,), n_bytes=64, out=q, timeout_s=0.05, stub=STUB)
        assert t.halted
        assert q.get_nowait() is None

    @pytest.mark.parametrize("n", [0, 6, 8192])
    def test_invalid_size(self, n: int) -> None:
        with pytest.raises(ValueError):
            run_sweep(_ready_target(), n_bytes=n, stub=STUB)

    def test_packaged_stub_exists(self) -> None:
        from core.agent.usart_sweep import load_stub
        assert len(load_stub()) > 0


class TestStepResult:
    def test_throughput(self) -> None:
        r = StepResult(1_000_000, 1e6, 100, 100, 0, 0, 0, 0, cycles=64_000)  # 1 ms
        assert r.throughput_bps == pytest.approx(1_000_000)
        assert r.ok
