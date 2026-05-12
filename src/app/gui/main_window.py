"""Janela principal da aplicação — pilot do Sprint 01.

Implementa o layout-base descrito na §8.1 da Especificação v0.5:

- barra de menu (Arquivo / Projeto / Executar / Ferramentas / Ajuda);
- painel lateral esquerdo com projetos recentes;
- área central com estado da bancada;
- barra de status persistente (probe / projeto / plano / instrumentos).

Todas as ações vêm desabilitadas — sprints subsequentes (08 em diante)
conectam a lógica real do Core.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.gui.about_dialog import AboutDialog

_PLACEHOLDER_TOOLTIP = "Disponível em sprints futuros."


class MainWindow(QMainWindow):
    """Janela principal — esqueleto não-funcional."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Plataforma de Bring-up — v{__version__} (Sprint 01)")
        self.resize(1180, 720)
        self.setMinimumSize(900, 560)

        self._build_menu()
        self._build_central()
        self._build_status_bar()

    # ------------------------------------------------------------------ menu

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        # Arquivo
        m_arq = menubar.addMenu("&Arquivo")
        m_arq.addAction(self._placeholder_action("Abrir Projeto...", QKeySequence("Ctrl+O")))
        m_arq.addAction(self._placeholder_action("Projetos Recentes"))
        m_arq.addSeparator()
        m_arq.addAction(self._placeholder_action("Preferências...", QKeySequence("Ctrl+,")))
        m_arq.addSeparator()
        act_sair = QAction("Sair", self)
        act_sair.setShortcut(QKeySequence("Ctrl+Q"))
        act_sair.triggered.connect(self.close)
        m_arq.addAction(act_sair)

        # Projeto
        m_proj = menubar.addMenu("&Projeto")
        m_proj.addAction(
            self._placeholder_action("Adicionar Plugin de Pasta...", QKeySequence("Ctrl+Shift+O"))
        )
        m_proj.addAction(self._placeholder_action("Configuração da Placa..."))
        m_proj.addAction(self._placeholder_action("Editor de Plano de Teste..."))

        # Executar
        m_exec = menubar.addMenu("&Executar")
        m_exec.addAction(self._placeholder_action("Executar Plano", QKeySequence("F5")))
        m_exec.addAction(self._placeholder_action("Cancelar Execução", QKeySequence("Esc")))
        m_exec.addSeparator()
        m_exec.addAction(self._placeholder_action("Modo Bancada Simulada"))

        # Ferramentas
        m_tools = menubar.addMenu("&Ferramentas")
        m_tools.addAction(self._placeholder_action("Console Interativo..."))
        m_tools.addAction(self._placeholder_action("Bancada › Instrumentos..."))
        m_tools.addAction(self._placeholder_action("Histórico de Execuções..."))

        # Ajuda
        m_help = menubar.addMenu("A&juda")
        act_sobre = QAction("Sobre...", self)
        act_sobre.triggered.connect(self._show_about)
        m_help.addAction(act_sobre)

    def _placeholder_action(self, text: str, shortcut: QKeySequence | None = None) -> QAction:
        act = QAction(text, self)
        if shortcut is not None:
            act.setShortcut(shortcut)
        act.setEnabled(False)
        act.setToolTip(_PLACEHOLDER_TOOLTIP)
        return act

    # ---------------------------------------------------------------- central

    def _build_central(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_recent_projects_panel())
        splitter.addWidget(self._build_bench_status_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([280, 900])
        self.setCentralWidget(splitter)

    def _build_recent_projects_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel("Projetos recentes")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        self.recent_list = QListWidget()
        QListWidgetItem("(nenhum projeto recente)", self.recent_list)
        self.recent_list.setEnabled(False)
        layout.addWidget(self.recent_list, stretch=1)

        return panel

    def _build_bench_status_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        layout.addWidget(self._heading("Estado da Bancada"))
        layout.addWidget(self._info_row("Probe", "não conectado"))
        layout.addWidget(self._info_row("Instrumentos", "nenhum detectado"))
        layout.addWidget(self._info_row("Projeto ativo", "nenhum"))
        layout.addWidget(self._info_row("Plano selecionado", "—"))
        layout.addStretch(1)

        hint = QLabel(
            "<i>Pilot do Sprint 01: layout-base conforme §8.1 da especificação. "
            "Conectividade real do probe entra a partir do Sprint 04.</i>"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

        return panel

    @staticmethod
    def _heading(text: str) -> QLabel:
        lbl = QLabel(text)
        font = lbl.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        lbl.setFont(font)
        return lbl

    @staticmethod
    def _info_row(label: str, value: str) -> QLabel:
        return QLabel(f"<b>{label}:</b> <i>{value}</i>")

    # ------------------------------------------------------------- status bar

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)

        self.lbl_probe = QLabel("Probe: —")
        self.lbl_project = QLabel("Projeto: —")
        self.lbl_plan = QLabel("Plano: —")
        self.lbl_instruments = QLabel("Instrumentos: 0")
        for lbl in (self.lbl_probe, self.lbl_project, self.lbl_plan, self.lbl_instruments):
            lbl.setMinimumWidth(140)
            bar.addPermanentWidget(lbl)

        bar.showMessage("Pronto.", 3000)

    # ----------------------------------------------------------------- about

    def _show_about(self) -> None:
        dialog = AboutDialog(self)
        dialog.exec()
