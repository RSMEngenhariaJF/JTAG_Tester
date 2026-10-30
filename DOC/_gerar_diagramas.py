"""Gera os diagramas do guia (DOC/img/diagrama_*.png) com QPainter — sem dependência extra.

Rodar a partir da raiz do repositório, antes de DOC/_gerar_word.py:
    python DOC/_gerar_diagramas.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPolygonF

OUT = Path(__file__).resolve().parent / "img"
ESCALA = 2                       # imagem em 2x para ficar nítida no Word/PDF

# Paleta (a mesma família de azuis do guia)
AZUL_ESCURO = QColor("#1F3964")
AZUL_MEDIO  = QColor("#2E74B5")
CINZA_TEXTO = QColor("#555555")
ESTILOS = {
    # nome: (preenchimento, borda, cor do título)
    "voce":   ("#FFF2CC", "#D6A100", "#7A5C00"),
    "app":    ("#D6E4F0", "#2E74B5", "#1F3964"),
    "dados":  ("#E2F0D9", "#548235", "#375623"),
    "acesso": ("#DEEBF7", "#2E74B5", "#1F3964"),
    "hw":     ("#EDEDED", "#7F7F7F", "#404040"),
    "lado":   ("#FBE5D6", "#C55A11", "#843C0C"),
}


def _font(px: int, bold: bool = False) -> QFont:
    f = QFont("Segoe UI")
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def bloco(p: QPainter, r: QRectF, titulo: str, sub: str, estilo: str,
          tag: str = "") -> None:
    fill, borda, cor_tit = ESTILOS[estilo]
    path = QPainterPath()
    path.addRoundedRect(r, 12, 12)
    p.fillPath(path, QColor(fill))
    p.setBrush(Qt.BrushStyle.NoBrush)      # a ponta da seta deixa o pincel preenchido
    p.setPen(QPen(QColor(borda), 2.5))
    p.drawPath(path)

    p.setPen(QColor(cor_tit))
    p.setFont(_font(28, True))
    p.drawText(r.adjusted(18, 12, -18, 0), Qt.AlignmentFlag.AlignLeft, titulo)
    if tag:
        p.setFont(_font(18, True))
        p.setPen(QColor(borda))
        p.drawText(r.adjusted(18, 14, -18, 0), Qt.AlignmentFlag.AlignRight, tag)
    p.setPen(CINZA_TEXTO)
    p.setFont(_font(22))
    p.drawText(r.adjusted(18, 52, -18, -6),
               Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, sub)


def seta(p: QPainter, a: QPointF, b: QPointF, cor: QColor = AZUL_ESCURO,
         tracejada: bool = False, dupla: bool = True, rotulo: str = "") -> None:
    pen = QPen(cor, 2.5)
    if tracejada:
        pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.drawLine(a, b)

    def ponta(fim: QPointF, ini: QPointF) -> None:
        d = fim - ini
        n = (d.x() ** 2 + d.y() ** 2) ** 0.5 or 1
        ux, uy = d.x() / n, d.y() / n
        s = 13
        poly = QPolygonF([
            fim,
            QPointF(fim.x() - ux * s - uy * s * 0.55, fim.y() - uy * s + ux * s * 0.55),
            QPointF(fim.x() - ux * s + uy * s * 0.55, fim.y() - uy * s - ux * s * 0.55),
        ])
        p.setBrush(cor)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(poly)
        p.setPen(pen)

    ponta(b, a)
    if dupla:
        ponta(a, b)
    if rotulo:
        p.setPen(CINZA_TEXTO)
        p.setFont(_font(18))
        meio = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
        p.drawText(QRectF(meio.x() + 10, meio.y() - 11, 260, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, rotulo)


def diagrama_camadas() -> QImage:
    W, H = 1600, 1330
    img = QImage(W * ESCALA, H * ESCALA, QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(ESCALA, ESCALA)

    X, LARG, ALT, PASSO = 40, 1010, 118, 150
    cx = X + LARG / 2
    pilha = [
        ("Seu teste  /  blocos do Plano de testes",
         "class MeuTeste(BuiltinTest) com params  ·  pinos e periféricos vêm do Pinout do projeto",
         "voce", "VOCÊ TRABALHA AQUI"),
        ("GUI (janela)  /  CLI (terminal)",
         "Seleção de projeto e placa  ·  execução da suite  ·  relatórios PDF, HTML, Word  ·  JSON/CSV",
         "app", "seções 2 e 9"),
        ("BoardConfig  /  ProjectConfig",
         "Pinos, clocks e periféricos da placa  ·  get_active_board(), get_active_project()",
         "dados", "seção 3"),
        ("TestRunnerService",
         "Executa os testes em ordem numa thread  ·  captura exceções  ·  entrega os resultados à GUI",
         "app", ""),
        ("HAL de periféricos (src/hal)",
         "UART, SPI, I2C, EXTI, CAN, Ethernet  ·  registradores pela família (F4/H7)  ·  restaura o estado",
         "dados", "seção 14"),
        ("PAL — Peripheral Access Layer",
         "Traduz nomes em endereços: pal.read_field(\"GPIOA\", \"MODER\", \"MODER5\")",
         "acesso", "seção 5"),
        ("Probe: pyOCD + ST-Link  /  FT2232H",
         "USB  →  SWD  →  barramento de debug do chip (cerca de 0,3 a 0,5 ms por acesso)",
         "acesso", ""),
    ]
    rects = []
    for i, (tit, sub, est, tag) in enumerate(pilha):
        r = QRectF(X, 30 + i * PASSO, LARG, ALT)
        bloco(p, r, tit, sub, est, tag)
        rects.append(r)
    for a, b in zip(rects, rects[1:], strict=False):
        seta(p, QPointF(cx, a.bottom() + 3), QPointF(cx, b.top() - 3), dupla=False)

    # Microcontrolador (largura total) com o agente na RAM dentro
    mcu = QRectF(X, 30 + len(pilha) * PASSO, 1520, 222)
    bloco(p, mcu, "Microcontrolador STM32",
          "Registradores, RAM e periféricos (GPIO, USART, SPI, ADC...)  ·  pinos da placa",
          "hw")
    seta(p, QPointF(cx, rects[-1].bottom() + 3), QPointF(cx, mcu.top() - 3), dupla=False)
    stub = QRectF(mcu.left() + 560, mcu.top() + 100, 600, 100)
    bloco(p, stub, "Agente na RAM", "stub carregado via SWD, roda na velocidade do núcleo",
          "lado", "seção 12")

    # Coluna lateral: instrumentos e SVD
    XL, LL = 1110, 450
    instr = QRectF(XL, 30, LL, ALT + 82)
    bloco(p, instr, "Instrumentos de bancada",
          "get_oscilloscope(\"osc\")\n"
          "get_spectrum_analyzer(\"sa\")\n"
          "VISA / LAN  ·  Rigol MSO8000, R&S FPC\n"
          "rastreabilidade de calibração",
          "lado", "seção 13")
    seta(p, QPointF(rects[0].right() + 3, rects[0].center().y()),
         QPointF(instr.left() - 3, rects[0].center().y()))

    svd = QRectF(XL, rects[5].top(), LL - 120, ALT + 30)
    bloco(p, svd, "Arquivo SVD", "Mapa de todos os registradores e campos do chip (XML da ARM)",
          "dados", "seção 6")
    seta(p, QPointF(svd.left() - 3, svd.center().y()),
         QPointF(rects[5].right() + 3, svd.center().y()), dupla=False, rotulo="")

    # Pontas de prova: instrumentos medem os pinos do MCU
    xp = instr.right() - 55               # passa à direita da caixa do SVD
    seta(p, QPointF(xp, instr.bottom() + 3), QPointF(xp, mcu.top() - 3),
         cor=QColor("#C55A11"), tracejada=True, dupla=False)
    p.setPen(QColor("#843C0C"))
    p.setFont(_font(20, True))
    p.drawText(QRectF(xp - 260, rects[2].top() + 20, 248, 60),
               Qt.AlignmentFlag.AlignRight | Qt.TextFlag.TextWordWrap, "pontas de prova\nnos pinos")

    # Fluxo do agente: o host carrega o stub e lê a fila
    xa = stub.center().x() + 120
    seta(p, QPointF(rects[-1].right() - 160, rects[-1].bottom() + 3),
         QPointF(xa, stub.top() - 3), cor=QColor("#C55A11"), tracejada=True)
    p.setPen(QColor("#843C0C"))
    p.setFont(_font(19))
    p.drawText(QRectF(xa + 30, rects[-1].bottom() + 4, 420, 28),
               Qt.AlignmentFlag.AlignLeft, "carga do stub / leitura da fila")

    p.end()
    return img


def _canvas(w: int, h: int) -> tuple[QImage, QPainter]:
    img = QImage(w * ESCALA, h * ESCALA, QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(ESCALA, ESCALA)
    return img, p


def _moldura(p: QPainter, r: QRectF, titulo: str) -> None:
    """Retângulo tracejado que agrupa blocos (ex.: o ComposedTest)."""
    path = QPainterPath()
    path.addRoundedRect(r, 16, 16)
    p.fillPath(path, QColor("#F7F9FC"))
    pen = QPen(AZUL_MEDIO, 2.5)
    pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.setPen(AZUL_ESCURO)
    p.setFont(_font(22, True))
    p.drawText(r.adjusted(20, 10, -20, 0), Qt.AlignmentFlag.AlignLeft, titulo)


def _rotulo(p: QPainter, x: float, y: float, w: float, texto: str,
            cor: QColor = CINZA_TEXTO, centro: bool = True) -> None:
    p.setPen(cor)
    p.setFont(_font(17))
    align = Qt.AlignmentFlag.AlignHCenter if centro else Qt.AlignmentFlag.AlignLeft
    p.drawText(QRectF(x, y, w, 50), align | Qt.TextFlag.TextWordWrap, texto)


def diagrama_testbench() -> QImage:
    """Fluxo de dados de um ComposedTest: estímulo → drivers → HW → monitores → decisões."""
    img, p = _canvas(1600, 1010)

    plano = QRectF(1000, 20, 560, 96)
    bloco(p, plano, "Plano de testes (params)",
          "pinos, periférico, ciclos... escolhidos no formulário", "voce", "seção 14")

    frame = QRectF(30, 150, 1540, 610)
    _moldura(p, frame, "ComposedTest  —  build() monta a bancada; _run() executa e decide")
    seta(p, QPointF(plano.center().x(), plano.bottom() + 3),
         QPointF(plano.center().x(), frame.top() + 46), dupla=False)
    _rotulo(p, plano.center().x() + 12, plano.bottom() + 2, 200, "self.p.<nome>", centro=False)

    y1, h = 230, 180
    est = QRectF(60, y1, 320, h)
    drv = QRectF(440, y1, 320, h)
    hw = QRectF(820, y1, 300, h)
    mon = QRectF(1180, y1, 360, h)
    bloco(p, est, "Estímulo", "O QUE fazer, passo a passo\nToggle · Levels · Sample · Chain",
          "app")
    bloco(p, drv, "Drivers", "aplicam o valor do passo\nGpioOutputDriver\nGpioPullDriver",
          "acesso")
    bloco(p, hw, "Hardware", "pinos do MCU\nvia PAL / SWD", "hw")
    bloco(p, mon, "Monitores", "observam a cada passo\nGpioInputMonitor (IDR)\n"
          "GpioLatchMonitor (ODR)", "acesso")
    cy = y1 + h / 2
    seta(p, QPointF(est.right() + 3, cy), QPointF(drv.left() - 3, cy), dupla=False)
    seta(p, QPointF(drv.right() + 3, cy), QPointF(hw.left() - 3, cy), dupla=False)
    seta(p, QPointF(hw.right() + 3, cy), QPointF(mon.left() - 3, cy), dupla=False)
    _rotulo(p, est.right() - 10, cy - 52, 80, "Step")
    _rotulo(p, drv.right() - 10, cy - 52, 80, "aplica")
    _rotulo(p, hw.right() - 10, cy - 52, 80, "lê")

    y2 = 520
    trace = QRectF(1180, y2, 360, 190)
    dec = QRectF(640, y2, 440, 190)
    ver = QRectF(60, y2, 480, 190)
    bloco(p, trace, "Trace (histórico)", "por passo: valor aplicado\n+ valor observado",
          "dados")
    bloco(p, dec, "Decisões", "comparam observado × esperado\nFollowsDrive · Expect · Report",
          "voce")
    bloco(p, ver, "Veredito + métricas", "ok / falha / informativo\n"
          "ex.: gpio_divergencias_led = 0", "dados")
    seta(p, QPointF(mon.center().x(), mon.bottom() + 3), QPointF(trace.center().x(), trace.top() - 3),
         dupla=False)
    _rotulo(p, mon.center().x() + 10, mon.bottom() + 30, 170, "amostra", centro=False)
    # valores aplicados: contorna por baixo dos blocos até o topo do Trace
    verde = QColor("#548235")
    pen = QPen(verde, 2.5)
    pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    xa, ya, xb = drv.center().x(), drv.bottom() + 55, trace.left() + 50
    p.drawLine(QPointF(xa, drv.bottom() + 3), QPointF(xa, ya))
    p.drawLine(QPointF(xa, ya), QPointF(xb, ya))
    seta(p, QPointF(xb, ya), QPointF(xb, trace.top() - 3), cor=verde, tracejada=True, dupla=False)
    _rotulo(p, xa + 14, ya - 32, 400, "valores aplicados (por passo)", QColor("#375623"),
            centro=False)
    cy2 = y2 + 95
    seta(p, QPointF(trace.left() - 3, cy2), QPointF(dec.right() + 3, cy2), dupla=False)
    seta(p, QPointF(dec.left() - 3, cy2), QPointF(ver.right() + 3, cy2), dupla=False)

    y3 = 820
    perfil = QRectF(60, y3, 480, 150)
    res = QRectF(640, y3, 900, 150)
    bloco(p, perfil, "Perfil de critérios", "analysis_configs/*.json\no perfil vence o limite "
          "padrão (0)", "lado", "seção 16")
    bloco(p, res, "Resultado do teste", "PASS / FAIL + métricas com limite, origem e margem\n"
          "→ tabela da GUI, relatório PDF/HTML/Word, JSON, logs", "app")
    seta(p, QPointF(perfil.center().x(), perfil.top() - 3), QPointF(ver.center().x(), ver.bottom() + 3),
         cor=QColor("#C55A11"), dupla=False)
    _rotulo(p, perfil.center().x() + 12, ver.bottom() + 12, 220, "limites", QColor("#843C0C"),
            centro=False)
    seta(p, QPointF(ver.right() - 40, ver.bottom() + 3), QPointF(res.left() + 60, res.top() - 3),
         dupla=False)

    p.setPen(CINZA_TEXTO)
    p.setFont(_font(16))
    p.drawText(QRectF(640, y2 + 196, 900, 30), Qt.AlignmentFlag.AlignRight,
               "setup() salva o estado de cada pino  ·  teardown() restaura — mesmo se der erro")
    p.end()
    return img


def diagrama_ciclo() -> QImage:
    """Ciclo de execução de Testbench.run(), da preparação ao veredito."""
    img, p = _canvas(1600, 560)
    h, y, gap = 230, 150, 30
    larguras = [260, 380, 260, 260, 260]
    xs, x = [], 15
    for lw in larguras:
        xs.append(x)
        x += lw + gap
    caixas = [
        ("1. setup", "drivers e depois monitores salvam o estado e preparam os pinos", "acesso"),
        ("2. passos do estímulo", "", "app"),
        ("3. teardown", "monitores e depois drivers restauram os pinos", "acesso"),
        ("4. decisões", "avaliam o Trace e devolvem Verdict + métricas", "voce"),
        ("5. resultado", "métricas → MeasurementSet (aplica o perfil) → PASS/FAIL", "dados"),
    ]
    rects = []
    for x, lw, (tit, sub, est) in zip(xs, larguras, caixas, strict=True):
        r = QRectF(x, y, lw, h)
        bloco(p, r, tit, sub, est)
        rects.append(r)
    for a, b in zip(rects, rects[1:], strict=False):
        seta(p, QPointF(a.right() + 3, y + h / 2), QPointF(b.left() - 3, y + h / 2), dupla=False)

    # Detalhe do laço de passos
    laco = rects[1]
    itens = ["aplica o valor em cada driver", "espera wait_s", "amostra cada monitor",
             "grava Observation no Trace"]
    p.setFont(_font(17))
    for i, txt in enumerate(itens):
        r = QRectF(laco.left() + 22, laco.top() + 56 + i * 40, laco.width() - 44, 34)
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.fillPath(path, QColor("white"))
        p.setPen(QPen(AZUL_MEDIO, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setPen(AZUL_ESCURO)
        p.drawText(r.adjusted(10, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter, f"{i + 1}) {txt}")
    # seta de repetição
    p.setPen(QPen(AZUL_MEDIO, 2.5))
    arco = QRectF(laco.left() + 60, laco.bottom() + 6, laco.width() - 120, 60)
    p.drawArc(arco, 0, -180 * 16)
    _rotulo(p, laco.left(), laco.bottom() + 70, laco.width(), "repete para cada Step",
            AZUL_MEDIO)

    # caminho de erro: sempre passa pelo teardown
    pen = QPen(QColor("#C00000"), 2.5)
    pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    y_err = y - 40
    p.drawLine(QPointF(laco.center().x(), y), QPointF(laco.center().x(), y_err))
    p.drawLine(QPointF(laco.center().x(), y_err), QPointF(rects[2].center().x(), y_err))
    seta(p, QPointF(rects[2].center().x(), y_err), QPointF(rects[2].center().x(), y - 3),
         cor=QColor("#C00000"), tracejada=True, dupla=False)
    _rotulo(p, laco.center().x() + 10, y_err - 34, 420,
            "erro no meio → teardown mesmo assim (finally)", QColor("#C00000"), centro=False)
    p.end()
    return img


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841
    OUT.mkdir(parents=True, exist_ok=True)
    for nome, fn in (("diagrama_camadas.png", diagrama_camadas),
                     ("diagrama_testbench.png", diagrama_testbench),
                     ("diagrama_ciclo.png", diagrama_ciclo)):
        img = fn()
        img.save(str(OUT / nome))
        print(f"salvo {nome} {img.width()} x {img.height()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
