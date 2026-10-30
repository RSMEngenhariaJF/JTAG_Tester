"""Painel de detalhes do teste — o que o teste faz, onde atua e o último resultado.

Aparece abaixo da tabela de resultados (splitter). É preenchido ao clicar num
teste do plano (aba Testes) ou numa linha da tabela de resultados:

    cabeçalho   rótulo, classe, categoria, ativo/pausado
    descrição   o que o teste verifica e como (docstring da classe)
    parâmetros  valor de cada parâmetro e os pinos/periféricos que ele resolve
    resultado   status, mensagem, duração e as métricas com limite, margem e
                origem do limite (perfil ou padrão do teste)

As funções entry_html() / result_html() geram o HTML e podem ser testadas sem Qt.
"""

from __future__ import annotations

import html
import inspect

from PySide6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget

_STATUS_COLOR = {"PASS": "#1E7B34", "FAIL": "#B00020", "ERROR": "#B00020", "SKIP": "#8A6D00"}
_CSS = """
<style>
  body { font-size: 11px; }
  h3 { margin: 2px 0 2px 0; }
  .sub { color: #666; }
  table { border-collapse: collapse; margin-top: 4px; }
  th { background: #E8EEF5; text-align: left; padding: 2px 8px; }
  td { padding: 2px 8px; border-bottom: 1px solid #E3E3E3; vertical-align: top; }
  .ajuda { color: #777; }
</style>
"""


def _e(text: object) -> str:
    return html.escape(str(text))


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table width='100%'><tr>{head}</tr>{body}</table>"


def _status(status: str) -> str:
    return f"<b style='color:{_STATUS_COLOR.get(status, '#333')}'>{_e(status)}</b>"


# ── Pinos que cada parâmetro resolve ─────────────────────────────────────────

def _pin_text(name: str, project) -> str:
    """'servo_in_p1 → PB10 (PWM TIM2 CH3)'."""
    if project is None or name not in project.pins:
        return f"{_e(name)} <span class='ajuda'>(não está no Pinout)</span>"
    pd = project.pins[name]
    where = f"P{pd.port.removeprefix('GPIO')}{pd.pin}"
    ref = pd.peripheral
    func = " ".join(x for x in (ref.periph_type, ref.name, ref.role) if x and x != "GPIO")
    info = [_e(func)] if func else []
    if pd.active_low:
        info.append("ativo-baixo")
    return f"{_e(name)} → <b>{where}</b>" + (f" ({', '.join(info)})" if info else "")


def _resolved(param, value, project) -> str:
    from tests_builtin import params as tp

    if isinstance(param, tp.SignalsParam):
        return "<br>".join(_pin_text(n, project) for n in value or []) or "—"
    if isinstance(param, tp.PeripheralParam) and project is not None and value:
        pins = [n for n, pd in project.pins.items() if pd.peripheral.name == value]
        roles = [f"{_e(project.pins[n].peripheral.role or n)}: "
                 f"P{project.pins[n].port.removeprefix('GPIO')}{project.pins[n].pin}"
                 for n in pins]
        return f"<b>{_e(value)}</b>" + (f" — {', '.join(roles)}" if roles else
                                        " <span class='ajuda'>(sem pinos no Pinout)</span>")
    return ""


def _params_rows(cls, values: dict, project) -> list[list[str]]:
    from tests_builtin import params as tp

    merged = {**tp.defaults(cls.params), **(values or {})}
    rows = []
    for key, param in cls.params.items():
        value = merged.get(key)
        shown = _resolved(param, value, project) or _e(param.describe(value))
        rows.append([_e(param.label), shown,
                     f"<span class='ajuda'>{_e(param.help)}</span>" if param.help else ""])
    return rows


# ── HTML ─────────────────────────────────────────────────────────────────────

def result_html(result) -> str:
    """Último resultado: status, mensagem e métricas (com limite, margem e origem)."""
    from core.analysis.criteria_report import limits_text, margin_text
    from core.analysis.report import _fmt

    status = result.status.value
    out = [f"<p>{_status(status)} &nbsp; {result.duration_ms:.1f} ms<br>{_e(result.message)}</p>"]
    ms = list(result.measurements or [])
    if ms:
        rows = [[_status(m.status), _e(m.name), _e(_fmt(m.value, m.unit)),
                 _e(limits_text(m, _fmt) or "—"), _e(margin_text(m)),
                 _e(m.limit_source or "—")] for m in ms]
        out.append(_table(["", "Métrica", "Valor", "Limite", "Margem", "Origem do limite"],
                          rows))
    return "".join(out)


def entry_html(entry, project=None, result=None) -> str:
    """Detalhes de uma entrada do plano de testes (e do último resultado dela)."""
    from tests_builtin.plan import resolve_ref

    try:
        cls = resolve_ref(entry.test)
    except Exception as exc:
        return (f"{_CSS}<h3>{_e(entry.label or entry.test)}</h3>"
                f"<p style='color:#B00020'>Não foi possível carregar o teste: {_e(exc)}</p>"
                f"<p class='sub'>{_e(entry.test)}</p>")
    estado = "ativo" if entry.enabled else "pausado (não roda na suite)"
    if getattr(entry, "repeat", 1) > 1:
        estado += f" · {entry.repeat} repetições (repetibilidade)"
    categoria = getattr(cls, "category", "") or "—"
    out = [_CSS,
           f"<h3>{_e(entry.label or cls.name)}</h3>",
           f"<p class='sub'>{_e(cls.name)} · categoria {_e(categoria)} · {estado}<br>"
           f"{_e(entry.test)}</p>",
           f"<p>{_e(cls.description)}</p>"]
    doc = inspect.getdoc(cls)
    if doc and doc.strip() != cls.description.strip():
        out.append(f"<p class='sub'>{_e(doc).replace(chr(10), '<br>')}</p>")
    if cls.params:
        out.append("<b>Parâmetros</b>")
        out.append(_table(["Parâmetro", "Valor / onde atua", ""],
                          _params_rows(cls, entry.params, project)))
    out.append("<br><b>Último resultado</b>")
    out.append(result_html(result) if result is not None else
               "<p class='sub'>Ainda não executado nesta sessão.</p>")
    return "".join(out)


def standalone_result_html(result) -> str:
    """Resultado sem entrada do plano (testes embutidos e plugins)."""
    return f"{_CSS}<h3>{_e(result.name)}</h3>{result_html(result)}"


def result_name(entry) -> str:
    """Nome com que o resultado desta entrada aparece na tabela."""
    from tests_builtin.plan import resolve_ref

    try:
        base = resolve_ref(entry.test).name
    except Exception:
        return entry.label or entry.test
    return f"{base} — {entry.label}" if entry.label else base


# ── Widget ───────────────────────────────────────────────────────────────────

class TestDetailPanel(QWidget):
    __test__ = False

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        self._title = QLabel("Detalhes do teste")
        self._title.setStyleSheet("font-weight: bold; font-size: 12px;")
        lay.addWidget(self._title)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        lay.addWidget(self.browser, stretch=1)
        self.clear()

    def clear(self) -> None:
        self.current: str | None = None
        self.browser.setHtml(f"{_CSS}<p class='sub'>Clique num teste do plano (aba Testes) ou "
                             "numa linha dos resultados para ver os detalhes.</p>")

    def show_entry(self, entry, project=None, result=None) -> None:
        self.current = result_name(entry)
        self.browser.setHtml(entry_html(entry, project, result))

    def show_result(self, result) -> None:
        self.current = result.name
        self.browser.setHtml(standalone_result_html(result))
