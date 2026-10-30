"""Blocos de PWM para servo — verificar o PWM do firmware ou gerar pelo testador.

Os pinos vêm do Pinout do projeto (tipo PWM: timer + canal, ex. TIM2 CH3). O
clock do timer sai da árvore de clock do RCC; por isso o HSE é parâmetro.

    PwmFirmware   monitores PwmMonitor (registradores) + GpioActivityMonitor (pino)
                  decisões: frequência ± tol, pulso dentro da faixa do servo, pino comuta
    PwmServoGerar driver PwmDriver (o testador assume o timer) + os mesmos monitores
                  estímulo: lista de larguras de pulso; decisão: o pulso acompanha

Medida de tempo no pino exige instrumento (osciloscópio): a amostragem pelo SWD
só confirma que o pino comuta e dá um duty aproximado.
"""

from core.analysis.metrics import Measurement
from testbench import ComposedTest, Decision, Step, Stimulus, Testbench, Trace, Verdict
from testbench.clock import expected_hz
from testbench.decision import Satisfies, WithinTolerance
from testbench.gpio import GpioActivityMonitor
from testbench.pwm import PwmDriver, PwmMonitor
from testbench.stimulus import Sample
from tests_builtin.params import Bool, Float, Int, Signals, Text


def _comuta(v) -> bool:
    return v["transicoes"] > 0


def _atividade(v) -> str:
    return f"{v['transicoes']} transições, {v['alto_pct']:.1f} % em 1"


class PwmFirmware(ComposedTest):
    name        = "PWM — Verificar saída do firmware (servo)"
    category    = "PWM"
    description = ("Lê PSC/ARR/CCR do canal que o firmware configurou: frequência, largura de "
                   "pulso dentro da faixa do servo e saída ativa; opcionalmente confere se o "
                   "pino comuta.")
    params = {
        "pinos":     Signals("Saídas PWM", types=("PWM",)),
        "hse_mhz":   Float("HSE / cristal (MHz)", 0.0, maximum=60.0, help="0 = do projeto (.ioc)"),
        "freq_hz":   Float("Frequência esperada (Hz)", 50.0, minimum=0.1, maximum=1e6),
        "tol_freq_pct": Float("Tolerância da frequência (%)", 1.0, minimum=0.0, maximum=50.0),
        "pulso_min_us": Float("Pulso mínimo (µs)", 500.0, minimum=0.0, maximum=1e6),
        "pulso_max_us": Float("Pulso máximo (µs)", 2500.0, minimum=0.0, maximum=1e6),
        "verificar_pino": Bool("Conferir se o pino comuta", True,
                               help="Desmarque se o firmware deixa o pulso em 0 (servo parado)"),
    }

    def build(self) -> Testbench:
        p = self.p
        monitors, decisions = [], []
        centro = (p.pulso_min_us + p.pulso_max_us) / 2
        meia = (p.pulso_max_us - p.pulso_min_us) / 2
        for s in p.pinos:
            reg = PwmMonitor(s, expected_hz(p.hse_mhz, "HSE"))
            monitors.append(reg)
            decisions += [
                Satisfies(reg.name, lambda v: v["ativo"], metric="pwm_inativo", label=s.name,
                          what="com contador ou saída desligados",
                          describe=lambda v: "ativo" if v["ativo"] else "inativo"),
                WithinTolerance(reg.name, p.freq_hz, tol_pct=p.tol_freq_pct, key="freq_hz",
                                metric=f"pwm_freq_hz_{s.name}", unit="Hz",
                                label=f"{s.name} freq", fmt="{:.4g}".format),
                WithinTolerance(reg.name, centro, tol_abs=meia, key="pulso_us",
                                metric=f"pwm_pulso_us_{s.name}", unit="µs",
                                label=f"{s.name} pulso", fmt="{:.1f}".format),
            ]
            if p.verificar_pino:
                act = GpioActivityMonitor(s)
                monitors.append(act)
                decisions.append(Satisfies(act.name, _comuta, metric="pwm_pino_parado",
                                           label=s.name, what="sem transições",
                                           describe=_atividade))
        return Testbench(monitors=monitors, stimulus=Sample(1), decisions=decisions)

    def summary(self, trace, verdicts) -> str:
        partes = []
        for s in self.p.pinos:
            v = trace.series(f"pwm_reg:{s.name}")
            if v:
                v = v[-1]
                partes.append(f"{s.name} ({s.periph_name} {s.role}): {v['freq_hz']:.4g} Hz, "
                              f"{v['pulso_us']:.1f} µs" + ("" if v["ativo"] else " INATIVO"))
        falhas = [v.message for v in verdicts if v.ok is False]
        return ("; ".join(falhas) + " | " if falhas else "") + "; ".join(partes)


class _Pulsos(Stimulus):
    """Aplica cada largura de pulso em todos os drivers e espera o servo/timer assentar."""

    def __init__(self, drivers, pulsos_s, wait_s) -> None:
        self.drivers, self.pulsos_s, self.wait_s = drivers, pulsos_s, wait_s

    def steps(self):
        for pulso in self.pulsos_s:
            yield Step({d: pulso for d in self.drivers}, self.wait_s, f"{pulso * 1e6:.0f} µs")


class _PulsoAcompanha(Decision):
    """O pulso lido nos registradores bate com o aplicado (± resolução do timer)."""

    def __init__(self, monitor: str, driver: str, tol_us: float, label: str) -> None:
        self.monitor, self.driver, self.tol_us, self.label = monitor, driver, tol_us, label
        self.name = f"pulso:{label}"

    def evaluate(self, trace: Trace) -> Verdict:
        pares = trace.pairs(self.driver, self.monitor)
        if not pares:
            return Verdict(False, f"{self.label}: nenhuma amostra")
        erros = [abs(o["pulso_us"] - d * 1e6) for d, o, _ in pares]
        ruins = [(d, o) for (d, o, _), e in zip(pares, erros, strict=True) if e > self.tol_us]
        m = Measurement(f"pwm_pulso_erro_us_{self.label}", max(erros), "µs", samples=erros,
                        limit_max=self.tol_us, nominal=0.0,
                        description=f"{self.label}: maior |pulso lido - aplicado|")
        if ruins:
            d, o = ruins[0]
            return Verdict(False, f"{self.label}: aplicado {d * 1e6:.0f} µs, lido "
                                  f"{o['pulso_us']:.1f} µs", [m])
        return Verdict(True, f"{self.label}: {len(pares)} pulsos ok (erro máx "
                             f"{max(erros):.2f} µs)", [m])


class PwmServoGerar(ComposedTest):
    name        = "PWM — Gerar pulsos de servo pelo testador"
    category    = "PWM"
    description = ("O testador assume o timer e gera a sequência de pulsos (ex.: 1000, 1500, "
                   "2000 µs a 50 Hz); confere registradores e se o pino comuta. Restaura o "
                   "timer do firmware no fim. Use com o firmware sem controlar o servo.")
    params = {
        "pinos":     Signals("Saídas PWM", types=("PWM",)),
        "hse_mhz":   Float("HSE / cristal (MHz)", 0.0, maximum=60.0, help="0 = do projeto (.ioc)"),
        "freq_hz":   Float("Frequência (Hz)", 50.0, minimum=0.1, maximum=1e6),
        "pulsos_us": Text("Pulsos (µs)", "1000, 1500, 2000", "ex.: 1000, 1500, 2000"),
        "espera_ms": Int("Espera em cada pulso (ms)", 300, minimum=0, maximum=10_000),
        "tol_us":    Float("Tolerância do pulso (µs)", 2.0, minimum=0.0, maximum=1e6),
        "verificar_pino": Bool("Conferir se o pino comuta", True),
    }

    def _pulsos(self) -> list[float]:
        return [float(x) * 1e-6 for x in self.p.pulsos_us.replace(";", ",").split(",")
                if x.strip()]

    def _run(self, pal):
        try:
            if not self._pulsos():
                return self._fail("Informe ao menos um pulso em 'Pulsos (µs)'")
        except ValueError:
            return self._fail(f"Pulsos inválidos: '{self.p.pulsos_us}'")
        return super()._run(pal)

    def build(self) -> Testbench:
        p = self.p
        drivers, monitors, decisions = [], [], []
        for s in p.pinos:
            drv = PwmDriver(s, p.freq_hz, expected_hz(p.hse_mhz, "HSE"))
            reg = PwmMonitor(s, expected_hz(p.hse_mhz, "HSE"))
            drivers.append(drv)
            monitors.append(reg)
            decisions.append(_PulsoAcompanha(reg.name, drv.name, p.tol_us, s.name))
            if p.verificar_pino:
                act = GpioActivityMonitor(s)
                monitors.append(act)
                decisions.append(Satisfies(act.name, _comuta, metric="pwm_pino_parado",
                                           label=s.name, what="sem transições",
                                           describe=_atividade))
        return Testbench(drivers, monitors,
                         _Pulsos([d.name for d in drivers], self._pulsos(), p.espera_ms / 1000),
                         decisions)
