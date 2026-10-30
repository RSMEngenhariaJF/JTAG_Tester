"""Textos de critérios para os relatórios (HTML, Word, PDF) — uma só implementação.

    limits_text(m, fmt)  → "[3,96 MHz … 4,04 MHz]", "≤ 1e-07 err/bit"...
    detail_text(m, fmt)  → "nominal 4 MHz · perfil Industrial v1.0"
    margin_text(m)       → "+42,0 %" / "-3,1 %" / "—"
    criteria_dict(cfg)   → resumo serializável do perfil ativo (vai para o relatório e o JSON)
    criteria_rows(crit)  → linhas [métrica, critério, descrição] da seção "Critérios de análise"
"""

from __future__ import annotations

from collections.abc import Callable

Fmt = Callable[[object, str], str]


def limits_text(m, fmt: Fmt) -> str:
    if m.limit_min is not None and m.limit_max is not None:
        return f"[{fmt(m.limit_min, m.unit)} … {fmt(m.limit_max, m.unit)}]"
    if m.limit_min is not None:
        return f"≥ {fmt(m.limit_min, m.unit)}"
    if m.limit_max is not None:
        return f"≤ {fmt(m.limit_max, m.unit)}"
    return ""


def detail_text(m, fmt: Fmt) -> str:
    parts = []
    if getattr(m, "nominal", None) is not None:
        parts.append(f"nominal {fmt(m.nominal, m.unit)}")
    if getattr(m, "limit_source", ""):
        parts.append(m.limit_source)
    return " · ".join(parts)


def margin_text(m) -> str:
    margin = getattr(m, "margin_pct", None)
    if margin is None:
        return "—"
    sign = "+" if margin >= 0 else "-"
    return f"{sign}{abs(margin):.1f} %".replace(".", ",")


def criteria_dict(cfg) -> dict | None:
    """Resumo do perfil (AnalysisConfig) para o relatório; None se não houver perfil."""
    if cfg is None:
        return None
    return {
        "name": cfg.name,
        "version": cfg.version,
        "description": cfg.description,
        "metrics": {k: mc.to_dict() for k, mc in sorted(cfg.metrics.items())},
    }


def _criterion(d: dict) -> str:
    tol, nom = d.get("tolerance_pct"), d.get("nominal")
    lo, hi = d.get("limit_min"), d.get("limit_max")
    if tol is not None:
        base = f"{nom:g}" if nom is not None else "nominal do teste"
        return f"± {tol:g} % de {base}"
    if lo is not None and hi is not None:
        return f"[{lo:g} … {hi:g}]"
    if lo is not None:
        return f"≥ {lo:g}"
    if hi is not None:
        return f"≤ {hi:g}"
    return "—"


def criteria_title(crit: dict | None) -> str:
    if not crit:
        return ("Nenhum perfil de critérios ativo: valem os limites padrão escritos em "
                "cada teste.")
    title = f"Perfil {crit['name']} v{crit['version']}"
    if crit.get("description"):
        title += f" — {crit['description']}"
    return title


def criteria_rows(crit: dict | None) -> list[list[str]]:
    if not crit:
        return []
    return [[name, _criterion(d), d.get("description", "")]
            for name, d in crit.get("metrics", {}).items()]
