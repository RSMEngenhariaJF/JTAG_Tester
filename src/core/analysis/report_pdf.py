"""Exportador de relatório em PDF via PyMuPDF (fitz.Story).

Gera um PDF A4 a partir de HTML simplificado usando a API fitz.Story,
que suporta um subconjunto de HTML4/CSS2. Nenhuma dependência de
navegador ou driver externo é necessária.

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
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

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
"""


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
    ) -> None:
        self.title        = title
        self.project_name = project_name
        self.project_code = project_code
        self.board_name   = board_name
        self.operator     = operator
        self.notes        = notes

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
            self._results_table(results),
        ]

        tests_with_ms = [r for r in results if getattr(r, "measurements", None)]
        if tests_with_ms:
            parts.append(self._measurements_section(tests_with_ms))

        parts.append(self._footer(now))
        parts.append("</body></html>")
        return "\n".join(parts)

    def save(self, path: Path | str, results: list) -> Path:
        """Gera e salva o relatório PDF. Retorna o Path salvo."""
        try:
            import fitz
        except ImportError:
            raise RuntimeError(
                "PyMuPDF não encontrado — instale com: pip install PyMuPDF"
            )

        path   = Path(path)
        html   = self.build_html(results)
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

            lim_str = ""
            if m.limit_min is not None and m.limit_max is not None:
                lim_str = f"[{_fmt(m.limit_min, m.unit)} … {_fmt(m.limit_max, m.unit)}]"
            elif m.limit_min is not None:
                lim_str = f"≥ {_fmt(m.limit_min, m.unit)}"
            elif m.limit_max is not None:
                lim_str = f"≤ {_fmt(m.limit_max, m.unit)}"

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
                f"<td style='width:22%'>{_esc(m.name)}{desc}</td>"
                f"<td style='width:18%'><b>{_esc(_fmt(m.value, m.unit))}</b></td>"
                f"<td style='width:22%' class='small'>{_esc(lim_str)}</td>"
                f"<td style='width:28%' class='small'>{_esc(stats_str)}</td>"
                f"<td class='c s-{m_stat}' style='width:10%'>{m_stat}</td>"
                "</tr>"
            )

        return (
            f'<h3><span class="s-{status}" style="padding:1pt 4pt;">{status}</span>'
            f'&nbsp; {_esc(result.name)}</h3>\n'
            "<table>"
            "<tr>"
            "<th style='width:22%'>Métrica</th>"
            "<th style='width:18%'>Valor</th>"
            "<th style='width:22%'>Limites</th>"
            "<th style='width:28%'>Estatísticas</th>"
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
