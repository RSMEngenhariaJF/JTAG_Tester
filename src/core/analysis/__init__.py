"""Sistema de análise e relatório de testes.

Módulos:
    config      — MetricConfig, AnalysisConfig, perfis importáveis/exportáveis
    metrics     — Measurement, MeasurementSet (dados e estatísticas)
    analyzers   — Funções de análise: BER, timing, tensão, frequência, atraso
    report      — Gerador de relatório HTML auto-contido
    report_docx — Gerador de relatório Word (.docx) via python-docx
    report_pdf  — Gerador de relatório PDF via PyMuPDF (fitz.Story)
"""

from core.analysis.config import (
    AnalysisConfig,
    MetricConfig,
    active_limits,
    find_configs,
    get_active_analysis_config,
    set_active_analysis_config,
)
from core.analysis.metrics import Measurement, MeasurementSet
from core.analysis.analyzers import (
    analyze_ber,
    analyze_timing,
    analyze_voltage,
    analyze_frequency,
    analyze_delay,
)
from core.analysis.report      import HtmlReport
from core.analysis.report_docx import DocxReport
from core.analysis.report_pdf  import PdfReport

__all__ = [
    # Config
    "AnalysisConfig",
    "MetricConfig",
    "active_limits",
    "find_configs",
    "get_active_analysis_config",
    "set_active_analysis_config",
    # Metrics
    "Measurement",
    "MeasurementSet",
    # Analyzers
    "analyze_ber",
    "analyze_timing",
    "analyze_voltage",
    "analyze_frequency",
    "analyze_delay",
    # Reports
    "HtmlReport",
    "DocxReport",
    "PdfReport",
]
