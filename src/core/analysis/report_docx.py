"""Exportador de relatório em formato Word (.docx).

Usa python-docx para criar um documento com:
    - Capa com metadados do projeto
    - Tabela de resumo (PASS / FAIL / ERROR / SKIP + yield)
    - Tabela detalhada de resultados com células coloridas por status
    - Seções de métricas por teste (quando measurements estiver preenchido)

Uso::

    from core.analysis.report_docx import DocxReport

    report = DocxReport(
        title="Relatório — Sensor Gateway v1",
        project_name="Sensor Gateway v1",
        project_code="SGW-001",
        board_name="NUCLEO-F446RE",
    )
    report.save(Path("relatorio.docx"), results)
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests_builtin.base import TestResult

# Cores de fundo por status (hex RGB sem '#')
_BG: dict[str, str] = {
    "PASS":  "C8F0C8",
    "FAIL":  "FFB0B0",
    "ERROR": "FFD080",
    "SKIP":  "DCDCDC",
    "INFO":  "D0E8FF",
}

_FG: dict[str, str] = {
    "PASS":  "006400",
    "FAIL":  "8B0000",
    "ERROR": "7B3F00",
    "SKIP":  "505050",
    "INFO":  "003080",
}

_HEADER_BG = "1F3964"   # azul escuro do cabeçalho de tabela
_HEADER_FG = "FFFFFF"


# ── Helpers de XML / formatação ───────────────────────────────────────────────

def _cell_bg(cell, hex_color: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  hex_color)
    tcPr.append(shd)


def _cell_write(
    cell,
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
    fg_hex: str | None = None,
    pt: float = 10.0,
    center: bool = False,
) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    cell.text = ""
    para = cell.paragraphs[0]
    if center:
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run(text)
    run.bold   = bold
    run.italic = italic
    run.font.size = Pt(pt)
    if fg_hex:
        r, g, b = int(fg_hex[0:2], 16), int(fg_hex[2:4], 16), int(fg_hex[4:6], 16)
        run.font.color.rgb = RGBColor(r, g, b)


def _hdr_row(table, *texts: str) -> None:
    row = table.rows[0]
    for i, text in enumerate(texts):
        cell = row.cells[i]
        _cell_bg(cell, _HEADER_BG)
        _cell_write(cell, text, bold=True, fg_hex=_HEADER_FG, pt=9.0)


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


# ── Classe principal ──────────────────────────────────────────────────────────

class DocxReport:
    """Gerador de relatório Word (.docx).

    Parâmetros idênticos a HtmlReport para uso intercambiável.
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

    def generate(self, results: list):
        """Gera e retorna um objeto Document (python-docx)."""
        from docx import Document
        from docx.shared import Cm

        doc = Document()
        for sec in doc.sections:
            sec.left_margin   = Cm(2.5)
            sec.right_margin  = Cm(2.5)
            sec.top_margin    = Cm(2.0)
            sec.bottom_margin = Cm(2.0)

        now = datetime.now()
        self._add_title(doc, now)
        self._add_summary(doc, results, now)
        self._add_results_table(doc, results)

        tests_with_ms = [r for r in results if getattr(r, "measurements", None)]
        if tests_with_ms:
            self._add_measurements_section(doc, tests_with_ms)

        return doc

    def save(self, path: Path | str, results: list) -> Path:
        """Salva o relatório em ``path``. Retorna o Path do arquivo."""
        path = Path(path)
        doc  = self.generate(results)
        doc.save(str(path))
        return path

    # ── Seções ────────────────────────────────────────────────────────────────

    def _add_title(self, doc, now: datetime) -> None:
        from docx.shared import Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        # Título principal
        h = doc.add_heading(self.title, level=0)
        h.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in h.runs:
            run.font.size  = Pt(18)
            run.font.color.rgb = RGBColor(0x1F, 0x39, 0x64)

        # Subtítulo com metadados
        meta_parts = []
        if self.project_name:
            meta_parts.append(f"Projeto: {self.project_name}")
        if self.project_code:
            meta_parts.append(f"Código: {self.project_code}")
        if self.board_name:
            meta_parts.append(f"Placa: {self.board_name}")
        if self.operator:
            meta_parts.append(f"Operador: {self.operator}")
        meta_parts.append(f"Data: {now.strftime('%d/%m/%Y %H:%M:%S')}")

        p = doc.add_paragraph("  |  ".join(meta_parts))
        p.runs[0].font.size = Pt(9)
        p.runs[0].font.color.rgb = RGBColor(0x60, 0x60, 0x60)

        if self.notes:
            n = doc.add_paragraph(self.notes)
            n.runs[0].italic = True
            n.runs[0].font.size = Pt(9)

    def _add_summary(self, doc, results: list, now: datetime) -> None:
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt

        n_pass  = sum(1 for r in results if r.status.value == "PASS")
        n_fail  = sum(1 for r in results if r.status.value == "FAIL")
        n_error = sum(1 for r in results if r.status.value == "ERROR")
        n_skip  = sum(1 for r in results if r.status.value == "SKIP")
        total   = len(results)
        counted = n_pass + n_fail + n_error
        yield_pct = n_pass / counted * 100 if counted > 0 else 0.0

        doc.add_heading("Resumo", level=1)

        # Tabela de contagem: 4 colunas (PASS / FAIL / ERROR / SKIP)
        t = doc.add_table(rows=2, cols=4)
        t.style = "Table Grid"

        labels  = ["PASS", "FAIL", "ERROR", "SKIP"]
        counts_ = [n_pass, n_fail, n_error, n_skip]
        for col_i, (lbl, cnt) in enumerate(zip(labels, counts_)):
            hdr_cell = t.cell(0, col_i)
            _cell_bg(hdr_cell, _BG[lbl])
            _cell_write(hdr_cell, lbl, bold=True, fg_hex=_FG[lbl], pt=9.0, center=True)

            val_cell = t.cell(1, col_i)
            _cell_bg(val_cell, _BG[lbl])
            _cell_write(val_cell, str(cnt), bold=True, fg_hex=_FG[lbl], pt=18.0, center=True)

        doc.add_paragraph()  # espaço

        # Yield
        p = doc.add_paragraph(f"Yield: {yield_pct:.1f}%  ({n_pass}/{total} testes aprovados)")
        p.runs[0].bold = True
        p.runs[0].font.size = Pt(11)

    def _add_results_table(self, doc, results: list) -> None:
        from docx.shared import Cm, Pt

        doc.add_heading("Resultados por Teste", level=1)

        t = doc.add_table(rows=1 + len(results), cols=4)
        t.style = "Table Grid"

        # Larguras aproximadas (soma com as margens = ~16 cm útil)
        widths = [Cm(2.0), Cm(4.5), Cm(2.0), Cm(7.5)]

        _hdr_row(t, "Status", "Teste", "Tempo (ms)", "Mensagem")
        for col_i, w in enumerate(widths):
            t.columns[col_i].width = w

        for row_i, r in enumerate(results, start=1):
            row = t.rows[row_i]
            status = r.status.value
            bg     = _BG.get(status, "FFFFFF")
            fg     = _FG.get(status, "000000")
            dur    = f"{r.duration_ms:.1f}" if r.duration_ms else "—"

            for col_i in range(4):
                _cell_bg(row.cells[col_i], bg)

            _cell_write(row.cells[0], status, bold=True, fg_hex=fg, pt=9.0, center=True)
            _cell_write(row.cells[1], r.name,    pt=9.0)
            _cell_write(row.cells[2], dur,        pt=9.0, center=True)
            _cell_write(row.cells[3], r.message,  pt=9.0)

    def _add_measurements_section(self, doc, results: list) -> None:
        doc.add_heading("Análise de Métricas", level=1)

        for r in results:
            ms     = r.measurements
            status = r.status.value

            doc.add_heading(f"{status}  —  {r.name}", level=2)

            t = doc.add_table(rows=1 + len(ms), cols=5)
            t.style = "Table Grid"

            _hdr_row(t, "Métrica", "Valor", "Limites", "Estatísticas", "Status")

            for row_i, m in enumerate(ms, start=1):
                row = t.rows[row_i]
                wl     = m.within_limits
                m_stat = "INFO" if wl is None else ("PASS" if wl else "FAIL")
                bg     = _BG.get(m_stat, "FFFFFF")
                fg     = _FG.get(m_stat, "000000")

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
                        f"µ={_fmt(m.mean, m.unit)}\n"
                        f"σ={_fmt(m.std_dev, m.unit)}\n"
                        f"min={_fmt(m.minimum, m.unit)}  "
                        f"max={_fmt(m.maximum, m.unit)}"
                    )

                desc_txt = m.name
                if m.description:
                    desc_txt += f"\n{m.description}"

                _cell_write(row.cells[0], desc_txt, pt=8.5)
                _cell_write(row.cells[1], _fmt(m.value, m.unit), bold=True, pt=9.0)
                _cell_write(row.cells[2], lim_str,   pt=8.5)
                _cell_write(row.cells[3], stats_str, pt=8.0)

                _cell_bg(row.cells[4], bg)
                _cell_write(row.cells[4], m_stat, bold=True, fg_hex=fg, pt=9.0, center=True)

            doc.add_paragraph()  # espaço entre métricas

    def _add_footer(self, doc) -> None:
        from docx.shared import Pt

        doc.add_paragraph()
        p = doc.add_paragraph(
            f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} · "
            "JTAG Tester — Sistema de Testes de Hardware"
        )
        p.runs[0].font.size = Pt(8)
        p.runs[0].italic    = True
