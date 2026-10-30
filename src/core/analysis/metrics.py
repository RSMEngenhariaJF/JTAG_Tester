"""Métricas de análise de testes de hardware.

Measurement  — uma grandeza medida com amostras e limites configuráveis.
MeasurementSet — coleção de medições associada a um TestResult.

Exemplo de uso::

    from core.analysis.metrics import Measurement, MeasurementSet

    ms = MeasurementSet()
    ms.add(Measurement(
        name="uart_ber",
        value=2.5e-6,
        unit="err/bit",
        samples=[0.0, 1.0, 0.0, 0.0],  # bits errados por bloco
        limit_max=1e-5,
        description="Taxa de erro de bit USART2 a 115200 bps",
    ))

    for m in ms:
        print(m.name, m.value, m.status)   # "uart_ber", 2.5e-6, "PASS"
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field


@dataclass
class Measurement:
    """Uma grandeza medida com estatísticas e critérios de aprovação.

    Parâmetros:
        name        — identificador da medição (ex: "uart_ber", "v_3v3_ripple")
        value       — valor principal (escalar ou média das amostras)
        unit        — unidade da grandeza ("V", "Hz", "s", "dB", "err/bit", "%")
        samples     — lista de amostras brutas (opcional; permite estatísticas)
        limit_min   — limite inferior de aprovação (None = sem limite)
        limit_max   — limite superior de aprovação (None = sem limite)
        description — descrição legível para o relatório
        nominal     — valor esperado (para relatório e para tolerância % do perfil)
        limit_source — de onde vieram os limites: "perfil <nome> v<versão>" ou
                       "padrão do teste" (preenchido por MeasurementSet.add)
    """

    name:        str
    value:       float
    unit:        str            = ""
    samples:     list[float]   = field(default_factory=list)
    limit_min:   float | None  = None
    limit_max:   float | None  = None
    description: str           = ""
    nominal:     float | None  = None
    limit_source: str          = ""

    # ── Estatísticas ──────────────────────────────────────────────────────

    @property
    def mean(self) -> float:
        return statistics.mean(self.samples) if len(self.samples) >= 2 else self.value

    @property
    def std_dev(self) -> float:
        return statistics.stdev(self.samples) if len(self.samples) >= 2 else 0.0

    @property
    def minimum(self) -> float:
        return min(self.samples) if self.samples else self.value

    @property
    def maximum(self) -> float:
        return max(self.samples) if self.samples else self.value

    @property
    def p05(self) -> float:
        """5º percentil (valor abaixo do qual caem 5% das amostras)."""
        if len(self.samples) < 2:
            return self.value
        s = sorted(self.samples)
        k = (len(s) - 1) * 0.05
        lo, hi = int(k), min(int(k) + 1, len(s) - 1)
        return s[lo] + (k - lo) * (s[hi] - s[lo])

    @property
    def p95(self) -> float:
        """95º percentil."""
        if len(self.samples) < 2:
            return self.value
        s = sorted(self.samples)
        k = (len(s) - 1) * 0.95
        lo, hi = int(k), min(int(k) + 1, len(s) - 1)
        return s[lo] + (k - lo) * (s[hi] - s[lo])

    # ── Aprovação ─────────────────────────────────────────────────────────

    @property
    def within_limits(self) -> bool | None:
        """True = aprovado, False = reprovado, None = sem limites definidos."""
        if self.limit_min is None and self.limit_max is None:
            return None
        ok = True
        if self.limit_min is not None:
            ok = ok and self.value >= self.limit_min
        if self.limit_max is not None:
            ok = ok and self.value <= self.limit_max
        return ok

    @property
    def margin_pct(self) -> float | None:
        """Folga até o limite mais próximo, em % (negativa = fora do limite).

        Com os dois limites: % da faixa (limit_max - limit_min) que ainda sobra
        até a borda mais próxima. Com um só: % do valor do limite. None quando
        não há limite ou ele é zero (ex.: BER ≤ 0).
        """
        lo, hi, v = self.limit_min, self.limit_max, self.value
        if lo is not None and hi is not None:
            band = hi - lo
            return min(v - lo, hi - v) / band * 100 if band > 0 else None
        if hi is not None:
            return (hi - v) / abs(hi) * 100 if hi else None
        if lo is not None:
            return (v - lo) / abs(lo) * 100 if lo else None
        return None

    @property
    def status(self) -> str:
        wl = self.within_limits
        if wl is None:
            return "INFO"
        return "PASS" if wl else "FAIL"

    # ── Serialização ──────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        d: dict = {
            "name":   self.name,
            "value":  self.value,
            "unit":   self.unit,
            "status": self.status,
        }
        if self.description:
            d["description"] = self.description
        if self.samples:
            d["stats"] = {
                "n":       len(self.samples),
                "mean":    round(self.mean,    6),
                "std_dev": round(self.std_dev, 6),
                "min":     round(self.minimum, 6),
                "max":     round(self.maximum, 6),
                "p05":     round(self.p05,     6),
                "p95":     round(self.p95,     6),
            }
        if self.limit_min is not None:
            d["limit_min"] = self.limit_min
        if self.limit_max is not None:
            d["limit_max"] = self.limit_max
        if self.nominal is not None:
            d["nominal"] = self.nominal
        if self.limit_source:
            d["limit_source"] = self.limit_source
        if (margin := self.margin_pct) is not None:
            d["margin_pct"] = round(margin, 3)
        return d


class MeasurementSet:
    """Coleção ordenada de Measurements associadas a um teste.

    Exemplo::

        ms = MeasurementSet()
        ms.add(analyze_ber("uart_ber", sent, received, limit_max=1e-5))
        ms.add(analyze_voltage("v_3v3", samples, 3.3, tolerance_pct=3.0))

        if not ms.all_within_limits():
            return self._fail("Métricas fora dos limites", measurements=ms)
    """

    def __init__(self) -> None:
        self._items: list[Measurement] = []

    def add(self, m: Measurement) -> None:
        """Acrescenta a medida aplicando o perfil de critérios ativo (o perfil vence)."""
        apply_criteria(m)
        self._items.append(m)

    def get(self, name: str) -> Measurement | None:
        for m in self._items:
            if m.name == name:
                return m
        return None

    def all_within_limits(self) -> bool:
        """True se todas as métricas com limites estão aprovadas."""
        for m in self._items:
            wl = m.within_limits
            if wl is False:
                return False
        return True

    def any_fail(self) -> bool:
        return not self.all_within_limits()

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    def to_dict(self) -> dict:
        return {
            "measurements": [m.to_dict() for m in self._items],
            "all_pass": self.all_within_limits(),
        }


SOURCE_DEFAULT = "padrão do teste"


def apply_criteria(m: Measurement, cfg=None) -> Measurement:
    """Aplica à medida os limites do perfil de critérios (ativo ou `cfg`).

    O perfil vence o limite escrito no teste. A métrica do perfil casa pelo nome
    exato ou como prefixo seguido de "_" ("uart_ber" vale para "uart_ber_9600").
    tolerance_pct do perfil usa o nominal do perfil ou, se ausente, o da medida.
    Sem perfil para a métrica, os limites do teste ficam, marcados como padrão.
    """
    if m.limit_source:
        return m
    if cfg is None:
        from core.analysis.config import get_active_analysis_config
        cfg = get_active_analysis_config()
    match = cfg.match(m.name) if cfg is not None else None
    if match is not None:
        mc = match[1]
        nominal = mc.nominal if mc.nominal is not None else m.nominal
        lo, hi = mc.effective_limits(nominal_override=nominal)
        if lo is not None or hi is not None:
            m.limit_min, m.limit_max = lo, hi
            m.nominal = nominal
            m.limit_source = f"perfil {cfg.name} v{cfg.version}"
            return m
    if m.limit_min is not None or m.limit_max is not None:
        m.limit_source = SOURCE_DEFAULT
    return m
