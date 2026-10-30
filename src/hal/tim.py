"""Timer em PWM: lê a configuração do firmware ou gera PWM pelo testador.

Um canal PWM é (timer, canal), ex. TIM2 CH3. Frequência e pulso saem de
PSC/ARR/CCRx e do clock do timer (árvore de clock do RCC):

    f_pwm = f_tim / ((PSC + 1) · (ARR + 1))      pulso = CCRx / f_cnt

Uso::

    ch = PwmChannel(pal, "TIM2", 3, f_tim=200e6)
    ch.read()                       # PwmState(freq_hz=50.0, pulse_s=0.0015, ...)
    with ch: ch.generate(50, 1.5e-3)   # assume o timer; restaura no fim
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from hal.common import enable_clock, has_register, restore_regs, save_regs

log = logging.getLogger("hal.tim")

CR1_CEN, CR1_URS, CR1_ARPE = 1 << 0, 1 << 2, 1 << 7
EGR_UG = 1 << 0
BDTR_MOE = 1 << 15
OCM_PWM1 = 0b110


@dataclass
class PwmState:
    enabled:  bool       # contador rodando (CEN) e saída do canal ligada (CCxE)
    pwm_mode: bool       # OCxM = PWM 1 ou PWM 2
    psc:      int
    arr:      int
    ccr:      int
    freq_hz:  float
    pulse_s:  float

    @property
    def duty(self) -> float:
        return self.ccr / (self.arr + 1) if self.arr + 1 else 0.0


def channel_number(role: str) -> int:
    """'CH3' → 3 (CH3N → 3)."""
    m = re.fullmatch(r"CH(\d)N?", role.upper())
    if not m:
        raise ValueError(f"função '{role}' não é um canal de timer (CHn)")
    return int(m.group(1))


class PwmChannel:
    def __init__(self, pal, timer: str, channel: int, f_tim: float) -> None:
        self.pal, self.tim, self.ch, self.f_tim = pal, timer.upper(), channel, f_tim
        self.ccmr = f"CCMR{1 if channel <= 2 else 2}_Output"
        self._saved: dict[str, int] = {}

    # ── Leitura ───────────────────────────────────────────────────────────

    def read(self) -> PwmState:
        p, t = self.pal, self.tim
        psc, arr = p.read_reg(t, "PSC") & 0xFFFF, p.read_reg(t, "ARR")
        ccr = p.read_reg(t, f"CCR{self.ch}")
        ccmr = p.read_reg(t, self.ccmr)
        lo, hi = (4, 16) if self.ch % 2 else (12, 24)          # OCxM[2:0] e OCxM[3]
        ocm = ccmr >> lo & 0b111 | (ccmr >> hi & 1) << 3
        cen = p.read_reg(t, "CR1") & CR1_CEN
        cce = p.read_reg(t, "CCER") >> (4 * (self.ch - 1)) & 1
        f_cnt = self.f_tim / (psc + 1)
        return PwmState(bool(cen and cce), ocm in (0b110, 0b111), psc, arr, ccr,
                        f_cnt / (arr + 1), ccr / f_cnt)

    # ── Geração pelo testador ─────────────────────────────────────────────

    def __enter__(self) -> PwmChannel:
        return self

    def __exit__(self, *_exc) -> None:
        self.restore()

    def generate(self, freq_hz: float, pulse_s: float) -> PwmState:
        """PWM modo 1 com a melhor resolução que cabe no ARR de 16 bits."""
        p, t = self.pal, self.tim
        if not self._saved:
            enable_clock(p, t)
            self._saved = save_regs(p, t, ("CR1", "CCER", self.ccmr, "PSC", "ARR",
                                           f"CCR{self.ch}", "BDTR"))
        ticks = self.f_tim / freq_hz
        psc = max(0, int(ticks // 65536))
        arr = round(ticks / (psc + 1)) - 1
        ccr = round(pulse_s * self.f_tim / (psc + 1))
        p.write_reg(t, "CR1", 0)
        p.write_reg(t, "PSC", psc)
        p.write_reg(t, "ARR", arr)
        p.write_reg(t, f"CCR{self.ch}", ccr)
        shift = 0 if self.ch % 2 else 8
        ccmr = p.read_reg(t, self.ccmr) & ~(0xFF << shift) & ~(1 << (16 + shift))
        p.write_reg(t, self.ccmr, ccmr | (OCM_PWM1 << 4 | 1 << 3) << shift)   # PWM1 + preload
        ccer = p.read_reg(t, "CCER") & ~(0xF << (4 * (self.ch - 1)))
        p.write_reg(t, "CCER", ccer | 1 << (4 * (self.ch - 1)))
        if has_register(p, t, "BDTR"):                 # TIM1/TIM8: saída principal
            p.write_reg(t, "BDTR", p.read_reg(t, "BDTR") | BDTR_MOE)
        p.write_reg(t, "CR1", CR1_URS)                 # UG sem interrupção de update
        p.write_reg(t, "EGR", EGR_UG)
        p.write_reg(t, "CR1", CR1_ARPE | CR1_URS | CR1_CEN)
        st = self.read()
        log.info("%s CH%d: PSC=%d ARR=%d CCR=%d (f_tim %.6g Hz) -> %.4g Hz, pulso %.2f us",
                 t, self.ch, psc, arr, ccr, self.f_tim, st.freq_hz, st.pulse_s * 1e6)
        return st

    def restore(self) -> None:
        """Devolve os registradores do firmware (PSC/ARR valem a partir do próximo update)."""
        if self._saved:
            p, t = self.pal, self.tim
            p.write_reg(t, "CR1", 0)
            restore_regs(p, t, {k: v for k, v in self._saved.items() if k != "CR1"})
            p.write_reg(t, "CR1", self._saved["CR1"])
            self._saved = {}
