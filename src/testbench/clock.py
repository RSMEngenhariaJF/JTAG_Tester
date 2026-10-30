"""Monitores de clock: árvore configurada no RCC e frequência real da CPU."""

from __future__ import annotations

from hal.clock import (
    ClockConfig,
    ClockError,
    ClockTree,
    H7ClockControl,
    clock_tree,
    measure_cpu_hz,
)
from testbench.core import Driver, Monitor


class ClockTreeMonitor(Monitor):
    """Lê a árvore de clock (RCC). Amostra: dict nome → Hz (SYSCLK, CPU, HCLK, APB1...)."""

    def __init__(self, hse_hz: float, name: str = "rcc") -> None:
        self.hse_hz, self.name = hse_hz, name
        self.tree: ClockTree | None = None

    def sample(self, pal) -> dict[str, float]:
        self.tree = clock_tree(pal, self.hse_hz)
        return self.tree.values()


class CpuClockMonitor(Monitor):
    """Mede a frequência real da CPU pelo DWT_CYCCNT. Amostra: Hz ou None (erro em .error).

    sram_base: com o núcleo parado (sem firmware), roda um laço nessa SRAM durante
    a medida (BoardConfig.sram_base).
    """

    def __init__(self, window_s: float = 0.5, sram_base: int | None = None,
                 name: str = "cpu_medido") -> None:
        self.window_s, self.sram_base, self.name = window_s, sram_base, name
        self.error = ""

    def sample(self, pal) -> float | None:
        try:
            return measure_cpu_hz(pal, self.window_s, self.sram_base)
        except RuntimeError as exc:
            self.error = str(exc)
            return None


# ── Clock esperado do projeto (importado do .ioc) ────────────────────────────

def project_clocks() -> dict:
    """ProjectConfig.clocks do projeto ativo ({} se não houver projeto ou .ioc)."""
    from core.project.config import get_active_project

    proj = get_active_project()
    return dict(proj.clocks) if proj is not None else {}


def expected_hz(param_mhz: float, key: str, clocks: dict | None = None) -> float:
    """Parâmetro em MHz; 0 = valor do projeto (Hz); 0.0 se nenhum dos dois."""
    if param_mhz:
        return param_mhz * 1e6
    return float((project_clocks() if clocks is None else clocks).get(key, 0.0))


# ── Driver: fonte de clock escolhida pelo testador (sem firmware) ────────────

class ClockSourceDriver(Driver):
    """Valores do passo: "HSE" (liga o cristal e roda a CPU direto nele), "LSE" (liga
    o cristal de 32 kHz) ou "PLL" (árvore do projeto). Erros de oscilador não
    abortam a bancada: ficam em .errors para as decisões; .startup_ms guarda o
    tempo até RDY. teardown() volta ao estado de reset (HSI), salvo keep=True.
    """

    def __init__(self, cfg: ClockConfig | None, hse_hz: float, *, hse_bypass: bool = False,
                 lse_bypass: bool = False, keep: bool = False, name: str = "clk_src") -> None:
        self.cfg, self.hse_hz, self.name, self.keep = cfg, hse_hz, name, keep
        self.hse_bypass, self.lse_bypass = hse_bypass, lse_bypass
        self.errors: dict[str, str] = {}
        self.startup_ms: dict[str, float] = {}
        self.ctl: H7ClockControl | None = None

    def setup(self, pal) -> None:
        self.ctl = H7ClockControl(pal)
        self.ctl.save()

    def apply(self, pal, value: str) -> None:
        try:
            if value == "HSE":
                self.startup_ms["HSE"] = self.ctl.start_hse(self.hse_bypass)
                self.ctl.use_hse()
            elif value == "LSE":
                self.startup_ms["LSE"] = self.ctl.start_lse(self.lse_bypass, timeout_s=6.0)
            elif value == "PLL":
                if self.cfg is None:
                    raise ClockError("sem configuração do PLL no projeto")
                self.ctl.use_pll(self.cfg)
            else:
                raise ValueError(f"fonte desconhecida: {value}")
        except ClockError as exc:
            self.errors[value] = str(exc)

    def teardown(self, pal) -> None:
        if self.ctl is not None and not self.keep:
            self.ctl.restore()
