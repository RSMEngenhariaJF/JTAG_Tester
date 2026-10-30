"""Árvore de clock lida do RCC (F4 e H7) e medida da frequência real da CPU.

clock_tree(pal, hse_hz) calcula, a partir dos registradores que o firmware
configurou, as frequências de SYSCLK, CPU, HCLK, APBx, timers e PLLs. O valor
do cristal (HSE) não está em registrador nenhum: vem do projeto (parâmetro).

measure_cpu_hz(pal) mede a frequência real com o contador de ciclos do núcleo
(DWT_CYCCNT) contra o relógio do PC: valida cristal + PLL de verdade, não só a
configuração. Exige o núcleo rodando (firmware liberado após a conexão).

Registradores lidos em bits brutos (RM0433 §8.7 / RM0390 §6.3) para não
depender de nomes de campo que variam entre revisões de SVD.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from hal.common import family

log = logging.getLogger("hal.clock")

HSI_F4, CSI_H7 = 16_000_000, 4_000_000

# ── Divisores codificados ─────────────────────────────────────────────────────

_AHB_DIV = {8: 2, 9: 4, 10: 8, 11: 16, 12: 64, 13: 128, 14: 256, 15: 512}   # HPRE/D1CPRE
_APB_DIV = {4: 2, 5: 4, 6: 8, 7: 16}                                         # PPRE


def _ahb(code: int) -> int:
    return _AHB_DIV.get(code, 1)


def _apb(code: int) -> int:
    return _APB_DIV.get(code, 1)


def _bits(value: int, lsb: int, width: int) -> int:
    return value >> lsb & ((1 << width) - 1)


def _timer_clock(hclk: float, pclk: float, apb_div: int, timpre: int = 0) -> float:
    """Clock dos timers de um barramento APB (TIMPRE=0: 2x se o APB divide)."""
    if timpre:
        return hclk if apb_div <= 4 else 4 * pclk
    return pclk if apb_div == 1 else 2 * pclk


@dataclass
class ClockTree:
    family:   str
    source:   str                                   # "HSI", "HSE", "CSI", "PLL1"
    sysclk:   float
    cpu:      float
    hclk:     float
    apb:      dict[str, float]                      # "APB1" → Hz
    timers:   dict[str, float]                      # "APB1" → clock dos timers desse APB
    plls:     dict[str, dict[str, float]] = field(default_factory=dict)  # "PLL1" → {p,q,r,vco}
    pll_src:  str = ""
    ready:    dict[str, bool] = field(default_factory=dict)              # "HSE" → HSERDY
    notes:    list[str] = field(default_factory=list)

    def values(self) -> dict[str, float]:
        """Frequências planas, nome → Hz (para monitores e relatório)."""
        out = {"SYSCLK": self.sysclk, "CPU": self.cpu, "HCLK": self.hclk}
        out.update(self.apb)
        out.update({f"TIM_{k}": v for k, v in self.timers.items()})
        for pll, outs in self.plls.items():
            out.update({f"{pll}_{k.upper()}": v for k, v in outs.items()})
        return out


# Barramento APB de cada timer (H7: RM0433 §8.5; F4: RM0390 §6.2)
_TIMER_APB = {
    "H7": {**dict.fromkeys(("TIM2", "TIM3", "TIM4", "TIM5", "TIM6", "TIM7", "TIM12", "TIM13",
                            "TIM14"), "APB1"),
           **dict.fromkeys(("TIM1", "TIM8", "TIM15", "TIM16", "TIM17"), "APB2")},
    "F4": {**dict.fromkeys(("TIM2", "TIM3", "TIM4", "TIM5", "TIM6", "TIM7", "TIM12", "TIM13",
                            "TIM14"), "APB1"),
           **dict.fromkeys(("TIM1", "TIM8", "TIM9", "TIM10", "TIM11"), "APB2")},
}


def timer_apb(fam: str, timer: str) -> str:
    try:
        return _TIMER_APB[fam][timer.upper()]
    except KeyError:
        raise LookupError(f"{timer}: barramento desconhecido para {fam}") from None


def clock_tree(pal, hse_hz: float) -> ClockTree:
    return _tree_h7(pal, hse_hz) if family(pal) == "H7" else _tree_f4(pal, hse_hz)


# ── H7 ────────────────────────────────────────────────────────────────────────

def _tree_h7(pal, hse_hz: float) -> ClockTree:
    rd = lambda reg: pal.read_reg("RCC", reg)    # noqa: E731
    cr, cfgr = rd("CR"), rd("CFGR")
    hsi = 64_000_000 >> _bits(cr, 3, 2)
    ready = {"HSI": bool(cr >> 2 & 1), "CSI": bool(cr >> 8 & 1), "HSE": bool(cr >> 17 & 1),
             "PLL1": bool(cr >> 25 & 1), "PLL2": bool(cr >> 27 & 1), "PLL3": bool(cr >> 29 & 1)}

    cksel, pllcfgr = rd("PLLCKSELR"), rd("PLLCFGR")
    src_code = _bits(cksel, 0, 2)
    pll_src, f_src = [("HSI", hsi), ("CSI", CSI_H7), ("HSE", hse_hz), ("nenhuma", 0)][src_code]
    plls: dict[str, dict[str, float]] = {}
    for n, m_lsb in ((1, 4), (2, 12), (3, 20)):
        if not cr >> (22 + 2 * n) & 1:            # PLLnON
            continue
        divm = _bits(cksel, m_lsb, 6)
        divr = rd(f"PLL{n}DIVR")
        frac = _bits(rd(f"PLL{n}FRACR"), 3, 13) if pllcfgr >> (4 * (n - 1)) & 1 else 0
        vco = f_src / divm * (_bits(divr, 0, 9) + 1 + frac / 8192) if divm else 0.0
        plls[f"PLL{n}"] = {"vco": vco,
                           "p": vco / (_bits(divr, 9, 7) + 1),
                           "q": vco / (_bits(divr, 16, 7) + 1),
                           "r": vco / (_bits(divr, 24, 7) + 1)}

    sws = _bits(cfgr, 3, 3)
    source = {0: "HSI", 1: "CSI", 2: "HSE", 3: "PLL1"}.get(sws, f"SWS={sws}")
    sysclk = {"HSI": hsi, "CSI": CSI_H7, "HSE": hse_hz}.get(source) or \
        plls.get("PLL1", {}).get("p", 0.0)

    d1, d2, d3 = rd("D1CFGR"), rd("D2CFGR"), rd("D3CFGR")
    cpu = sysclk / _ahb(_bits(d1, 8, 4))           # D1CPRE
    hclk = cpu / _ahb(_bits(d1, 0, 4))             # HPRE
    divs = {"APB3": _apb(_bits(d1, 4, 3)), "APB1": _apb(_bits(d2, 4, 3)),
            "APB2": _apb(_bits(d2, 8, 3)), "APB4": _apb(_bits(d3, 4, 3))}
    apb = {k: hclk / v for k, v in divs.items()}
    timpre = cfgr >> 15 & 1
    timers = {k: _timer_clock(hclk, apb[k], divs[k], timpre) for k in ("APB1", "APB2")}
    notes = []
    if source == "PLL1" and pll_src == "HSE" and not ready["HSE"]:
        notes.append("PLL1 usa o HSE, mas HSERDY=0")
    return ClockTree("H7", source, sysclk, cpu, hclk, apb, timers, plls, pll_src, ready, notes)


# ── F4 ────────────────────────────────────────────────────────────────────────

def _tree_f4(pal, hse_hz: float) -> ClockTree:
    cr, cfgr, pll = (pal.read_reg("RCC", r) for r in ("CR", "CFGR", "PLLCFGR"))
    ready = {"HSI": bool(cr >> 1 & 1), "HSE": bool(cr >> 17 & 1), "PLL1": bool(cr >> 25 & 1)}
    pll_src, f_src = ("HSE", hse_hz) if pll >> 22 & 1 else ("HSI", HSI_F4)
    m, n = _bits(pll, 0, 6), _bits(pll, 6, 9)
    vco = f_src / m * n if m else 0.0
    plls = {"PLL1": {"vco": vco, "p": vco / (2 * (_bits(pll, 16, 2) + 1)),
                     "q": vco / (_bits(pll, 24, 4) or 1)}}
    sws = _bits(cfgr, 2, 2)
    source = {0: "HSI", 1: "HSE", 2: "PLL1"}.get(sws, f"SWS={sws}")
    sysclk = {"HSI": HSI_F4, "HSE": hse_hz, "PLL1": plls["PLL1"]["p"]}.get(source, 0.0)
    hclk = sysclk / _ahb(_bits(cfgr, 4, 4))
    divs = {"APB1": _apb(_bits(cfgr, 10, 3)), "APB2": _apb(_bits(cfgr, 13, 3))}
    apb = {k: hclk / v for k, v in divs.items()}
    timers = {k: _timer_clock(hclk, apb[k], divs[k]) for k in divs}
    return ClockTree("F4", source, sysclk, hclk, hclk, apb, timers, plls, pll_src, ready)


# ── Medida real: contador de ciclos do núcleo ─────────────────────────────────

DHCSR, DEMCR = 0xE000EDF0, 0xE000EDFC
DWT_CTRL, DWT_CYCCNT, DWT_LAR = 0xE0001000, 0xE0001004, 0xE0001FB0
_TRCENA, _CYCCNTENA, _S_HALT = 1 << 24, 1 << 0, 1 << 17


_IDLE_LOOP = 0xE7FEE7FE                 # Thumb "b ." duas vezes
_REG_SP, _REG_PC, _REG_XPSR, _XPSR_THUMB = 13, 15, 16, 1 << 24


@contextmanager
def idle_loop(mem, sram_base: int):
    """Sem firmware: roda um laço "b ." na SRAM para o núcleo contar ciclos.

    Salva a palavra da SRAM e PC/SP/xPSR; no fim para o núcleo e restaura tudo.
    """
    for need in ("halt", "resume", "read_core_register", "write_core_register"):
        if not hasattr(mem, need):
            raise RuntimeError("adaptador de debug sem controle do núcleo (halt/resume)")
    word = mem.read_mem32(sram_base)
    regs = {r: mem.read_core_register(r) for r in (_REG_SP, _REG_PC, _REG_XPSR)}
    mem.write_mem32(sram_base, _IDLE_LOOP)
    mem.write_core_register(_REG_SP, (sram_base + 0x400) & ~7)
    mem.write_core_register(_REG_PC, sram_base)
    mem.write_core_register(_REG_XPSR, _XPSR_THUMB)
    mem.resume()
    try:
        yield
    finally:
        mem.halt()
        for r, v in regs.items():
            mem.write_core_register(r, v)
        mem.write_mem32(sram_base, word)


def measure_cpu_hz(pal, window_s: float = 0.5, sram_base: int | None = None) -> float:
    """Ciclos de CPU contados em `window_s` segundos do PC. Restaura o DWT no fim.

    Núcleo parado (sem firmware): com `sram_base`, roda um laço na SRAM durante a
    medida (idle_loop); sem, recusa. Incerteza: latência de uma leitura SWD
    (~0,1 a 1 ms) sobre a janela; com 0,5 s fica abaixo de 0,3 %.
    """
    mem = pal.mem
    if mem.read_mem32(DHCSR) & _S_HALT:
        if sram_base is None:
            raise RuntimeError("núcleo parado (halt) e sem SRAM para o laço de medida")
        with idle_loop(mem, sram_base):
            return _count_cycles(mem, window_s)
    return _count_cycles(mem, window_s)


def _stamped_read(mem) -> tuple[float, int]:
    """CYCCNT com o instante do PC no MEIO da leitura SWD.

    Marcar o tempo antes da 1ª leitura e depois da 2ª soma uma latência SWD
    inteira (1 a 2,5 ms) ao intervalo do PC e puxa a medida para baixo (até
    -0,5 % em 0,5 s, visto na placa CT); o ponto médio cancela essa latência.
    """
    a = time.perf_counter()
    value = mem.read_mem32(DWT_CYCCNT)
    return (a + time.perf_counter()) / 2, value


def _count_cycles(mem, window_s: float) -> float:
    demcr, ctrl = mem.read_mem32(DEMCR), mem.read_mem32(DWT_CTRL)
    try:
        mem.write_mem32(DEMCR, demcr | _TRCENA)
        mem.write_mem32(DWT_LAR, 0xC5ACCE55)          # Cortex-M7: destrava o DWT
        mem.write_mem32(DWT_CTRL, mem.read_mem32(DWT_CTRL) | _CYCCNTENA)
        t0, c0 = _stamped_read(mem)
        time.sleep(window_s)
        t1, c1 = _stamped_read(mem)
    finally:
        mem.write_mem32(DWT_CTRL, ctrl)
        mem.write_mem32(DEMCR, demcr)
    cycles = (c1 - c0) & 0xFFFFFFFF
    if cycles == 0:
        raise RuntimeError("DWT_CYCCNT não contou (núcleo em baixo consumo ou DWT ausente)")
    hz = cycles / (t1 - t0)
    log.info("DWT_CYCCNT: %d ciclos em %.4f s -> %.6g Hz", cycles, t1 - t0, hz)
    return hz


# ── Configuração pelo testador (sem firmware) — H7 ────────────────────────────
#
# Sequência do RM0433 §8.5 (e do HAL_RCC_OscConfig/ClockConfig): alimentação e
# escala de tensão → latência da flash → HSE → PLL1 → prescalers → troca do SW.
# O estado de partida esperado é o de reset (SYSCLK no HSI); restore() volta a ele.

class ClockError(RuntimeError):
    """Oscilador ou PLL não ficou pronto, ou configuração incompatível."""


@dataclass
class ClockConfig:
    """Árvore desejada, vinda do projeto (ProjectConfig.clocks, importado do .ioc)."""

    hse_hz:     float
    hse_bypass: bool
    pll_src:    str                       # "HSE", "HSI", "CSI"
    pll1:       dict[str, int]            # m, n, p, q, r
    div:        dict[str, int]            # D1CPRE, HPRE, D1PPRE, D2PPRE1, D2PPRE2, D3PPRE
    vos:        int = 1
    supply:     str = "LDO_SUPPLY"

    @classmethod
    def from_project(cls, clocks: dict) -> ClockConfig:
        falta = [k for k in ("HSE", "PLL1") if k not in clocks]
        if falta or set(clocks.get("PLL1", {})) < set("mnpqr"):
            raise ClockError("o projeto não traz a configuração do PLL1 (DIVM1..DIVR1): "
                             "importe o .ioc do produto")
        return cls(clocks["HSE"], bool(clocks.get("HSE_BYPASS")),
                   clocks.get("PLL_SRC", "HSE") or "HSE", dict(clocks["PLL1"]),
                   {k: int(v) for k, v in clocks.get("DIV", {}).items()},
                   int(clocks.get("VOS", 1)), clocks.get("SUPPLY", "LDO_SUPPLY"))

    def expected(self) -> dict[str, float]:
        f_src = {"HSE": self.hse_hz, "HSI": 64e6, "CSI": float(CSI_H7)}[self.pll_src]
        vco = f_src / self.pll1["m"] * self.pll1["n"]
        sysclk = vco / self.pll1["p"]
        cpu = sysclk / self.div.get("D1CPRE", 1)
        hclk = cpu / self.div.get("HPRE", 1)
        return {"SYSCLK": sysclk, "CPU": cpu, "HCLK": hclk, "VCO": vco}


_AHB_CODE = {1: 0, 2: 8, 4: 9, 8: 10, 16: 11, 64: 12, 128: 13, 256: 14, 512: 15}
_APB_CODE = {1: 0, 2: 4, 4: 5, 8: 6, 16: 7}
_VOS_CODE = {1: 0b11, 2: 0b10, 3: 0b01}
# Latência da flash por clock do AXI (RM0433 tabela 17): (f_max, LATENCY, WRHIGHFREQ)
_FLASH_WS = {
    1: [(70e6, 0, 0), (140e6, 1, 1), (185e6, 2, 1), (210e6, 2, 2), (225e6, 3, 2)],
    2: [(55e6, 0, 0), (110e6, 1, 1), (165e6, 2, 1), (225e6, 3, 2)],
    3: [(45e6, 0, 0), (90e6, 1, 1), (135e6, 2, 1), (180e6, 3, 2), (225e6, 4, 2)],
}


def flash_wait_states(hclk: float, vos: int) -> tuple[int, int]:
    for f_max, lat, wrh in _FLASH_WS[vos]:
        if hclk <= f_max:
            return lat, wrh
    raise ClockError(f"HCLK {hclk / 1e6:g} MHz acima do máximo da flash em VOS{vos}")


class H7ClockControl:
    """Liga HSE/LSE, monta o PLL1 e troca o SYSCLK; restore() volta ao reset (HSI).

    Uso::

        ctl = H7ClockControl(pal)
        ms = ctl.start_hse(25e6, bypass=False)    # tempo até HSERDY
        ctl.use_hse()                              # SYSCLK = HSE (sem PLL)
        ctl.use_pll(ClockConfig.from_project(clocks))
        ctl.restore()
    """

    _RCC_REGS = ("CR", "CFGR", "D1CFGR", "D2CFGR", "D3CFGR", "PLLCKSELR", "PLLCFGR",
                 "PLL1DIVR", "BDCR")

    def __init__(self, pal) -> None:
        if family(pal) != "H7":
            raise ClockError("configuração do clock pelo testador implementada só para H7")
        self.pal = pal
        self._saved: dict[str, int] = {}
        self.vos = 3                            # escala de reset

    # ── Estado ────────────────────────────────────────────────────────────

    def save(self) -> None:
        p = self.pal
        if self._saved:
            return
        sws = _bits(p.read_reg("RCC", "CFGR"), 3, 3)
        if sws != 0:
            raise ClockError("SYSCLK não está no HSI (estado de reset): o clock já foi "
                             "configurado por um firmware — use o modo 'ler como está'")
        self._saved = {r: p.read_reg("RCC", r) for r in self._RCC_REGS}
        self._saved["ACR"] = p.read_reg("FLASH", "ACR")
        self._saved["VOS"] = p.read_field("PWR", "D3CR", "VOS")
        self._saved["DBP"] = p.read_field("PWR", "CR1", "DBP")

    def restore(self) -> None:
        if not self._saved:
            return
        p, s = self.pal, self._saved
        self._switch(0)                                           # SYSCLK ← HSI
        for r in ("D1CFGR", "D2CFGR", "D3CFGR"):
            p.write_reg("RCC", r, s[r])
        p.modify_field("RCC", "CR", "PLL1ON", 0)
        self._wait(lambda: not p.read_field("RCC", "CR", "PLL1RDY"), 0.05, "PLL1 não desligou")
        for r in ("PLLCKSELR", "PLLCFGR", "PLL1DIVR"):
            p.write_reg("RCC", r, s[r])
        if not s["CR"] >> 16 & 1:                                 # HSE estava desligado
            p.modify_field("RCC", "CR", "HSEON", 0)
            self._wait(lambda: not p.read_field("RCC", "CR", "HSERDY"), 0.05,
                       "HSE não desligou")
            p.modify_field("RCC", "CR", "HSEBYP", s["CR"] >> 18 & 1)
        if not s["BDCR"] & 1:                                     # LSE estava desligado
            p.modify_field("PWR", "CR1", "DBP", 1)
            p.modify_field("RCC", "BDCR", "LSEON", 0)
            p.modify_field("RCC", "BDCR", "LSEBYP", s["BDCR"] >> 2 & 1)
        p.modify_field("PWR", "CR1", "DBP", s["DBP"])
        p.write_reg("FLASH", "ACR", s["ACR"])                     # depois de baixar o clock
        p.modify_field("PWR", "D3CR", "VOS", s["VOS"])
        self._saved = {}
        log.info("clock restaurado: SYSCLK no HSI, PLL/HSE/LSE como antes do teste")

    # ── Osciladores ───────────────────────────────────────────────────────

    def start_hse(self, bypass: bool = False, timeout_s: float = 0.1) -> float:
        """Liga o HSE; devolve o tempo até HSERDY (ms). ClockError se não oscilar."""
        p = self.pal
        self.save()
        if p.read_field("RCC", "CR", "HSERDY"):
            return 0.0
        p.modify_field("RCC", "CR", "HSEBYP", int(bypass))
        t0 = time.perf_counter()
        p.modify_field("RCC", "CR", "HSEON", 1)
        self._wait(lambda: p.read_field("RCC", "CR", "HSERDY"), timeout_s,
                   f"HSE não ficou pronto em {timeout_s * 1000:.0f} ms (HSERDY=0): cristal, "
                   "capacitores de carga ou trilhas OSC_IN/OSC_OUT")
        ms = (time.perf_counter() - t0) * 1000
        log.info("HSE pronto (HSERDY) em %.1f ms, %s", ms, "bypass" if bypass else "cristal")
        return ms

    def start_lse(self, bypass: bool = False, timeout_s: float = 3.0) -> float:
        """Liga o LSE (domínio de backup); devolve o tempo até LSERDY (ms)."""
        p = self.pal
        self.save()
        p.modify_field("PWR", "CR1", "DBP", 1)
        if p.read_field("RCC", "BDCR", "LSERDY"):
            return 0.0
        p.modify_field("RCC", "BDCR", "LSEBYP", int(bypass))
        t0 = time.perf_counter()
        p.modify_field("RCC", "BDCR", "LSEON", 1)
        self._wait(lambda: p.read_field("RCC", "BDCR", "LSERDY"), timeout_s,
                   f"LSE não ficou pronto em {timeout_s:.0f} s (LSERDY=0): cristal de 32 kHz, "
                   "capacitores ou trilhas OSC32_IN/OSC32_OUT")
        ms = (time.perf_counter() - t0) * 1000
        log.info("LSE pronto (LSERDY) em %.1f ms", ms)
        return ms

    # ── Fonte do SYSCLK ───────────────────────────────────────────────────

    def use_hse(self) -> None:
        """SYSCLK = HSE com prescalers /1: a CPU passa a rodar na frequência do cristal."""
        p = self.pal
        if not p.read_field("RCC", "CR", "HSERDY"):
            raise ClockError("HSE desligado: chame start_hse() antes")
        for r in ("D1CFGR", "D2CFGR", "D3CFGR"):
            p.write_reg("RCC", r, 0)
        self._switch(2)

    def use_pll(self, cfg: ClockConfig) -> None:
        p = self.pal
        self.save()
        exp = cfg.expected()
        self._supply_and_vos(cfg)
        lat, wrh = flash_wait_states(exp["HCLK"], cfg.vos)
        if lat > p.read_field("FLASH", "ACR", "LATENCY"):          # sobe antes do clock
            self._flash(lat, wrh)
        if cfg.pll_src == "HSE":
            self.start_hse(cfg.hse_bypass)
        if _bits(p.read_reg("RCC", "CFGR"), 3, 3) == 3:
            self._switch(0)
        p.modify_field("RCC", "CR", "PLL1ON", 0)
        self._wait(lambda: not p.read_field("RCC", "CR", "PLL1RDY"), 0.05, "PLL1 não desligou")
        m, n, pp, q, r = (cfg.pll1[k] for k in "mnpqr")
        src = {"HSI": 0, "CSI": 1, "HSE": 2}[cfg.pll_src]
        f_ref = {"HSE": cfg.hse_hz, "HSI": 64e6, "CSI": float(CSI_H7)}[cfg.pll_src] / m
        if not 1e6 <= f_ref <= 16e6:
            raise ClockError(f"entrada do PLL1 {f_ref / 1e6:g} MHz fora de 1 a 16 MHz (DIVM1)")
        rge = 0 if f_ref < 2e6 else 1 if f_ref < 4e6 else 2 if f_ref < 8e6 else 3
        cksel = p.read_reg("RCC", "PLLCKSELR") & ~(0b11 | 0x3F << 4)
        p.write_reg("RCC", "PLLCKSELR", cksel | src | m << 4)
        cfgr = p.read_reg("RCC", "PLLCFGR") & ~0xF                 # FRACEN, VCOSEL, RGE (PLL1)
        vcosel = 1 if exp["VCO"] < 192e6 else 0
        p.write_reg("RCC", "PLLCFGR", cfgr | rge << 2 | vcosel << 1 | 0b111 << 16)
        p.write_reg("RCC", "PLL1DIVR", (n - 1) | (pp - 1) << 9 | (q - 1) << 16 | (r - 1) << 24)
        p.modify_field("RCC", "CR", "PLL1ON", 1)
        self._wait(lambda: p.read_field("RCC", "CR", "PLL1RDY"), 0.05,
                   "PLL1 não travou (PLL1RDY=0): confira DIVM1/DIVN1 e o HSE")
        d = cfg.div
        p.write_reg("RCC", "D1CFGR", _AHB_CODE[d.get("D1CPRE", 1)] << 8
                    | _APB_CODE[d.get("D1PPRE", 1)] << 4 | _AHB_CODE[d.get("HPRE", 1)])
        p.write_reg("RCC", "D2CFGR", _APB_CODE[d.get("D2PPRE1", 1)] << 4
                    | _APB_CODE[d.get("D2PPRE2", 1)] << 8)
        p.write_reg("RCC", "D3CFGR", _APB_CODE[d.get("D3PPRE", 1)] << 4)
        self._switch(3)
        log.info("SYSCLK <- PLL1 (%s/%d*%d/%d = %.6g Hz), VOS%d, flash %d WS, "
                 "prescalers %s", cfg.pll_src, m, n, pp, exp["SYSCLK"], cfg.vos, lat, cfg.div)
        if lat < p.read_field("FLASH", "ACR", "LATENCY"):
            self._flash(lat, wrh)

    # ── Internos ──────────────────────────────────────────────────────────

    def _supply_and_vos(self, cfg: ClockConfig) -> None:
        p = self.pal
        if p.read_field("PWR", "CR3", "SCUEN"):
            # Alimentação ainda não travada (sem firmware): grava a do projeto (só LDO)
            if cfg.supply != "LDO_SUPPLY":
                raise ClockError(f"alimentação {cfg.supply} não suportada pelo testador")
            p.write_reg("PWR", "CR3", 1 << 1)                       # LDOEN; trava até o POR
            self._wait(lambda: p.read_field("PWR", "CSR1", "ACTVOSRDY"), 0.1,
                       "regulador não ficou pronto (ACTVOSRDY=0)")
        if cfg.vos not in _VOS_CODE:
            raise ClockError(f"VOS{cfg.vos} não suportado pelo testador (use VOS1 a VOS3)")
        p.modify_field("PWR", "D3CR", "VOS", _VOS_CODE[cfg.vos])
        self._wait(lambda: p.read_field("PWR", "D3CR", "VOSRDY"), 0.1,
                   "escala de tensão não ficou pronta (VOSRDY=0)")
        self.vos = cfg.vos

    def _flash(self, lat: int, wrh: int) -> None:
        p = self.pal
        p.modify_field("FLASH", "ACR", "LATENCY", lat)
        p.modify_field("FLASH", "ACR", "WRHIGHFREQ", wrh)
        if p.read_field("FLASH", "ACR", "LATENCY") != lat:
            raise ClockError("latência da flash não foi aceita")

    def _switch(self, sw: int) -> None:
        p = self.pal
        p.modify_field("RCC", "CFGR", "SW", sw)
        self._wait(lambda: _bits(p.read_reg("RCC", "CFGR"), 3, 3) == sw, 0.05,
                   f"SYSCLK não trocou de fonte (SWS≠{sw})")

    @staticmethod
    def _wait(cond, timeout_s: float, msg: str) -> None:
        deadline = time.perf_counter() + timeout_s
        while not cond():
            if time.perf_counter() > deadline:
                raise ClockError(msg)
