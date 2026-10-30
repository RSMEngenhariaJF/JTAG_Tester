"""Seções de auditoria dos relatórios — mesmas informações em HTML, PDF e Word.

    environment_rows(env)  — ambiente da execução (software, sonda, MCU, projeto, horários)
    test_blocks(result)    — registro de um teste: identificação, parâmetros, decisões,
                             repetições, passos (aplicado → observado), log e exceção

Cada bloco é independente do formato; os geradores (report.py, report_pdf.py,
report_docx.py) só desenham. Os dados vêm de TestResult.details, preenchido na
execução (tests_builtin/base.py e tests_builtin/audit.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Rótulos do ambiente, na ordem em que aparecem
_ENV_LABELS = (
    ("software", "Software"), ("python", "Python"), ("pyocd", "pyOCD"),
    ("sonda", "Sonda de debug"), ("mcu", "MCU"), ("placa", "Placa"),
    ("projeto", "Projeto"), ("projeto_arquivo", "Arquivo do projeto"),
    ("projeto_sha256", "SHA-256 do projeto"), ("perfil", "Perfil de critérios"),
    ("inicio", "Início da suíte"), ("fim", "Fim da suíte"), ("duracao", "Duração total"),
    ("testes", "Testes executados"),
)


@dataclass
class Block:
    """kind: "kv" (rótulo/valor), "table" (cabeçalho + linhas) ou "pre" (texto fixo)."""

    kind:    str
    title:   str
    headers: list[str] = field(default_factory=list)
    rows:    list[list[str]] = field(default_factory=list)
    text:    str = ""
    widths:  list[int] = field(default_factory=list)   # % por coluna (HTML/PDF)


def _clock_time(iso: str) -> str:
    """'2026-10-30T09:46:08.297-03:00' → '09:46:08.297' (a data já está no cabeçalho)."""
    return iso[11:23] if len(iso) >= 23 and iso[10] == "T" else iso


def environment_rows(env: dict | None) -> list[list[str]]:
    env = env or {}
    rows = [[label, str(env[key])] for key, label in _ENV_LABELS if env.get(key)]
    known = {k for k, _ in _ENV_LABELS}
    rows += [[k, str(v)] for k, v in env.items() if k not in known and v]
    return rows


def test_blocks(result) -> list[Block]:
    d = result.details or {}
    ident = d.get("teste", {})
    blocks: list[Block] = []

    kv = [["Status", result.status.value], ["Mensagem", result.message]]
    if result.started_at:
        kv.append(["Início", result.started_at])
    kv.append(["Duração", f"{result.duration_ms:.1f} ms"])
    if ident.get("classe"):
        kv.append(["Classe", ident["classe"]])
    if ident.get("arquivo"):
        kv.append(["Arquivo do teste", ident["arquivo"]])
    if ident.get("sha256"):
        kv.append(["SHA-256 do código", ident["sha256"]])
    if d.get("descricao"):
        kv.append(["Descrição", d["descricao"]])
    blocks.append(Block("kv", "Identificação", rows=kv))

    if result.params:
        blocks.append(Block("table", "Parâmetros aplicados", ["Parâmetro", "Valor"],
                            [[k, str(v)] for k, v in result.params.items()], widths=[40, 60]))
    if result.measured is not None or result.expected is not None:
        blocks.append(Block("kv", "Valores comparados",
                            rows=[["Medido", str(result.measured)],
                                  ["Esperado", str(result.expected)]]))
    if d.get("decisoes"):
        blocks.append(Block("table", "Decisões (critério de aceitação)",
                            ["Veredito", "Resultado"], [list(r) for r in d["decisoes"]],
                            widths=[12, 88]))
    if d.get("repeticoes"):
        rows = [[n, st, f"{ms} ms", _clock_time(t0), msg] for n, st, ms, t0, msg in d["repeticoes"]]
        blocks.append(Block("table", "Repetições", ["#", "Status", "Duração", "Início", "Mensagem"],
                            rows, widths=[5, 10, 11, 14, 60]))
    if d.get("passos"):
        title = "Passos executados (aplicado → observado)"
        if d.get("repeticoes"):
            title += " — última repetição"
        blocks.append(Block("table", title, ["#", "Passo", "t (ms)", "Aplicado", "Observado"],
                            [list(r) for r in d["passos"]], widths=[5, 18, 8, 27, 42]))
    if d.get("log"):
        blocks.append(Block("pre", "Log durante o teste", text="\n".join(d["log"])))
    if d.get("excecao"):
        blocks.append(Block("pre", "Exceção (rastreamento)", text=d["excecao"].rstrip()))
    return blocks
