"""Exportador de relatório em PDF (A4) a partir de HTML simplificado.

Dois motores, escolhidos por ``backend`` em save():
    "qt"   — QTextDocument + QPdfWriter do PySide6 (LGPL, já é dependência da GUI)
    "fitz" — PyMuPDF / fitz.Story (opcional; licença AGPL — avaliar antes de distribuir)
    "auto" — Qt se disponível, senão PyMuPDF (padrão)

Uso::

    from core.analysis.report_pdf import PdfReport

    report = PdfReport(
        title="Relatório — Sensor Gateway v1",
        project_name="Sensor Gateway v1",
        project_code="SGW-001",
        board_name="NUCLEO-F446RE",
    )
    report.save(Path("relatorio.pdf"), results)
"""

from __future__ import annotations

import html as html_lib
import math
import re
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

# ── CSS embarcado para fitz.Story ────────────────────────────────────────────
# A Story API usa um subconjunto de HTML4/CSS2 — sem variáveis CSS nem SVG.

_STORY_CSS = """
body    { font-family: Helvetica, Arial, sans-serif; font-size: 10pt;
          color: #1a1a1a; margin: 0; padding: 0; }
h1      { font-size: 16pt; color: #1F3964; margin-top: 0; margin-bottom: 4pt; }
h2      { font-size: 12pt; color: #1F3964; margin-top: 14pt; margin-bottom: 6pt;
          border-bottom: 1px solid #aaaaaa; padding-bottom: 2pt; }
h3      { font-size: 10pt; color: #1F3964; margin-top: 10pt; margin-bottom: 4pt; }
p       { margin: 2pt 0; }
.meta   { font-size: 8.5pt; color: #555555; margin-bottom: 10pt; }
.sep    { border-top: 1pt solid #cccccc; margin: 8pt 0; }
table   { border-collapse: collapse; width: 100%; margin-bottom: 10pt; }
th      { background-color: #1F3964; color: #ffffff; font-size: 8.5pt;
          font-weight: bold; padding: 4pt 6pt; text-align: left; }
td      { font-size: 9pt; padding: 3pt 6pt;
          border-bottom: 1px solid #dddddd; }
.c      { text-align: center; }
.bold   { font-weight: bold; }
.small  { font-size: 8pt; color: #666666; }
.footer { font-size: 8pt; color: #888888; margin-top: 16pt;
          border-top: 1pt solid #cccccc; padding-top: 6pt; }

/* Status badges */
.s-PASS  { background-color: #C8F0C8; color: #006400; font-weight: bold; }
.s-FAIL  { background-color: #FFB0B0; color: #8B0000; font-weight: bold; }
.s-ERROR { background-color: #FFD080; color: #7B3F00; font-weight: bold; }
.s-SKIP  { background-color: #DCDCDC; color: #505050; font-weight: bold; }
.s-INFO  { background-color: #D0E8FF; color: #003080; font-weight: bold; }

/* Summary boxes */
.sum-box { display: inline-block; padding: 6pt 18pt; margin-right: 8pt;
           text-align: center; border-radius: 4pt; }
.yield-p  { font-size: 11pt; font-weight: bold; margin: 6pt 0; }
.kvk     { color: #555555; width: 24%; }
h4       { font-size: 9pt; color: #1F3964; margin-top: 6pt; margin-bottom: 2pt; }
pre      { font-family: Courier New, monospace; font-size: 7pt; background-color: #F4F4F4;
           border: 1px solid #DDDDDD; padding: 4pt; white-space: pre-wrap; }
"""


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


def _width(block, i: int) -> str:
    return f" style='width:{block.widths[i]}%'" if i < len(block.widths) else ""


def _audit_cell(text: str) -> str:
    if text in ("PASS", "FAIL", "ERROR", "SKIP", "INFO"):
        return f"<td class='c s-{text} small'>{text}</td>"
    return f"<td class='small'>{_esc(text)}</td>"


def _esc(text: str) -> str:
    return html_lib.escape(str(text))


def _fmt(value: object, unit: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if abs(value) < 0.001 or abs(value) >= 1e6:
            return f"{value:.3e} {unit}".strip()
        return f"{value:.4f} {unit}".strip()
    return f"{value} {unit}".strip()


# ── Gerador de HTML para Story ────────────────────────────────────────────────

class PdfReport:
    """Gerador de relatório PDF via PyMuPDF.

    Parâmetros idênticos a HtmlReport e DocxReport.
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

    # ── API pública ───────────────────────────────────────────────────────────

    def build_html(self, results: list) -> str:
        """Gera o HTML simplificado (compatível com fitz.Story)."""
        now = datetime.now()
        n_pass  = sum(1 for r in results if r.status.value == "PASS")
        n_fail  = sum(1 for r in results if r.status.value == "FAIL")
        n_error = sum(1 for r in results if r.status.value == "ERROR")
        n_skip  = sum(1 for r in results if r.status.value == "SKIP")
        total   = len(results)
        counted = n_pass + n_fail + n_error
        yield_pct = n_pass / counted * 100 if counted > 0 else 0.0

        parts = [
            "<html><body>",
            self._header(now),
            self._summary(n_pass, n_fail, n_error, n_skip, total, yield_pct),
            self._environment_section(),
            self._results_table(results),
        ]

        tests_with_ms = [r for r in results if getattr(r, "measurements", None)]
        if tests_with_ms:
            parts.append(self._measurements_section(tests_with_ms))
        parts.append(self._audit_section(results))
        parts.append(self._criteria_section())
        if self.instruments:
            parts.append(self._instruments_section())

        parts.append(self._footer(now))
        parts.append("</body></html>")
        return "\n".join(parts)

    def save(self, path: Path | str, results: list, backend: str = "auto") -> Path:
        """Gera e salva o relatório PDF. Retorna o Path salvo."""
        if backend not in ("auto", "qt", "fitz"):
            raise ValueError(f"backend inválido: {backend}")
        path = Path(path)
        html = self.build_html(results)
        if backend in ("auto", "qt"):
            try:
                return _save_qt(path, html)
            except ImportError:
                if backend == "qt":
                    raise RuntimeError("PySide6 não encontrado — necessário para o PDF") from None
        return _save_fitz(path, html)

    # ── Partes do HTML ────────────────────────────────────────────────────────

    def _header(self, now: datetime) -> str:
        meta_parts = []
        if self.project_name:
            meta_parts.append(f"<b>Projeto:</b> {_esc(self.project_name)}")
        if self.project_code:
            meta_parts.append(f"<b>Código:</b> {_esc(self.project_code)}")
        if self.board_name:
            meta_parts.append(f"<b>Placa:</b> {_esc(self.board_name)}")
        if self.operator:
            meta_parts.append(f"<b>Operador:</b> {_esc(self.operator)}")
        meta_parts.append(f"<b>Data:</b> {now.strftime('%d/%m/%Y %H:%M:%S')}")

        notes_html = f'<p class="small">{_esc(self.notes)}</p>' if self.notes else ""
        return (
            f"<h1>{_esc(self.title)}</h1>\n"
            f'<p class="meta">{"&nbsp;&nbsp;|&nbsp;&nbsp;".join(meta_parts)}</p>\n'
            + notes_html
        )

    def _summary(
        self,
        n_pass: int,
        n_fail: int,
        n_error: int,
        n_skip: int,
        total: int,
        yield_pct: float,
    ) -> str:
        def box(lbl: str, count: int) -> str:
            return (
                f'<td class="c s-{lbl}" style="width:22%;padding:8pt 4pt;">'
                f'<b style="font-size:16pt">{count}</b><br/>'
                f'<span style="font-size:8pt">{lbl}</span></td>'
            )

        return (
            "<h2>Resumo</h2>\n"
            "<table><tr>"
            + box("PASS", n_pass)
            + box("FAIL", n_fail)
            + box("ERROR", n_error)
            + box("SKIP", n_skip)
            + "</tr></table>\n"
            f'<p class="yield-p">Yield: {yield_pct:.1f}% '
            f'<span class="small">({n_pass}/{total} testes aprovados)</span></p>\n'
        )

    def _criteria_section(self) -> str:
        rows = "".join(
            "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in row) + "</tr>"
            for row in criteria_rows(self.criteria)
        )
        table = (
            "<table><tr><th style='width:22%'>Métrica</th><th style='width:22%'>Critério</th>"
            f"<th>Descrição</th></tr>{rows}</table>\n"
        ) if rows else ""
        return (f"<h2>Critérios de análise</h2>\n"
                f"<p class='small'>{_esc(criteria_title(self.criteria))}</p>\n{table}")

    def _instruments_section(self) -> str:
        widths = (8, 24, 17, 13, 15, 23)   # % — soma 100
        head = "".join(
            f"<th style='width:{w}%'>{h}</th>" for h, w in zip(_INSTR_COLS, widths, strict=True)
        )
        body = "".join(
            "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in row) + "</tr>"
            for row in _instrument_rows(self.instruments)
        )
        return f"<h2>Instrumentos utilizados</h2>\n<table><tr>{head}</tr>{body}</table>\n"

    def _results_table(self, results: list) -> str:
        rows = []
        for r in results:
            status = r.status.value
            dur    = f"{r.duration_ms:.1f} ms" if r.duration_ms else "—"
            rows.append(
                f'<tr class="s-{status}">'
                f'<td class="c s-{status}" style="width:12%">{status}</td>'
                f'<td style="width:28%">{_esc(r.name)}</td>'
                f'<td class="c" style="width:12%">{_esc(dur)}</td>'
                f'<td>{_esc(r.message)}</td>'
                f"</tr>"
            )

        return (
            "<h2>Resultados por Teste</h2>\n"
            "<table>"
            "<tr>"
            "<th style='width:12%'>Status</th>"
            "<th style='width:28%'>Teste</th>"
            "<th style='width:12%'>Tempo</th>"
            "<th>Mensagem</th>"
            "</tr>"
            + "\n".join(rows)
            + "</table>\n"
        )

    def _environment_section(self) -> str:
        rows = environment_rows(self.environment)
        if not rows:
            return ""
        body = "".join(f"<tr><td class='kvk'>{_esc(k)}</td><td>{_esc(v)}</td></tr>"
                       for k, v in rows)
        return f"<h2>Ambiente da execução</h2>\n<table>{body}</table>\n"

    def _audit_section(self, results: list) -> str:
        items = [r for r in results if r.details or r.params]
        if not items:
            return ""
        parts = ["<h2>Registro de execução por teste</h2>\n"]
        for r in items:
            status = r.status.value
            parts.append(f'<h3><span class="s-{status}" style="padding:1pt 4pt;">{status}'
                         f"</span>&nbsp; {_esc(r.name)}</h3>\n")
            for b in test_blocks(r):
                parts.append(f"<h4>{_esc(b.title)}</h4>\n")
                if b.kind == "pre":
                    parts.append(f"<pre>{_esc(b.text)}</pre>\n")
                elif b.kind == "kv":
                    parts.append("<table>" + "".join(
                        f"<tr><td class='kvk'>{_esc(k)}</td><td>{_esc(v)}</td></tr>"
                        for k, v in b.rows) + "</table>\n")
                else:
                    head = "".join(f"<th{_width(b, i)}>{_esc(h)}</th>"
                                   for i, h in enumerate(b.headers))
                    body = "".join("<tr>" + "".join(_audit_cell(c) for c in row) + "</tr>"
                                   for row in b.rows)
                    parts.append(f"<table><tr>{head}</tr>{body}</table>\n")
        return "".join(parts)

    def _measurements_section(self, results: list) -> str:
        parts = ["<h2>Análise de Métricas</h2>\n"]
        for r in results:
            parts.append(self._measurement_block(r))
        return "".join(parts)

    def _measurement_block(self, result) -> str:
        ms     = result.measurements
        status = result.status.value

        rows = []
        for m in ms:
            wl     = m.within_limits
            m_stat = "INFO" if wl is None else ("PASS" if wl else "FAIL")

            lim_str = limits_text(m, _fmt)
            det_str = detail_text(m, _fmt)
            mrg_str = margin_text(m)

            stats_str = ""
            if len(m.samples) >= 2:
                stats_str = (
                    f"µ={_fmt(m.mean, m.unit)}"
                    f" σ={_fmt(m.std_dev, m.unit)}"
                    f" min={_fmt(m.minimum, m.unit)}"
                    f" max={_fmt(m.maximum, m.unit)}"
                )

            desc = f'<br/><span class="small">{_esc(m.description)}</span>' if m.description else ""

            rows.append(
                "<tr>"
                f"<td style='width:20%'>{_esc(m.name)}{desc}</td>"
                f"<td style='width:15%'><b>{_esc(_fmt(m.value, m.unit))}</b></td>"
                f"<td style='width:24%' class='small'>{_esc(lim_str)}"
                + (f"<br/>{_esc(det_str)}" if det_str else "") + "</td>"
                f"<td style='width:21%' class='small'>{_esc(stats_str)}</td>"
                f"<td style='width:10%' class='c small'>{_esc(mrg_str)}</td>"
                f"<td class='c s-{m_stat}' style='width:10%'>{m_stat}</td>"
                "</tr>"
            )

        return (
            f'<h3><span class="s-{status}" style="padding:1pt 4pt;">{status}</span>'
            f'&nbsp; {_esc(result.name)}</h3>\n'
            "<table>"
            "<tr>"
            "<th style='width:20%'>Métrica</th>"
            "<th style='width:15%'>Valor</th>"
            "<th style='width:24%'>Limites</th>"
            "<th style='width:21%'>Estatísticas</th>"
            "<th style='width:10%'>Margem</th>"
            "<th style='width:10%'>Status</th>"
            "</tr>"
            + "\n".join(rows)
            + "</table>\n"
        )

    def _footer(self, now: datetime) -> str:
        return (
            f'<p class="footer">Gerado em {now.strftime("%d/%m/%Y %H:%M:%S")} · '
            "JTAG Tester — Sistema de Testes de Hardware</p>"
        )


def _save_fitz(path: Path, html: str) -> Path:
    try:
        import fitz
    except ImportError:
        raise RuntimeError(
            "PyMuPDF não encontrado — instale com: pip install PyMuPDF"
        ) from None

    story  = fitz.Story(html=html, user_css=_STORY_CSS)
    writer = fitz.DocumentWriter(str(path))

    # A4: 595 × 842 pt
    mediabox = fitz.paper_rect("a4")
    # Margens: 54 pt (~1.9 cm) laterais, 54 pt topo/base
    where = mediabox + (54, 54, -54, -54)

    more = True
    while more:
        device     = writer.begin_page(mediabox)
        more, _    = story.place(where)
        story.draw(device)
        writer.end_page()

    writer.close()
    return path


_QT_APP = None   # mantém a QGuiApplication criada fora da GUI (scripts/CLI)


def _save_qt(path: Path, html: str) -> Path:
    """Renderiza com QTextDocument (paginação automática) e grava com QPdfWriter."""
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import (
        QGuiApplication,
        QPageLayout,
        QPageSize,
        QPdfWriter,
        QTextDocument,
    )

    global _QT_APP
    if QGuiApplication.instance() is None:
        _QT_APP = QGuiApplication([])

    writer = QPdfWriter(str(path))
    writer.setResolution(96)             # px do HTML (cellpadding, bordas) = px de tela
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(19, 19, 19, 19), QPageLayout.Unit.Millimeter)
    writer.setTitle("Relatório de Testes")
    writer.setCreator("Plataforma de Bring-up")

    # O rich text do Qt ignora width/padding de tabela via CSS: usa atributos HTML.
    html = html.replace("<table>", '<table width="100%" cellspacing="0" cellpadding="5">')
    html = re.sub(r"(<t[hd]\b[^>]*?)style=(['\"])width:(\d+)%;?", r'\1width="\3%" style=\2', html)

    doc = QTextDocument()
    doc.setDefaultStyleSheet(_STORY_CSS)
    doc.setHtml(html)
    doc.print_(writer)
    return path
