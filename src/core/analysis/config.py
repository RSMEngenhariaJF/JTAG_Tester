"""Perfis de critérios de análise — importáveis, exportáveis e reutilizáveis.

Um AnalysisConfig é um arquivo JSON que define os limites de aprovação de cada
métrica por nome. Ele é independente do código de teste e pode ser compartilhado
entre projetos ou ajustado por grau de qualidade (industrial, consumidor, protótipo).

Hierarquia:
    AnalysisConfig          — perfil completo (nome, versão, conjunto de métricas)
        MetricConfig        — critérios de uma métrica (limites, tolerância, nominal)

Integração com testes::

    from core.analysis.config import get_active_analysis_config

    ac = get_active_analysis_config()

    # Passa critérios direto para o analyzer
    ms.add(analyze_ber("uart_ber", sent, recv, **ac.limits("uart_ber")))
    ms.add(analyze_voltage("v33", samples, 3.3, **ac.limits("v33")))

    # Ou lê valores individuais
    ber_limit = ac.metric("uart_ber").limit_max   # None se não definido

Integração com ProjectConfig:
    O campo ``project.analysis_config`` guarda o nome do arquivo JSON em
    ``analysis_configs/``. Quando um projeto é ativado, o perfil é carregado
    automaticamente.

Localização padrão dos perfis:
    <raiz>/analysis_configs/*.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_CONFIGS_DIR = Path(__file__).parents[3] / "analysis_configs"


# ── MetricConfig ──────────────────────────────────────────────────────────────

@dataclass
class MetricConfig:
    """Critérios de aprovação para uma métrica específica.

    Atributos:
        limit_min     — valor mínimo aceitável (None = sem limite inferior)
        limit_max     — valor máximo aceitável (None = sem limite superior)
        tolerance_pct — faixa simétrica em % em torno de ``nominal``
                        (sobrepõe limit_min/max se nominal for definido)
        nominal       — valor de referência (usado com tolerance_pct)
        description   — anotação legível para o relatório
        extra         — parâmetros adicionais para funções analyze_* específicas
                        ex: {"limit_max_ms": 5.0} para analyze_delay
    """

    limit_min:     float | None = None
    limit_max:     float | None = None
    tolerance_pct: float | None = None
    nominal:       float | None = None
    description:   str          = ""
    extra:         dict         = field(default_factory=dict)

    # ── Helpers de uso ────────────────────────────────────────────────────────

    def limits_kwargs(self) -> dict:
        """Retorna dict com apenas os parâmetros não-None.

        Compatível como **kwargs com as funções analyze_* padrão::

            ms.add(analyze_ber("uart_ber", sent, recv, **mc.limits_kwargs()))
            ms.add(analyze_voltage("v33", samples, 3.3, **mc.limits_kwargs()))
        """
        kw: dict = {}
        if self.limit_min     is not None: kw["limit_min"]     = self.limit_min
        if self.limit_max     is not None: kw["limit_max"]     = self.limit_max
        if self.tolerance_pct is not None: kw["tolerance_pct"] = self.tolerance_pct
        kw.update(self.extra)
        return kw

    def effective_limits(self, nominal_override: float | None = None) -> tuple[float | None, float | None]:
        """Calcula (limit_min, limit_max) resolvendo tolerance_pct + nominal."""
        nom = nominal_override if nominal_override is not None else self.nominal
        if self.tolerance_pct is not None and nom is not None:
            frac = self.tolerance_pct / 100.0
            return nom * (1 - frac), nom * (1 + frac)
        return self.limit_min, self.limit_max

    def is_empty(self) -> bool:
        return (
            self.limit_min is None
            and self.limit_max is None
            and self.tolerance_pct is None
            and not self.extra
        )

    # ── Serialização ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        d: dict = {}
        if self.limit_min     is not None: d["limit_min"]     = self.limit_min
        if self.limit_max     is not None: d["limit_max"]     = self.limit_max
        if self.tolerance_pct is not None: d["tolerance_pct"] = self.tolerance_pct
        if self.nominal       is not None: d["nominal"]       = self.nominal
        if self.description:               d["description"]   = self.description
        if self.extra:                     d["extra"]         = self.extra
        return d

    @classmethod
    def from_dict(cls, d: dict) -> MetricConfig:
        return cls(
            limit_min     = d.get("limit_min"),
            limit_max     = d.get("limit_max"),
            tolerance_pct = d.get("tolerance_pct"),
            nominal       = d.get("nominal"),
            description   = d.get("description", ""),
            extra         = d.get("extra", {}),
        )


# ── AnalysisConfig ────────────────────────────────────────────────────────────

@dataclass
class AnalysisConfig:
    """Perfil completo de critérios de análise.

    Pode ser importado/exportado como JSON e associado a um ou mais projetos.
    """

    name:        str
    description: str                        = ""
    version:     str                        = "1.0"
    author:      str                        = ""
    metrics:     dict[str, MetricConfig]   = field(default_factory=dict)

    # ── Acesso a métricas ─────────────────────────────────────────────────────

    def metric(self, name: str) -> MetricConfig:
        """Retorna a config da métrica. Se não existir, retorna MetricConfig vazio."""
        return self.metrics.get(name, MetricConfig())

    def match(self, measurement_name: str) -> tuple[str, MetricConfig] | None:
        """Métrica que se aplica à medida: nome exato ou o prefixo mais longo + "_".

        Ex.: o perfil "uart_ber" vale para a medida "uart_ber_115200".
        Métricas vazias (sem limite nem tolerância) são ignoradas.
        """
        cand = [k for k, mc in self.metrics.items() if not mc.is_empty()
                and (measurement_name == k or measurement_name.startswith(k + "_"))]
        if not cand:
            return None
        key = max(cand, key=len)
        return key, self.metrics[key]

    def limits(self, name: str) -> dict:
        """Atalho: kwargs prontos para funções analyze_*."""
        return self.metric(name).limits_kwargs()

    def set_metric(self, name: str, cfg: MetricConfig) -> None:
        self.metrics[name] = cfg

    def remove_metric(self, name: str) -> None:
        self.metrics.pop(name, None)

    def metric_names(self) -> list[str]:
        return sorted(self.metrics.keys())

    # ── Serialização JSON ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "description": self.description,
            "version":     self.version,
            "author":      self.author,
            "metrics":     {k: v.to_dict() for k, v in self.metrics.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> AnalysisConfig:
        return cls(
            name        = d["name"],
            description = d.get("description", ""),
            version     = d.get("version", "1.0"),
            author      = d.get("author", ""),
            metrics     = {
                k: MetricConfig.from_dict(v)
                for k, v in d.get("metrics", {}).items()
            },
        )

    def save(self, path: Path | str) -> Path:
        """Salva o perfil em JSON. Retorna o Path do arquivo."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path | str) -> AnalysisConfig:
        """Carrega um perfil a partir de um arquivo JSON."""
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)


# ── Funções de loader ──────────────────────────────────────────────────────────

def find_configs(directory: Path = _CONFIGS_DIR) -> list[AnalysisConfig]:
    """Carrega todos os perfis *.json do diretório de configurações."""
    if not directory.exists():
        return []
    configs: list[AnalysisConfig] = []
    for path in sorted(directory.glob("*.json")):
        try:
            configs.append(AnalysisConfig.load(path))
        except Exception:
            pass
    return configs


def config_path(filename: str, directory: Path = _CONFIGS_DIR) -> Path:
    """Resolve o caminho absoluto de um arquivo de configuração pelo nome."""
    return directory / filename


# ── Singleton ──────────────────────────────────────────────────────────────────

_active_config: AnalysisConfig | None = None


def get_active_analysis_config() -> AnalysisConfig | None:
    """Retorna o perfil de análise ativo ou None se nenhum foi carregado."""
    return _active_config


def set_active_analysis_config(cfg: AnalysisConfig | None) -> None:
    global _active_config
    _active_config = cfg


def active_limits(metric_name: str) -> dict:
    """Atalho: retorna os kwargs do perfil ativo para uma métrica.

    Retorna dict vazio se nenhum perfil ativo ou métrica não definida::

        ms.add(analyze_ber("uart_ber", sent, recv, **active_limits("uart_ber")))
    """
    cfg = _active_config
    return cfg.limits(metric_name) if cfg else {}
