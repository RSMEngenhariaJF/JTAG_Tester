"""Bloco de clock — clock de entrada (cristais), árvore do RCC e frequência real.

Dois modos:

* configurar pelo testador (sem firmware) — o testador monta o clock do zero:

    estímulo  "HSE direto" → "LSE" → "PLL do projeto"
    driver    ClockSourceDriver   — liga o cristal, troca o SYSCLK, monta o PLL1
    monitores ClockTreeMonitor    — o que o RCC diz (registradores)
              CpuClockMonitor     — o que o chip faz (DWT_CYCCNT vs. relógio do PC),
                                    com um laço na SRAM porque não há firmware
    decisões  _Partida            — o oscilador partiu (RDY) e em quanto tempo
              WithinTolerance     — HSE medido ≈ cristal; PLL medido ≈ CPU do projeto;
                                    árvore do RCC ≈ .ioc

  "HSE direto" põe a CPU no cristal sem PLL: a frequência medida é a do próprio
  cristal. Partida lenta ou ausente aponta cristal, capacitores de carga ou
  trilhas OSC_IN/OSC_OUT; frequência errada aponta cristal trocado ou
  oscilando em harmônica. Resolução da medida: ~0,1 %, sem chegar a ppm (para
  isso, MCO no frequencímetro/osciloscópio).

* ler como está (com firmware) — só monitores: compara a árvore que o firmware
  configurou com o projeto e mede a CPU.

Genérico: tudo que é esperado vem do projeto (clock importado do .ioc,
ProjectConfig.clocks). Parâmetro 0 = usar o projeto.
"""

from core.analysis.metrics import Measurement
from hal.clock import ClockConfig, ClockError
from testbench import ComposedTest, Decision, Step, Stimulus, Testbench, Trace, Verdict
from testbench.clock import (
    ClockSourceDriver,
    ClockTreeMonitor,
    CpuClockMonitor,
    expected_hz,
    project_clocks,
)
from testbench.decision import WithinTolerance
from testbench.stimulus import Sample
from tests_builtin.params import Bool, Choice, Float

_PROJ = "0 = do projeto (.ioc)"
CONFIGURAR = "configurar pelo testador (sem firmware)"
HSE_STEP, PLL_STEP = "HSE direto", "PLL do projeto"


def _mhz(hz: float) -> str:
    return f"{hz / 1e6:.6g} MHz"


def _sram_base() -> int | None:
    from core.board.config import get_active_board
    try:
        return get_active_board().sram_base
    except Exception:
        return None


class _Sequencia(Stimulus):
    def __init__(self, driver: str, lse: bool) -> None:
        self.driver, self.lse = driver, lse

    def steps(self):
        yield Step({self.driver: "HSE"}, 0.0, HSE_STEP)
        if self.lse:
            yield Step({self.driver: "LSE"}, 0.0, "LSE", sample=False)
        yield Step({self.driver: "PLL"}, 0.0, PLL_STEP)


class _Partida(Decision):
    """O oscilador ficou pronto (RDY) dentro do tempo máximo."""

    def __init__(self, driver: ClockSourceDriver, osc: str, max_ms: float) -> None:
        self.driver, self.osc, self.max_ms, self.name = driver, osc, max_ms, f"partida_{osc}"

    def evaluate(self, trace: Trace) -> Verdict:
        if self.osc in self.driver.errors:
            return Verdict(False, self.driver.errors[self.osc])
        ms = self.driver.startup_ms.get(self.osc)
        if ms is None:
            return Verdict(False, f"{self.osc}: não foi ligado")
        m = Measurement(f"clk_{self.osc.lower()}_partida_ms", ms, "ms", limit_max=self.max_ms,
                        description=f"tempo até {self.osc}RDY (resolução ~1 ms, via SWD)")
        ok = ms <= self.max_ms
        return Verdict(ok, f"{self.osc} partiu em {ms:.1f} ms" +
                       ("" if ok else f" (máx {self.max_ms:g} ms)"), [m])


class _FonteEsperada(Decision):
    """A fonte do SYSCLK é a esperada e o oscilador/PLL dela está pronto."""

    def __init__(self, monitor: ClockTreeMonitor, fonte: str,
                 driver: ClockSourceDriver | None = None) -> None:
        self.monitor, self.fonte, self.driver, self.name = monitor, fonte, driver, "fonte_sysclk"

    def evaluate(self, trace: Trace) -> Verdict:
        tree = self.monitor.tree
        if tree is None:
            return Verdict(False, "árvore de clock não lida")
        origem = tree.source + (f" ← {tree.pll_src}" if tree.source.startswith("PLL") else "")
        falhas = list(tree.notes)
        if self.driver is not None and "PLL" in self.driver.errors:
            falhas.append(self.driver.errors["PLL"])
        if self.fonte != "qualquer" and tree.source != self.fonte:
            falhas.append(f"SYSCLK vem de {tree.source} (esperado {self.fonte})")
        if not tree.ready.get(tree.source, True):
            falhas.append(f"{tree.source} não está pronto (RDY=0)")
        if falhas:
            return Verdict(False, "; ".join(falhas))
        return Verdict(True, f"fonte {origem}")


class AnaliseClock(ComposedTest):
    name        = "Clock — Cristais, árvore e frequência real"
    category    = "Clock"
    description = ("Sem firmware: liga o HSE (e o LSE), mede o cristal rodando a CPU direto "
                   "nele, monta o PLL do .ioc e mede de novo. Com firmware: compara a árvore "
                   "configurada com o projeto. Valida cristais, trilhas e PLL.")
    params = {
        "modo":       Choice("Modo", (CONFIGURAR, "ler como está (com firmware)")),
        "hse_mhz":    Float("HSE / cristal (MHz)", 0.0, maximum=60.0, help=_PROJ),
        "tol_hse_pct": Float("Tolerância do HSE medido (%)", 0.5, minimum=0.0, maximum=50.0,
                             help="Limite da medida pelo SWD (~0,1 %); ppm só com instrumento"),
        "partida_hse_ms": Float("Partida máxima do HSE (ms)", 20.0, minimum=0.0, maximum=1000.0),
        "lse":        Choice("Verificar o LSE (32 kHz)", ("do projeto", "sim", "não")),
        "partida_lse_ms": Float("Partida máxima do LSE (ms)", 5000.0, minimum=0.0,
                                maximum=60_000.0),
        "fonte":      Choice("Fonte do SYSCLK", ("do projeto", "PLL1", "HSE", "HSI", "CSI",
                                                 "qualquer")),
        "sysclk_mhz": Float("SYSCLK esperado (MHz)", 0.0, maximum=1000.0, help=_PROJ),
        "cpu_mhz":    Float("CPU esperada (MHz)", 0.0, maximum=1000.0, help=_PROJ),
        "hclk_mhz":   Float("HCLK / AHB esperado (MHz)", 0.0, maximum=1000.0, help=_PROJ),
        "apb1_mhz":   Float("APB1 esperado (MHz)", 0.0, maximum=1000.0, help=_PROJ),
        "apb2_mhz":   Float("APB2 esperado (MHz)", 0.0, maximum=1000.0, help=_PROJ),
        "apb3_mhz":   Float("APB3 esperado (MHz, H7)", 0.0, maximum=1000.0, help=_PROJ),
        "apb4_mhz":   Float("APB4 esperado (MHz, H7)", 0.0, maximum=1000.0, help=_PROJ),
        "tim_mhz":    Float("Clock dos timers APB1/APB2 (MHz)", 0.0, maximum=1000.0, help=_PROJ),
        "tol_cfg_pct": Float("Tolerância da configuração (%)", 0.1, minimum=0.0, maximum=50.0),
        "medir_cpu":  Bool("Medir a frequência real da CPU (DWT)", True),
        "janela_s":   Float("Janela de medida (s)", 0.5, minimum=0.05, maximum=5.0),
        "tol_med_pct": Float("Tolerância da medida real (%)", 1.0, minimum=0.0, maximum=50.0),
        "manter":     Bool("Manter o clock configurado no fim", False,
                           help="Desmarcado: volta ao estado de reset (HSI 64 MHz)"),
    }

    def _configurar(self) -> bool:
        return self.p.modo == CONFIGURAR

    def _run(self, pal):
        if not expected_hz(self.p.hse_mhz, "HSE"):
            return self._fail("HSE desconhecido: informe 'HSE / cristal' ou importe o .ioc "
                              "no projeto (o cristal não fica em registrador)")
        if self._configurar():
            try:
                ClockConfig.from_project(project_clocks())
            except ClockError as exc:
                return self._fail(str(exc))
        return super()._run(pal)

    def build(self) -> Testbench:
        p, clocks = self.p, project_clocks()
        hse = expected_hz(p.hse_mhz, "HSE", clocks)
        self.rcc = ClockTreeMonitor(hse)
        monitors: list = [self.rcc]
        drivers: list = []
        decisions: list[Decision] = []
        self.drv = None
        step = None
        if self._configurar():
            cfg = ClockConfig.from_project(clocks)
            cfg.hse_hz = hse
            lse = p.lse == "sim" or (p.lse == "do projeto" and "LSE" in clocks)
            self.drv = ClockSourceDriver(cfg, hse, hse_bypass=cfg.hse_bypass,
                                         lse_bypass=bool(clocks.get("LSE_BYPASS")),
                                         keep=p.manter)
            drivers.append(self.drv)
            decisions.append(_Partida(self.drv, "HSE", p.partida_hse_ms))
            if lse:
                decisions.append(_Partida(self.drv, "LSE", p.partida_lse_ms))
            stimulus = _Sequencia(self.drv.name, lse)
            step = PLL_STEP
            fonte = "PLL1"
        else:
            stimulus = Sample(1)
            fonte = clocks.get("fonte", "qualquer") if p.fonte == "do projeto" else p.fonte
        if p.fonte not in ("do projeto",):
            fonte = p.fonte
        decisions.insert(0, _FonteEsperada(self.rcc, fonte, self.drv))

        esperados = {"SYSCLK": p.sysclk_mhz, "CPU": p.cpu_mhz, "HCLK": p.hclk_mhz,
                     "APB1": p.apb1_mhz, "APB2": p.apb2_mhz, "APB3": p.apb3_mhz,
                     "APB4": p.apb4_mhz, "TIM_APB1": p.tim_mhz, "TIM_APB2": p.tim_mhz}
        self.verificados = []
        for key, mhz in esperados.items():
            hz = expected_hz(mhz, key, clocks)
            if hz:
                self.verificados.append(key)
                decisions.append(WithinTolerance("rcc", hz, tol_pct=p.tol_cfg_pct, key=key,
                                                 metric=f"clk_{key.lower()}_hz", unit="Hz",
                                                 fmt=_mhz, step=step))
        self.cpu = None
        self.cpu_hz = expected_hz(p.cpu_mhz, "CPU", clocks)
        if p.medir_cpu:
            self.cpu = CpuClockMonitor(p.janela_s, _sram_base())
            monitors.append(self.cpu)
            if self._configurar():
                decisions.append(WithinTolerance(
                    "cpu_medido", hse, tol_pct=p.tol_hse_pct, metric="clk_hse_medido_hz",
                    unit="Hz", label="HSE medido", fmt=_mhz, step=HSE_STEP))
            if self.cpu_hz:
                decisions.append(WithinTolerance(
                    "cpu_medido", self.cpu_hz, tol_pct=p.tol_med_pct,
                    metric="clk_cpu_medido_hz", unit="Hz", label="CPU medida", fmt=_mhz,
                    step=step))
        return Testbench(drivers, monitors, stimulus, decisions)

    def summary(self, trace, verdicts) -> str:
        partes = []
        if self.drv is not None:
            for osc in ("HSE", "LSE"):
                if osc in self.drv.startup_ms:
                    partes.append(f"{osc} partiu em {self.drv.startup_ms[osc]:.1f} ms")
            medido = [o.observed.get("cpu_medido") for o in trace.observations
                      if o.label == HSE_STEP]
            if medido and medido[0]:
                hse = self.rcc.hse_hz
                partes.append(f"HSE medido {_mhz(medido[0])} "
                              f"({(medido[0] / hse - 1) * 100:+.2f} % do cristal)")
        tree = self.rcc.tree
        if tree is not None:
            partes += [f"SYSCLK {_mhz(tree.sysclk)} ({verdicts[0].message})",
                       f"CPU {_mhz(tree.cpu)}", f"HCLK {_mhz(tree.hclk)}"]
            partes += [f"{k} {_mhz(v)}" for k, v in sorted(tree.apb.items())]
        if self.cpu is not None:
            serie = trace.series("cpu_medido")
            if serie and serie[-1] and self.cpu_hz:
                partes.append(f"CPU medida {_mhz(serie[-1])} "
                              f"({(serie[-1] / self.cpu_hz - 1) * 100:+.2f} %)")
            elif self.cpu.error:
                partes.append(f"medida indisponível: {self.cpu.error}")
        if not self.verificados:
            partes.append("nenhum valor esperado (importe o .ioc ou preencha os parâmetros)")
        falhas = [v.message for v in verdicts if v.ok is False]
        return ("FALHAS: " + "; ".join(falhas) + " | " if falhas else "") + ", ".join(partes)
