"""Driver e monitor de PWM (canal de timer, ex.: TIM2 CH3 do Pinout).

O clock do timer vem da árvore de clock do RCC (hal.clock), lida no setup().
Valores do driver: largura de pulso em segundos (frequência fixa no construtor).
"""

from __future__ import annotations

from hal.clock import clock_tree, timer_apb
from hal.common import pin_af, restore_pin, set_af, snapshot_pin
from hal.tim import PwmChannel, channel_number
from testbench.core import Driver, Monitor


def _channel(pal, signal, hse_hz: float) -> PwmChannel:
    tree = clock_tree(pal, hse_hz)
    f_tim = tree.timers[timer_apb(tree.family, signal.periph_name)]
    return PwmChannel(pal, signal.periph_name, channel_number(signal.role), f_tim)


class PwmDriver(Driver):
    """O testador gera o PWM no canal: pino em AF, timer assumido e restaurado no fim."""

    def __init__(self, signal, freq_hz: float, hse_hz: float, name: str = "") -> None:
        self.signal, self.freq_hz, self.hse_hz = signal, freq_hz, hse_hz
        self.name = name or f"pwm:{signal.name}"
        self.ch: PwmChannel | None = None
        self._snap = None

    def setup(self, pal) -> None:
        s = self.signal
        self.ch = _channel(pal, s, self.hse_hz)
        self._snap = snapshot_pin(pal, s.port, s.pin)
        set_af(pal, s.port, s.pin, pin_af(pal, s))

    def apply(self, pal, pulse_s: float) -> None:
        self.ch.generate(self.freq_hz, pulse_s)

    def teardown(self, pal) -> None:
        if self.ch is not None:
            self.ch.restore()
        if self._snap is not None:
            restore_pin(pal, self._snap)
            self._snap = None


class PwmMonitor(Monitor):
    """Lê o canal pelos registradores. Amostra: dict freq_hz, pulso_us, duty_pct, ativo."""

    def __init__(self, signal, hse_hz: float, name: str = "") -> None:
        self.signal, self.hse_hz = signal, hse_hz
        self.name = name or f"pwm_reg:{signal.name}"
        self.ch: PwmChannel | None = None

    def setup(self, pal) -> None:
        self.ch = _channel(pal, self.signal, self.hse_hz)

    def sample(self, pal) -> dict:
        st = self.ch.read()
        return {"freq_hz": st.freq_hz, "pulso_us": st.pulse_s * 1e6, "duty_pct": st.duty * 100,
                "ativo": st.enabled and st.pwm_mode}
