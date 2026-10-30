"""Gerador de relatório HTML auto-contido para resultados de testes.

O relatório produzido é um arquivo .html standalone — nenhuma dependência
externa (CDN, imagens) é necessária para abri-lo.

Uso::

    from core.analysis.report import HtmlReport

    report = HtmlReport(
        title="Relatório de Testes — Sensor Gateway v1",
        project_name="Sensor Gateway v1",
        project_code="SGW-001",
        board_name="NUCLEO-F446RE",
    )
    html = report.generate(results)          # str com o HTML completo
    report.save(Path("relatorio.html"), results)   # salva em disco
"""

from __future__ import annotations

import html as html_lib
import math
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from core.analysis.audit import environment_rows, test_blocks
from core.analysis.criteria_report import (
    criteria_rows,
    criteria_title,
    detail_text,
    limits_text,
    margin_text,
)

if TYPE_CHECKING:
    from tests_builtin.base import TestResult


# ── CSS embutido ──────────────────────────────────────────────────────────────

_CSS = """\
:root{--pass:#22c55e;--fail:#ef4444;--error:#f97316;--skip:#94a3b8;
      --info:#3b82f6;--bg:#0f172a;--surface:#1e293b;--border:#334155;
      --text:#e2e8f0;--muted:#94a3b8;--mono:'Courier New',monospace;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:system-ui,sans-serif;
     font-size:14px;line-height:1.6;padding:24px;}
h1{font-size:1.6rem;font-weight:700;margin-bottom:4px;}
h2{font-size:1.1rem;font-weight:600;margin:24px 0 12px;color:var(--muted);
   text-transform:uppercase;letter-spacing:.05em;}
h3{font-size:.95rem;font-weight:600;margin:16px 0 8px;}
.meta{color:var(--muted);font-size:.85rem;margin-bottom:24px;}
.meta span{margin-right:24px;}
.card{background:var(--surface);border:1px solid var(--border);
      border-radius:8px;padding:16px;margin-bottom:16px;}

/* Summary badges */
.badges{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px;}
.badge{border-radius:6px;padding:10px 20px;font-size:1.1rem;font-weight:700;
       display:flex;flex-direction:column;align-items:center;min-width:80px;}
.badge small{font-size:.75rem;font-weight:400;margin-top:2px;}
.b-pass{background:rgba(34,197,94,.15);border:1px solid var(--pass);color:var(--pass);}
.b-fail{background:rgba(239,68,68,.15);border:1px solid var(--fail);color:var(--fail);}
.b-error{background:rgba(249,115,22,.15);border:1px solid var(--error);color:var(--error);}
.b-skip{background:rgba(148,163,184,.1);border:1px solid var(--skip);color:var(--skip);}
.yield-bar{background:var(--border);border-radius:99px;height:8px;
           margin:8px 0 4px;overflow:hidden;}
.yield-fill{height:100%;border-radius:99px;background:var(--pass);transition:width .4s;}
.yield-lbl{font-size:.85rem;color:var(--muted);}

/* Results table */
table{width:100%;border-collapse:collapse;}
th{text-align:left;padding:8px 12px;border-bottom:1px solid var(--border);
   color:var(--muted);font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;}
td{padding:8px 12px;border-bottom:1px solid rgba(255,255,255,.04);vertical-align:top;}
tr:last-child td{border-bottom:none;}
tr:hover td{background:rgba(255,255,255,.03);}
.status{font-weight:700;font-size:.8rem;font-family:var(--mono);
        white-space:nowrap;}
.s-PASS{color:var(--pass);} .s-FAIL{color:var(--fail);}
.s-ERROR{color:var(--error);} .s-SKIP{color:var(--skip);}
.dur{color:var(--muted);font-size:.8rem;font-family:var(--mono);}
.msg{font-size:.85rem;color:var(--text);}
.muted{color:var(--muted);}
.mono{font-family:var(--mono);font-size:.8rem;}

/* Measurement table */
.m-table{width:100%;border-collapse:collapse;margin-top:8px;font-size:.82rem;}
.m-table th{font-size:.75rem;padding:4px 10px;}
.m-table td{padding:4px 10px;}
.m-pass{color:var(--pass);font-weight:600;}
.m-fail{color:var(--fail);font-weight:600;}
.m-info{color:var(--info);}

/* Sparkbar */
.spark{display:flex;align-items:flex-end;gap:1px;height:32px;
       margin-top:4px;padding:0 2px;}
.spark-bar{background:var(--info);border-radius:2px 2px 0 0;min-height:2px;flex:1;}
.spark-bar.fail{background:var(--fail);}
.limit-line{border-top:1px dashed var(--fail);margin-top:2px;font-size:.7rem;
            color:var(--fail);text-align:right;}

/* Registro de auditoria */
.kv td:first-child{color:var(--muted);width:190px;white-space:nowrap;}
.audit h4{font-size:.8rem;color:var(--muted);text-transform:uppercase;
          letter-spacing:.04em;margin:14px 0 4px;}
.audit table{font-size:.8rem;} .audit td{padding:3px 8px;}
pre.log{background:#0b1220;border:1px solid var(--border);border-radius:6px;padding:8px;
        font-family:var(--mono);font-size:.72rem;white-space:pre-wrap;max-height:420px;
        overflow:auto;color:#cbd5e1;}
footer{margin-top:32px;border-top:1px solid var(--border);padding-top:12px;
       color:var(--muted);font-size:.75rem;text-align:center;}
"""

# ── Helpers de formatação ──────────────────────────────────────────────────────

def _fmt(value: object, unit: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if abs(value) >= 1e6:
            return f"{value:.3e} {unit}".strip()
        if abs(value) < 0.001:
            return f"{value:.3e} {unit}".strip()
        return f"{value:.4f} {unit}".strip()
    return f"{value} {unit}".strip()


_INSTR_COLS = (
    "Nome", "Fabricante / modelo", "Nº de série", "Firmware", "Patrimônio", "Calibração",
)


def _instrument_rows(instruments: list[dict]) -> list[list[str]]:
    """Linhas da tabela de rastreabilidade (uma por instrumento)."""
    rows = []
    for d in instruments:
        cal = d.get("calibration", "")
        if d.get("calibration_due"):
            cal = f"{d['calibration_due']} ({cal})"
        rows.append([
            d.get("name", ""),
            f"{d.get('manufacturer', '')} {d.get('model', '')}".strip() or "—",
            d.get("serial", "") or "—",
            d.get("firmware", "") or "—",
            d.get("asset_id", "") or "—",
            cal or "—",
        ])
    return rows


def _params_text(result) -> str:
    """Parâmetros do plano de testes usados nesta execução (rastreabilidade)."""
    params = getattr(result, "params", None) or {}
    return " · ".join(f"{k}: {v}" for k, v in params.items())


def _params_html(result) -> str:
    txt = _params_text(result)
    return f'<br><span class="mono muted" style="font-size:.75rem">{_esc(txt)}</span>' if txt else ""


def _esc(text: str) -> str:
    return html_lib.escape(str(text))


def _width(block, i: int) -> str:
    return f" style='width:{block.widths[i]}%'" if i < len(block.widths) else ""


def _audit_cell(text: str) -> str:
    if text in ("PASS", "FAIL", "ERROR", "SKIP", "INFO"):
        return f'<td><span class="status s-{text}">{text}</span></td>'
    return f'<td class="mono">{_esc(text)}</td>'


def _sparkbar(samples: list[float], limit_max: float | None) -> str:
    if not samples:
        return ""
    max_v = max(abs(s) for s in samples) or 1
    bars = []
    for s in samples[:80]:
        pct = abs(s) / max_v * 100
        fail = limit_max is not None and abs(s) > limit_max
        bars.append(
            f'<div class="spark-bar{"  fail" if fail else ""}" '
            f'style="height:{max(2,pct):.1f}%" title="{s:.4g}"></div>'
        )
    return f'<div class="spark">{"".join(bars)}</div>'


# ── Gerador de relatório ───────────────────────────────────────────────────────

class HtmlReport:
    """Gerador de relatório HTML para resultados de BuiltinTest / TestResult.

    Parâmetros:
        title        — título exibido no topo do relatório
        project_name — nome legível do projeto
        project_code — código do projeto (ex: SGW-001)
        board_name   — nome da placa (ex: NUCLEO-F446RE)
        operator     — nome do operador (opcional)
        notes        — observações gerais (opcional)
    """

    def __init__(
        self,
        title: str = "Relatório de Testes",
        *,
        project_name: str = "",
        project_code: str = "",
        board_name:   str = "",
        operator:     str = "",
        notes:        str = "",
        instruments:  list[dict] | None = None,
        criteria:     dict | None = None,
        environment:  dict | None = None,
    ) -> None:
        self.title        = title
        self.project_name = project_name
        self.project_code = project_code
        self.board_name   = board_name
        self.operator     = operator
        self.notes        = notes
        self.instruments  = instruments or []   # TraceRecord.to_dict() de cada instrumento
        self.criteria     = criteria                # criteria_report.criteria_dict(perfil)
        self.environment  = environment or {}       # ambiente da execução (audit.environment_rows)

    # ── Público ──────────────────────────────────────────────────────────────

    def generate(self, results: list) -> str:
        """Gera o HTML completo e retorna como string."""
        now = datetime.now()
        n_pass  = sum(1 for r in results if r.status.value == "PASS")
        n_fail  = sum(1 for r in results if r.status.value == "FAIL")
        n_error = sum(1 for r in results if r.status.value == "ERROR")
        n_skip  = sum(1 for r in results if r.status.value == "SKIP")
        total   = len(results)
        yield_pct = n_pass / (total - n_skip) * 100 if (total - n_skip) > 0 else 0.0

        head = self._head()
        header = self._header(now, n_pass, n_fail, n_error, n_skip, yield_pct)
        table  = self._results_table(results)
        measurements = self._measurements_section(results)
        instruments  = self._instruments_section()
        criteria     = self._criteria_section()
        environment  = self._environment_section()
        audit        = self._audit_section(results)
        footer = self._footer(now)

        return (
            "<!DOCTYPE html><html lang=\"pt-BR\">\n"
            + head
            + "<body>\n"
            + header
            + environment
            + table
            + measurements
            + audit
            + criteria
            + instruments
            + footer
            + "\n</body></html>"
        )

    def save(self, path: Path | str, results: list) -> Path:
        """Gera e salva o relatório em ``path``.  Retorna o Path salvo."""
        path = Path(path)
        path.write_text(self.generate(results), encoding="utf-8")
        return path

    # ── Partes do HTML ────────────────────────────────────────────────────────

    def _head(self) -> str:
        return (
            f"<head>\n"
            f'<meta charset="UTF-8">\n'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f"<title>{_esc(self.title)}</title>\n"
            f"<style>{_CSS}</style>\n"
            f"</head>\n"
        )

    def _header(self, now: datetime, n_pass: int, n_fail: int,
                n_error: int, n_skip: int, yield_pct: float) -> str:
        meta_parts = []
        if self.project_name:
            meta_parts.append(f"<span>Projeto: <b>{_esc(self.project_name)}</b></span>")
        if self.project_code:
            meta_parts.append(f"<span>Código: <b>{_esc(self.project_code)}</b></span>")
        if self.board_name:
            meta_parts.append(f"<span>Placa: <b>{_esc(self.board_name)}</b></span>")
        if self.operator:
            meta_parts.append(f"<span>Operador: <b>{_esc(self.operator)}</b></span>")
        meta_parts.append(f"<span>Data: <b>{now.strftime('%d/%m/%Y %H:%M:%S')}</b></span>")

        total_counted = n_pass + n_fail + n_error
        fill = f"{yield_pct:.1f}" if total_counted > 0 else "0"
        yield_color = "var(--pass)" if yield_pct >= 90 else (
            "var(--error)" if yield_pct >= 70 else "var(--fail)"
        )

        notes_html = f'<p class="muted" style="margin-top:8px">{_esc(self.notes)}</p>' if self.notes else ""

        return (
            f"<h1>{_esc(self.title)}</h1>\n"
            f'<p class="meta">{"".join(meta_parts)}</p>\n'
            f'<div class="card">\n'
            f'  <div class="badges">\n'
            f'    <div class="badge b-pass">{n_pass}<small>PASS</small></div>\n'
            f'    <div class="badge b-fail">{n_fail}<small>FAIL</small></div>\n'
            f'    <div class="badge b-error">{n_error}<small>ERROR</small></div>\n'
            f'    <div class="badge b-skip">{n_skip}<small>SKIP</small></div>\n'
            f'  </div>\n'
            f'  <div class="yield-bar"><div class="yield-fill" '
            f'style="width:{fill}%;background:{yield_color}"></div></div>\n'
            f'  <span class="yield-lbl">Yield: <b style="color:{yield_color}">'
            f'{fill}%</b></span>\n'
            f"{notes_html}\n"
            f"</div>\n"
        )

    def _environment_section(self) -> str:
        rows = environment_rows(self.environment)
        if not rows:
            return ""
        body = "".join(f'<tr><td>{_esc(k)}</td><td class="mono">{_esc(v)}</td></tr>\n'
                       for k, v in rows)
        return ("<h2>Ambiente da execução</h2>\n"
                f'<div class="card" style="padding:0"><table class="kv">{body}</table></div>\n')

    def _audit_section(self, results: list) -> str:
        cards = [self._audit_card(r) for r in results if r.details or r.params]
        if not cards:
            return ""
        return ("<h2>Registro de execução por teste</h2>\n"
                '<p class="muted" style="margin-bottom:8px">Identificação do código, '
                "parâmetros, decisões, passos aplicados/observados, log e exceções de cada "
                "teste, para auditoria e rastreabilidade.</p>\n" + "".join(cards))

    @staticmethod
    def _audit_card(result) -> str:
        status = result.status.value
        parts = [f'<div class="card audit">\n<h3><span class="status s-{status}">{status}'
                 f"</span> {_esc(result.name)}</h3>\n"]
        for b in test_blocks(result):
            parts.append(f"<h4>{_esc(b.title)}</h4>\n")
            if b.kind == "pre":
                parts.append(f'<pre class="log">{_esc(b.text)}</pre>\n')
            elif b.kind == "kv":
                parts.append('<table class="kv">' + "".join(
                    f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>" for k, v in b.rows)
                    + "</table>\n")
            else:
                head = "".join(f"<th{_width(b, i)}>{_esc(h)}</th>"
                               for i, h in enumerate(b.headers))
                body = "".join("<tr>" + "".join(_audit_cell(c) for c in row) + "</tr>"
                               for row in b.rows)
                parts.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}"
                             "</tbody></table>\n")
        parts.append("</div>\n")
        return "".join(parts)

    def _criteria_section(self) -> str:
        rows = "".join(
            "<tr>" + "".join(f'<td class="msg">{_esc(c)}</td>' for c in row) + "</tr>\n"
            for row in criteria_rows(self.criteria)
        )
        table = (
            '<div class="card" style="padding:0;overflow:auto">\n<table>\n'
            "<thead><tr><th>Métrica</th><th>Critério</th><th>Descrição</th></tr></thead>\n"
            f"<tbody>\n{rows}</tbody>\n</table>\n</div>\n"
        ) if rows else ""
        return (
            "<h2>Critérios de análise</h2>\n"
            f'<p class="muted">{_esc(criteria_title(self.criteria))}</p>\n' + table
        )

    def _instruments_section(self) -> str:
        if not self.instruments:
            return ""
        head = "".join(f"<th>{h}</th>" for h in _INSTR_COLS)
        body = "".join(
            "<tr>" + "".join(f'<td class="msg">{_esc(c)}</td>' for c in row) + "</tr>\n"
            for row in _instrument_rows(self.instruments)
        )
        return (
            "<h2>Instrumentos utilizados</h2>\n"
            '<div class="card" style="padding:0;overflow:auto">\n'
            f"<table>\n<thead><tr>{head}</tr></thead>\n<tbody>\n{body}</tbody>\n</table>\n"
            "</div>\n"
        )

    def _results_table(self, results: list) -> str:
        rows = []
        for r in results:
            status = r.status.value
            dur = f"{r.duration_ms:.1f} ms" if r.duration_ms else "—"
            measured_str = _esc(str(r.measured)) if r.measured is not None else ""
            expected_str = _esc(str(r.expected)) if r.expected is not None else ""
            comp = ""
            if measured_str or expected_str:
                comp = (
                    f'<br><span class="mono muted">medido: {measured_str}'
                    + (f" | esperado: {expected_str}" if expected_str else "")
                    + "</span>"
                )
            rows.append(
                f"<tr>\n"
                f'  <td><span class="status s-{status}">{status}</span></td>\n'
                f'  <td class="msg">{_esc(r.name)}{comp}</td>\n'
                f'  <td class="msg muted">{_esc(r.message)}</td>\n'
                f'  <td class="dur">{dur}</td>\n'
                f"</tr>\n"
            )

        return (
            "<h2>Resultados</h2>\n"
            '<div class="card" style="padding:0;overflow:auto">\n'
            "<table>\n"
            "<thead><tr>"
            "<th style='width:70px'>Status</th>"
            "<th>Teste</th>"
            "<th>Mensagem</th>"
            "<th style='width:80px'>Tempo</th>"
            "</tr></thead>\n"
            "<tbody>" + "".join(rows) + "</tbody>\n"
            "</table></div>\n"
        )

    def _measurements_section(self, results: list) -> str:
        # Filtra testes que têm medições
        tests_with_ms = [
            r for r in results
            if hasattr(r, "measurements") and r.measurements
        ]
        if not tests_with_ms:
            return ""

        sections = ["<h2>Análise de Métricas</h2>\n"]
        for r in tests_with_ms:
            sections.append(self._measurement_card(r))
        return "".join(sections)

    def _measurement_card(self, result) -> str:
        status = result.status.value
        ms = result.measurements

        rows = []
        for m in ms:
            wl = m.within_limits
            status_cls = "m-info" if wl is None else ("m-pass" if wl else "m-fail")
            status_lbl = "INFO" if wl is None else ("PASS" if wl else "FAIL")

            lim_str = limits_text(m, _fmt)
            det_str = detail_text(m, _fmt)
            mrg_str = margin_text(m)

            stats_html = ""
            if m.samples:
                spark = _sparkbar(m.samples, m.limit_max)
                if len(m.samples) >= 2:
                    stats_html = (
                        f'<td class="mono muted">'
                        f"µ={_fmt(m.mean, m.unit)} σ={_fmt(m.std_dev, m.unit)}"
                        f"<br>min={_fmt(m.minimum, m.unit)} max={_fmt(m.maximum, m.unit)}"
                        f"{spark}</td>"
                    )
                else:
                    stats_html = "<td>—</td>"
            else:
                stats_html = "<td>—</td>"

            desc = f'<br><span class="muted" style="font-size:.8rem">{_esc(m.description)}</span>' if m.description else ""
            rows.append(
                f"<tr>"
                f'<td class="mono">{_esc(m.name)}{desc}</td>'
                f'<td class="mono"><b>{_fmt(m.value, m.unit)}</b></td>'
                f'<td class="mono muted">{lim_str}'
                + (f'<br><span style="font-size:.75rem">{_esc(det_str)}</span>' if det_str else "")
                + "</td>"
                f"{stats_html}"
                f'<td class="mono">{mrg_str}</td>'
                f'<td><span class="{status_cls}" style="font-weight:700;font-size:.8rem">{status_lbl}</span></td>'
                f"</tr>\n"
            )

        return (
            f'<div class="card">\n'
            f'<h3><span class="status s-{status}">{status}</span> '
            f'{_esc(result.name)}</h3>\n'
            f'<table class="m-table">\n'
            f"<thead><tr>"
            f"<th>Métrica</th><th>Valor</th><th>Limites</th>"
            f"<th>Estatísticas / Histograma</th><th>Margem</th><th>Status</th>"
            f"</tr></thead>\n"
            f"<tbody>{''.join(rows)}</tbody>\n"
            f"</table>\n"
            f"</div>\n"
        )

    def _footer(self, now: datetime) -> str:
        return (
            "<footer>\n"
            f"Gerado em {now.strftime('%d/%m/%Y %H:%M:%S')} · "
            "JTAG Tester — Sistema de Testes de Hardware\n"
            "</footer>\n"
        )
