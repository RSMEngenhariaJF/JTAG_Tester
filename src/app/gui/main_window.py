"""Janela principal da aplicacao — Sprint 16.

Layout:
    Splitter horizontal
    ├── QTabWidget (painel esquerdo)
    │   ├── Aba "Projeto"       (placa + probe)
    │   ├── Aba "Instrumentos"  (registry + gerenciar)
    │   └── Aba "Testes"        (suite embutida + plugins)
    └── Painel direito   (tabela de resultados + botoes Run/Abort/Export)

Fluxo:
    1. Seleciona placa no ComboBox "Projeto" → set_active_board() + título atualizado
    2. Clique "Atualizar" → popula ComboBox com probes detectados
    3. Seleciona probe no ComboBox; clica "Conectar"
    4. DeviceService.connect(board, uid=...) → probe_connected
    5. Clique "Executar Suite" → TestRunnerService.run()
    6. Cada test_finished atualiza uma linha da tabela
    7. suite_finished → habilita "Exportar..."
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.gui.about_dialog import AboutDialog
from app.gui.analysis_config_dialog import AnalysisConfigDialog
from app.gui.instrument_dialog import InstrumentManagerDialog
from app.gui.project_dialog import ProjectEditorDialog
from core.macros.registry import MacroRegistry, _MACROS_DIR
from app.services.device import DeviceService
from app.services.runner import TestRunnerService
from core.board.config import BoardConfig, set_active_board
from core.board.loader import find_boards
from core.instruments.registry import InstrumentRegistry
from core.analysis.config      import (
    AnalysisConfig,
    config_path,
    set_active_analysis_config,
)
from core.analysis.report      import HtmlReport
from core.analysis.report_docx import DocxReport
from core.analysis.report_pdf  import PdfReport
from core.project.config import ProjectConfig, set_active_project
from core.project.loader import find_projects, save_project
from tests_builtin import STANDARD_SUITE, summarize
from tests_builtin.base import BuiltinTest, TestResult, TestStatus

logger = logging.getLogger("app.gui.main_window")

# ---------------------------------------------------------------------------
# Constantes visuais
# ---------------------------------------------------------------------------

_STATUS_BG: dict[TestStatus, QColor] = {
    TestStatus.PASS:  QColor(200, 240, 200),
    TestStatus.FAIL:  QColor(255, 200, 200),
    TestStatus.ERROR: QColor(255, 220, 160),
    TestStatus.SKIP:  QColor(220, 220, 220),
}

_STATUS_LABEL: dict[TestStatus, str] = {
    TestStatus.PASS:  "PASS",
    TestStatus.FAIL:  "FAIL",
    TestStatus.ERROR: "ERROR",
    TestStatus.SKIP:  "SKIP",
}

_COL_STATUS  = 0
_COL_NAME    = 1
_COL_MS      = 2
_COL_MESSAGE = 3
_COL_HEADERS = ["Status", "Teste", "ms", "Mensagem"]


class MainWindow(QMainWindow):
    """Janela principal — gerencia seleção de placa, conexão e execução de testes."""

    def __init__(
        self,
        device: DeviceService | None = None,
        runner: TestRunnerService | None = None,
    ) -> None:
        super().__init__()
        self.setMinimumSize(900, 560)
        self.resize(1180, 720)

        self._device = device or DeviceService(self)
        self._runner = runner or TestRunnerService(self._device, self)

        self._total_tests:   int = 0
        self._pass_count:    int = 0
        self._fail_count:    int = 0
        self._last_results:  list[TestResult] = []
        self._plugin_tests:  list[BuiltinTest] = []
        self._active_board:  BoardConfig | None = None
        self._active_project: ProjectConfig | None = None
        self._boards_by_name: dict[str, BoardConfig] = {}

        self._build_menu()
        self._build_central()
        self._build_status_bar()
        self._wire_signals()
        self._load_projects()
        self._refresh_button_states()

        registry = InstrumentRegistry.instance()
        registry.load()
        registry.add_listener(self._refresh_instruments_panel)
        self._refresh_instruments_panel()

        # Auto-carrega macros da pasta macros/
        self._auto_load_macros()

    # ------------------------------------------------------------------
    # Construção do layout
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        bar = self.menuBar()

        m_arq = bar.addMenu("&Arquivo")
        self._act_export = QAction("Exportar resultados...", self)
        self._act_export.setShortcut(QKeySequence("Ctrl+S"))
        self._act_export.setEnabled(False)
        self._act_export.triggered.connect(self._export_results)
        m_arq.addAction(self._act_export)
        m_arq.addSeparator()
        act_sair = QAction("Sair", self)
        act_sair.setShortcut(QKeySequence("Ctrl+Q"))
        act_sair.triggered.connect(self.close)
        m_arq.addAction(act_sair)

        m_exec = bar.addMenu("&Executar")
        self._act_connect = QAction("Conectar probe", self)
        self._act_connect.triggered.connect(self._toggle_connect)
        m_exec.addAction(self._act_connect)
        m_exec.addSeparator()
        self._act_run = QAction("Executar Suite", self)
        self._act_run.setShortcut(QKeySequence("F5"))
        self._act_run.triggered.connect(self._run_suite)
        m_exec.addAction(self._act_run)
        self._act_abort = QAction("Cancelar", self)
        self._act_abort.setShortcut(QKeySequence("Escape"))
        self._act_abort.triggered.connect(self._runner.abort)
        m_exec.addAction(self._act_abort)

        m_help = bar.addMenu("A&juda")
        act_sobre = QAction("Sobre...", self)
        act_sobre.triggered.connect(lambda: AboutDialog(self).exec())
        m_help.addAction(act_sobre)

    def _build_central(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 880])
        self.setCentralWidget(splitter)

    def _build_left_panel(self) -> QWidget:
        tabs = QTabWidget()
        tabs.setMinimumWidth(230)
        tabs.setMaximumWidth(350)
        tabs.addTab(self._build_projeto_tab(),      "Projeto")
        tabs.addTab(self._build_instrumentos_tab(), "Instrumentos")
        tabs.addTab(self._build_testes_tab(),       "Testes")
        return tabs

    # ── Aba "Projeto" — configuração de projeto + probe ──────────────────

    def _build_projeto_tab(self) -> QWidget:
        widget = QWidget()
        lay    = QVBoxLayout(widget)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        # Configuração de projeto
        lay.addWidget(self._section_header("Configuração"))

        proj_row = QHBoxLayout()
        self._combo_projects = QComboBox()
        self._combo_projects.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._combo_projects.setToolTip(
            "Selecione um projeto.\n"
            "Cada projeto define o pinout e os testes do produto."
        )
        self._combo_projects.currentIndexChanged.connect(self._on_project_changed)
        proj_row.addWidget(self._combo_projects)
        lay.addLayout(proj_row)

        btn_row = QHBoxLayout()
        self._btn_new_project  = QPushButton("Novo...")
        self._btn_edit_project = QPushButton("Editar")
        self._btn_edit_project.setEnabled(False)
        self._btn_new_project.clicked.connect(self._new_project)
        self._btn_edit_project.clicked.connect(self._edit_project)
        btn_row.addWidget(self._btn_new_project)
        btn_row.addWidget(self._btn_edit_project)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        # Detalhes do projeto selecionado
        info_form = QFormLayout()
        info_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        info_form.setContentsMargins(0, 4, 0, 4)

        self._lbl_project_code = QLabel("—")
        self._lbl_project_code.setStyleSheet(
            "color: #1F3964; font-weight: bold; font-size: 12px;"
        )
        self._lbl_board_name = QLabel("—")
        self._lbl_board_name.setStyleSheet("font-size: 11px;")
        self._lbl_proj_desc  = QLabel("")
        self._lbl_proj_desc.setWordWrap(True)
        self._lbl_proj_desc.setStyleSheet("color: #555; font-size: 11px;")

        self._lbl_analysis_cfg = QLabel("—")
        self._lbl_analysis_cfg.setStyleSheet("font-size: 11px; color: #1a6b1a;")
        self._lbl_analysis_cfg.setWordWrap(True)

        info_form.addRow("Código:",    self._lbl_project_code)
        info_form.addRow("Placa:",     self._lbl_board_name)
        info_form.addRow("Critérios:", self._lbl_analysis_cfg)
        info_form.addRow("",           self._lbl_proj_desc)
        lay.addLayout(info_form)

        btn_crit = QPushButton("Critérios de análise...")
        btn_crit.setToolTip(
            "Abre o editor de perfis de critérios (limites, tolerâncias)\n"
            "e permite vincular um perfil ao projeto atual."
        )
        btn_crit.clicked.connect(self._open_analysis_config)
        lay.addWidget(btn_crit)

        lay.addWidget(self._separator())

        # Probe
        lay.addWidget(self._section_header("Probe"))

        combo_row = QHBoxLayout()
        self._combo_probes = QComboBox()
        self._combo_probes.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._combo_probes.setToolTip("Selecione um probe antes de conectar")
        combo_row.addWidget(self._combo_probes)

        self._btn_refresh = QPushButton("Atualizar")
        self._btn_refresh.setFixedWidth(72)
        self._btn_refresh.clicked.connect(self._refresh_probes)
        combo_row.addWidget(self._btn_refresh)
        lay.addLayout(combo_row)

        self._lbl_probe = QLabel("nao conectado")
        self._lbl_probe.setWordWrap(True)
        self._lbl_probe.setStyleSheet("color: gray; font-size: 11px;")
        lay.addWidget(self._lbl_probe)

        self._btn_connect = QPushButton("Conectar")
        self._btn_connect.setMinimumHeight(32)
        self._btn_connect.clicked.connect(self._toggle_connect)
        lay.addWidget(self._btn_connect)

        lay.addStretch()
        return widget

    # ── Aba "Instrumentos" ───────────────────────────────────────────────

    def _build_instrumentos_tab(self) -> QWidget:
        widget = QWidget()
        lay    = QVBoxLayout(widget)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        self._instruments_list = QListWidget()
        self._instruments_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self._instruments_list, stretch=1)

        self._btn_instruments = QPushButton("Gerenciar...")
        self._btn_instruments.clicked.connect(self._open_instrument_manager)
        lay.addWidget(self._btn_instruments)

        return widget

    # ── Aba "Testes" — projeto + suite embutida + plugins ────────────────

    def _build_testes_tab(self) -> QWidget:
        widget = QWidget()
        lay    = QVBoxLayout(widget)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        # Testes do projeto
        lay.addWidget(self._section_header("Testes do projeto"))

        self._project_tests_list = QListWidget()
        self._project_tests_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._project_tests_list.setMaximumHeight(110)
        self._project_tests_list.setToolTip(
            "Arquivos de teste associados ao projeto selecionado.\n"
            "Execute via: pytest <arquivo>"
        )
        lay.addWidget(self._project_tests_list)

        self._lbl_no_tests = QLabel("Nenhum teste configurado no projeto.")
        self._lbl_no_tests.setStyleSheet("color: #888; font-size: 11px;")
        self._lbl_no_tests.setVisible(True)
        lay.addWidget(self._lbl_no_tests)

        lay.addWidget(self._separator())

        # Suite embutida
        lay.addWidget(self._section_header("Testes embutidos"))

        self._suite_list = QListWidget()
        self._suite_list.setEnabled(False)
        self._suite_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._suite_list.setMaximumHeight(130)
        for test in STANDARD_SUITE:
            item = QListWidgetItem(test.name)
            item.setToolTip(test.description)
            self._suite_list.addItem(item)
        lay.addWidget(self._suite_list)

        lay.addWidget(self._separator())

        # Plugins
        lay.addWidget(self._section_header("Plugins"))

        self._btn_load_plugin = QPushButton("Carregar Plugin...")
        self._btn_load_plugin.clicked.connect(self._load_plugin)
        lay.addWidget(self._btn_load_plugin)

        self._plugin_list = QListWidget()
        self._plugin_list.setEnabled(False)
        self._plugin_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._plugin_list.setMaximumHeight(80)
        lay.addWidget(self._plugin_list)

        lay.addWidget(self._separator())

        # Macros
        lay.addWidget(self._section_header("Macros"))

        macro_btn_row = QHBoxLayout()
        self._btn_load_macro = QPushButton("Carregar...")
        self._btn_load_macro.setToolTip("Carrega um arquivo .py com macros (@macro)")
        self._btn_load_macro.clicked.connect(self._load_macro_file)
        macro_btn_row.addWidget(self._btn_load_macro)

        self._btn_reload_macros = QPushButton("Recarregar")
        self._btn_reload_macros.setToolTip("Recarrega a pasta macros/ do projeto")
        self._btn_reload_macros.clicked.connect(self._reload_macros_dir)
        macro_btn_row.addWidget(self._btn_reload_macros)
        lay.addLayout(macro_btn_row)

        self._macro_list = QListWidget()
        self._macro_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._macro_list.setToolTip(
            "Macros disponíveis para uso nos testes.\n"
            "Clique duplo para ver a assinatura completa."
        )
        self._macro_list.itemDoubleClicked.connect(self._show_macro_detail)
        lay.addWidget(self._macro_list, stretch=1)

        return widget

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        lay.addWidget(self._section_header("Resultados"))

        self._table = QTableWidget(0, len(_COL_HEADERS))
        self._table.setHorizontalHeaderLabels(_COL_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_MESSAGE, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_STATUS, QHeaderView.ResizeMode.Fixed
        )
        self._table.setColumnWidth(_COL_STATUS, 72)
        self._table.setColumnWidth(_COL_NAME,   110)
        self._table.setColumnWidth(_COL_MS,      56)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        lay.addWidget(self._table, stretch=1)

        self._progress = QProgressBar()
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("%v / %m")
        lay.addWidget(self._progress)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self._btn_report = QPushButton("Relatório ▾")
        self._btn_report.setMinimumHeight(36)
        self._btn_report.setEnabled(False)
        report_menu = QMenu(self._btn_report)
        report_menu.addAction("HTML (.html)…",  self._generate_html_report)
        report_menu.addAction("Word (.docx)…",  self._generate_docx_report)
        report_menu.addAction("PDF (.pdf)…",    self._generate_pdf_report)
        self._btn_report.setMenu(report_menu)
        btn_row.addWidget(self._btn_report)

        self._btn_export = QPushButton("Exportar...")
        self._btn_export.setMinimumHeight(36)
        self._btn_export.setEnabled(False)
        self._btn_export.clicked.connect(self._export_results)
        btn_row.addWidget(self._btn_export)

        self._btn_run = QPushButton("Executar Suite  [F5]")
        self._btn_run.setMinimumHeight(36)
        self._btn_run.setEnabled(False)
        self._btn_run.clicked.connect(self._run_suite)
        btn_row.addWidget(self._btn_run)

        self._btn_abort = QPushButton("Cancelar")
        self._btn_abort.setMinimumHeight(36)
        self._btn_abort.setEnabled(False)
        self._btn_abort.clicked.connect(self._runner.abort)
        btn_row.addWidget(self._btn_abort)

        lay.addLayout(btn_row)
        return panel

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)

        self._sb_board = QLabel("Placa: —")
        self._sb_board.setMinimumWidth(200)
        bar.addPermanentWidget(self._sb_board)

        self._sb_probe = QLabel("Probe: —")
        self._sb_probe.setMinimumWidth(240)
        bar.addPermanentWidget(self._sb_probe)

        self._sb_suite = QLabel("Suite: —")
        self._sb_suite.setMinimumWidth(180)
        bar.addPermanentWidget(self._sb_suite)

    # ------------------------------------------------------------------
    # Conexão de sinais
    # ------------------------------------------------------------------

    def _wire_signals(self) -> None:
        self._device.probe_connected.connect(self._on_probe_connected)
        self._device.probe_disconnected.connect(self._on_probe_disconnected)
        self._device.probe_error.connect(self._on_probe_error)

        self._runner.suite_started.connect(self._on_suite_started)
        self._runner.test_started.connect(self._on_test_started)
        self._runner.test_finished.connect(self._on_test_finished)
        self._runner.suite_finished.connect(self._on_suite_finished)

    # ------------------------------------------------------------------
    # Inicialização de projetos
    # ------------------------------------------------------------------

    def _load_projects(self) -> None:
        """Carrega projetos da pasta projects/ e popula o ComboBox."""
        # Indexa por nome normalizado (minúsculas, hífen→sublinhado)
        # para tolerância a diferenças de capitalização nos JSONs
        self._boards_by_name = {
            _board_key(b.name): b for b in find_boards()
        }
        projects = find_projects()

        self._combo_projects.blockSignals(True)
        self._combo_projects.clear()
        if projects:
            for p in projects:
                self._combo_projects.addItem(
                    f"{p.project_code}  —  {p.name}", userData=p
                )
        else:
            self._combo_projects.addItem("(nenhum projeto — clique em Novo...)", userData=None)
        self._combo_projects.blockSignals(False)

        if projects:
            self._combo_projects.setCurrentIndex(0)
            self._on_project_changed(0)

        self._btn_edit_project.setEnabled(bool(projects))

    # ------------------------------------------------------------------
    # Handlers de projeto
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_project_changed(self, index: int) -> None:
        project: ProjectConfig | None = self._combo_projects.itemData(index)
        if project is None:
            return

        self._active_project = project
        set_active_project(project)

        # Resolve e aplica a placa referenciada
        board = self._boards_by_name.get(_board_key(project.board))
        if board:
            self._active_board = board
            set_active_board(board)
            self._lbl_board_name.setText(board.name)
            self._lbl_board_name.setStyleSheet("font-size: 11px;")
        else:
            self._active_board = None
            self._lbl_board_name.setText(f"⚠ placa '{project.board}' não encontrada")
            self._lbl_board_name.setStyleSheet("color: red; font-size: 11px;")

        self._lbl_project_code.setText(project.project_code)
        self._lbl_proj_desc.setText(project.description)
        self._sb_board.setText(f"{project.project_code}  —  {project.name}")
        self.setWindowTitle(
            f"Bring-up  {project.project_code} — {project.name}  v{__version__}"
        )

        # Auto-load do perfil de análise vinculado ao projeto
        self._load_project_analysis_config(project)

        self._refresh_project_tests()
        self._refresh_button_states()
        logger.info(
            "Projeto selecionado: %s  board=%s", project.name, project.board
        )

    # ------------------------------------------------------------------
    # Handlers de probe
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_probe_connected(self, description: str) -> None:
        logger.info("Probe conectado: %s", description)
        self._lbl_probe.setText(description)
        self._lbl_probe.setStyleSheet("color: green; font-weight: bold; font-size: 11px;")
        self._btn_connect.setText("Desconectar")
        self._act_connect.setText("Desconectar probe")
        self._sb_probe.setText(f"Probe: {description}")
        self.statusBar().showMessage("Probe conectado.", 3000)
        self._refresh_button_states()

    @Slot()
    def _on_probe_disconnected(self) -> None:
        logger.info("Probe desconectado.")
        self._lbl_probe.setText("nao conectado")
        self._lbl_probe.setStyleSheet("color: gray; font-size: 11px;")
        self._btn_connect.setText("Conectar")
        self._act_connect.setText("Conectar probe")
        self._sb_probe.setText("Probe: —")
        self._sb_suite.setText("Suite: —")
        self.statusBar().showMessage("Probe desconectado.", 3000)
        self._refresh_button_states()

    @Slot(str)
    def _on_probe_error(self, message: str) -> None:
        logger.error("Erro de probe: %s", message)
        self._lbl_probe.setText(f"Erro: {message}")
        self._lbl_probe.setStyleSheet("color: red; font-size: 11px;")
        self._sb_probe.setText("Probe: ERRO")
        self.statusBar().showMessage(f"Erro: {message}", 5000)
        self._refresh_button_states()

    # ------------------------------------------------------------------
    # Handlers da suite
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_suite_started(self, total: int) -> None:
        self._total_tests = total
        self._pass_count  = 0
        self._fail_count  = 0
        self._table.setRowCount(0)
        self._progress.setMaximum(total)
        self._progress.setValue(0)
        self._sb_suite.setText(f"Suite: executando {total} testes...")
        self._refresh_button_states()

    @Slot(str)
    def _on_test_started(self, name: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, _COL_STATUS,  _cell("..."))
        self._table.setItem(row, _COL_NAME,    _cell(name))
        self._table.setItem(row, _COL_MS,      _cell(""))
        self._table.setItem(row, _COL_MESSAGE, _cell("executando..."))
        self._table.scrollToBottom()
        self._suite_list.setCurrentRow(
            next((i for i, t in enumerate(STANDARD_SUITE) if t.name == name), -1)
        )

    @Slot(object)
    def _on_test_finished(self, result: TestResult) -> None:
        row = self._table.rowCount() - 1
        bg = QBrush(_STATUS_BG[result.status])
        for col in range(len(_COL_HEADERS)):
            item = self._table.item(row, col)
            if item:
                item.setBackground(bg)
        self._table.item(row, _COL_STATUS).setText(_STATUS_LABEL[result.status])
        self._table.item(row, _COL_MS).setText(f"{result.duration_ms:.1f}")
        self._table.item(row, _COL_MESSAGE).setText(result.message)

        if result.status == TestStatus.PASS:
            self._pass_count += 1
        elif result.status in (TestStatus.FAIL, TestStatus.ERROR):
            self._fail_count += 1

        self._progress.setValue(self._pass_count + self._fail_count)

    @Slot(object)
    def _on_suite_finished(self, results: list[TestResult]) -> None:
        self._last_results = results
        counts  = summarize(results)
        n_pass  = counts[TestStatus.PASS]
        n_fail  = counts[TestStatus.FAIL]
        n_error = counts[TestStatus.ERROR]
        n_skip  = counts[TestStatus.SKIP]
        total   = len(results)

        summary = f"Suite: {n_pass}/{total} PASS"
        if n_fail:
            summary += f"  {n_fail} FAIL"
        if n_error:
            summary += f"  {n_error} ERROR"
        if n_skip:
            summary += f"  {n_skip} SKIP"
        self._sb_suite.setText(summary)

        if n_fail + n_error == 0:
            self.statusBar().showMessage(
                f"Suite concluida — {n_pass}/{total} testes passaram.", 5000
            )
        else:
            self.statusBar().showMessage(
                f"Suite concluida com {n_fail + n_error} falha(s).", 8000
            )

        self._suite_list.clearSelection()
        self._refresh_button_states()

    # ------------------------------------------------------------------
    # Ações dos botões
    # ------------------------------------------------------------------

    def _refresh_probes(self) -> None:
        probes = self._device.list_probes()
        self._combo_probes.clear()
        for p in probes:
            self._combo_probes.addItem(str(p), userData=p.unique_id)
        if not probes:
            self.statusBar().showMessage("Nenhum probe detectado.", 3000)
        else:
            self.statusBar().showMessage(
                f"{len(probes)} probe(s) encontrado(s).", 3000
            )

    def _toggle_connect(self) -> None:
        if self._device.is_connected:
            self._device.disconnect()
        else:
            if self._active_board is None:
                self.statusBar().showMessage("Selecione uma placa antes de conectar.", 4000)
                return
            uid = self._combo_probes.currentData()
            self.statusBar().showMessage("Conectando ao probe...", 0)
            self._btn_connect.setEnabled(False)
            self._device.connect(board=self._active_board, uid=uid)

    def _run_suite(self) -> None:
        if self._runner.is_running:
            return
        suite = STANDARD_SUITE + tuple(self._plugin_tests)
        try:
            self._runner.run(suite)
        except RuntimeError as exc:
            self.statusBar().showMessage(str(exc), 5000)

    def _load_plugin(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Carregar Plugin de Testes", "", "Python (*.py)"
        )
        if not path:
            return
        try:
            from tests_builtin.loader import PluginLoader
            tests = PluginLoader.load_from_file(Path(path))
            self._plugin_tests.extend(tests)
            for t in tests:
                item = QListWidgetItem(t.name)
                item.setToolTip(t.description)
                self._plugin_list.addItem(item)
            self.statusBar().showMessage(
                f"Plugin carregado: {len(tests)} teste(s) de '{Path(path).name}'.", 5000
            )
        except Exception as exc:
            self.statusBar().showMessage(f"Erro ao carregar plugin: {exc}", 6000)

    def _new_project(self) -> None:
        dlg = ProjectEditorDialog(self)
        if dlg.exec() == ProjectEditorDialog.DialogCode.Accepted:
            self._load_projects()

    def _edit_project(self) -> None:
        project: ProjectConfig | None = self._combo_projects.currentData()
        if project is None:
            return
        dlg = ProjectEditorDialog(self, project=project)
        if dlg.exec() == ProjectEditorDialog.DialogCode.Accepted:
            self._load_projects()

    def _refresh_project_tests(self) -> None:
        project = self._active_project
        self._project_tests_list.clear()
        if project and project.test_paths:
            for path in project.test_paths:
                self._project_tests_list.addItem(path)
            self._lbl_no_tests.setVisible(False)
            self._project_tests_list.setVisible(True)
        else:
            self._lbl_no_tests.setVisible(True)
            self._project_tests_list.setVisible(False)

    def _load_project_analysis_config(self, project: ProjectConfig) -> None:
        """Carrega e ativa o perfil de análise vinculado ao projeto."""
        if not project.analysis_config:
            set_active_analysis_config(None)
            self._lbl_analysis_cfg.setText("(nenhum)")
            self._lbl_analysis_cfg.setStyleSheet("font-size: 11px; color: #888;")
            return

        try:
            path = config_path(project.analysis_config)
            cfg  = AnalysisConfig.load(path)
            set_active_analysis_config(cfg)
            self._lbl_analysis_cfg.setText(cfg.name)
            self._lbl_analysis_cfg.setStyleSheet("font-size: 11px; color: #1a6b1a;")
            logger.info("Perfil de análise carregado: %s", cfg.name)
        except Exception as exc:
            set_active_analysis_config(None)
            self._lbl_analysis_cfg.setText(f"⚠ {project.analysis_config} não encontrado")
            self._lbl_analysis_cfg.setStyleSheet("font-size: 11px; color: red;")
            logger.warning("Perfil de análise não carregado: %s", exc)

    def _open_analysis_config(self) -> None:
        """Abre o editor de perfis de análise."""
        proj = self._active_project
        active_cfg_name = proj.analysis_config if proj else ""
        dlg = AnalysisConfigDialog(self, active_config_name=active_cfg_name)

        if dlg.exec() != AnalysisConfigDialog.DialogCode.Accepted:
            return

        fname = dlg.selected_filename
        if not fname or proj is None:
            return

        # Vincula o perfil ao projeto e salva
        proj.analysis_config = fname
        try:
            save_project(proj)
            self._load_project_analysis_config(proj)
            self.statusBar().showMessage(
                f"Perfil '{fname}' vinculado ao projeto e salvo.", 4000
            )
        except Exception as exc:
            self.statusBar().showMessage(f"Erro ao salvar projeto: {exc}", 6000)

    # ── Macros ───────────────────────────────────────────────────────────────

    def _auto_load_macros(self) -> None:
        """Carrega automaticamente os arquivos *.py da pasta macros/."""
        reg = MacroRegistry.instance()
        try:
            n = reg.load_directory(_MACROS_DIR)
            if n:
                logger.info("Auto-carregamento: %d macro(s) de macros/", n)
        except Exception as exc:
            logger.warning("Erro ao auto-carregar macros: %s", exc)
        self._refresh_macro_list()

    def _load_macro_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Carregar arquivo de macros", str(_MACROS_DIR), "Python (*.py)"
        )
        if not path:
            return
        reg = MacroRegistry.instance()
        try:
            entries = reg.load_file(Path(path))
            self._refresh_macro_list()
            self.statusBar().showMessage(
                f"{len(entries)} macro(s) carregada(s) de '{Path(path).name}'.", 5000
            )
        except Exception as exc:
            self.statusBar().showMessage(f"Erro ao carregar macros: {exc}", 6000)

    def _reload_macros_dir(self) -> None:
        reg = MacroRegistry.instance()
        reg.reset()
        self._auto_load_macros()
        self.statusBar().showMessage(
            f"{len(reg)} macro(s) recarregada(s) de macros/.", 4000
        )

    def _refresh_macro_list(self) -> None:
        reg = MacroRegistry.instance()
        self._macro_list.clear()
        for entry in reg.all_entries():
            item = QListWidgetItem(f"[{entry.category}]  {entry.name}{entry.signature_str()}")
            item.setToolTip(entry.tooltip())
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._macro_list.addItem(item)

    def _show_macro_detail(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.ItemDataRole.UserRole)
        if entry is None:
            return
        params_text = "\n".join(
            f"  {p.signature_str()}" for p in entry.params
        ) or "  (sem parâmetros além de pal)"

        from PySide6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle(f"Macro: {entry.name}")
        msg.setTextFormat(Qt.TextFormat.PlainText)
        msg.setText(
            f"Nome:      {entry.name}\n"
            f"Categoria: {entry.category}\n"
            f"Origem:    {Path(entry.source_file).name if entry.source_file else '—'}\n"
            f"\nDescrição:\n  {entry.description or '—'}\n"
            f"\nParâmetros (além de pal):\n{params_text}\n"
            f"\nUso no teste:\n"
            f"  from core.macros import get_macro\n"
            f"  get_macro(\"{entry.name}\")(pal)"
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _open_instrument_manager(self) -> None:
        dlg = InstrumentManagerDialog(self)
        dlg.exec()

    def _refresh_instruments_panel(self) -> None:
        registry = InstrumentRegistry.instance()
        self._instruments_list.clear()
        for cfg in registry.configs():
            connected = registry.is_connected(cfg.name)
            bullet = "●" if connected else "○"
            label  = f"{bullet} {cfg.name}"
            if cfg.description:
                label += f"  —  {cfg.description}"
            self._instruments_list.addItem(label)

    def _export_results(self) -> None:
        if not self._last_results:
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Exportar resultados",
            "resultados",
            "JSON (*.json);;CSV (*.csv)",
        )
        if not path:
            return
        dest = Path(path)
        try:
            if "CSV" in selected_filter or dest.suffix.lower() == ".csv":
                self._export_csv(dest)
            else:
                self._export_json(dest)
            self.statusBar().showMessage(f"Exportado: {dest.name}", 4000)
        except OSError as exc:
            self.statusBar().showMessage(f"Erro ao exportar: {exc}", 6000)

    # ── Fábrica de metadados comuns ──────────────────────────────────────────

    def _report_kwargs(self) -> dict:
        proj  = self._active_project
        board = self._active_board
        return dict(
            title        = f"Relatório de Testes — {proj.project_code if proj else ''}",
            project_name = proj.name         if proj else "",
            project_code = proj.project_code if proj else "",
            board_name   = board.name        if board else "",
        )

    def _report_default_stem(self) -> str:
        proj = self._active_project
        code = proj.project_code if proj else "relatorio"
        return f"relatorio_{code}"

    # ── Handlers de relatório ────────────────────────────────────────────────

    def _generate_html_report(self) -> None:
        if not self._last_results:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Relatório HTML",
            f"{self._report_default_stem()}.html",
            "HTML (*.html)",
        )
        if not path:
            return
        try:
            saved = HtmlReport(**self._report_kwargs()).save(
                Path(path), self._last_results
            )
            self.statusBar().showMessage(f"Relatório salvo: {saved.name}", 5000)
            import webbrowser
            webbrowser.open(saved.as_uri())
        except Exception as exc:
            self.statusBar().showMessage(f"Erro ao gerar relatório HTML: {exc}", 6000)

    def _generate_docx_report(self) -> None:
        if not self._last_results:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Relatório Word",
            f"{self._report_default_stem()}.docx",
            "Word (*.docx)",
        )
        if not path:
            return
        try:
            saved = DocxReport(**self._report_kwargs()).save(
                Path(path), self._last_results
            )
            self.statusBar().showMessage(f"Relatório Word salvo: {saved.name}", 5000)
            import os
            os.startfile(str(saved))
        except Exception as exc:
            self.statusBar().showMessage(f"Erro ao gerar relatório Word: {exc}", 6000)

    def _generate_pdf_report(self) -> None:
        if not self._last_results:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Relatório PDF",
            f"{self._report_default_stem()}.pdf",
            "PDF (*.pdf)",
        )
        if not path:
            return
        try:
            saved = PdfReport(**self._report_kwargs()).save(
                Path(path), self._last_results
            )
            self.statusBar().showMessage(f"Relatório PDF salvo: {saved.name}", 5000)
            import os
            os.startfile(str(saved))
        except Exception as exc:
            self.statusBar().showMessage(f"Erro ao gerar relatório PDF: {exc}", 6000)

    def _export_json(self, dest: Path) -> None:
        proj  = self._active_project
        board = self._active_board
        data  = {
            "project_code": proj.project_code if proj else "—",
            "project_name": proj.name         if proj else "—",
            "board":        board.name        if board else "—",
            "results": [r.to_dict() for r in self._last_results],
        }
        dest.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _export_csv(self, dest: Path) -> None:
        proj  = self._active_project
        board = self._active_board
        with dest.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "project_code", "project_name", "board",
                "status", "name", "duration_ms", "message", "measured", "expected",
            ])
            for r in self._last_results:
                writer.writerow([
                    proj.project_code if proj else "—",
                    proj.name         if proj else "—",
                    board.name        if board else "—",
                    r.status.value, r.name, r.duration_ms,
                    r.message, r.measured, r.expected,
                ])

    # ------------------------------------------------------------------
    # Estado dos botões
    # ------------------------------------------------------------------

    def _refresh_button_states(self) -> None:
        connected   = self._device.is_connected
        running     = self._runner.is_running
        has_board   = self._active_board is not None
        has_results = bool(self._last_results)

        self._combo_projects.setEnabled(not connected and not running)
        self._btn_connect.setEnabled(has_board and not running)
        self._btn_refresh.setEnabled(not running and not connected)
        self._btn_run.setEnabled(connected and not running)
        self._btn_abort.setEnabled(running)
        self._btn_export.setEnabled(has_results and not running)
        self._btn_report.setEnabled(has_results and not running)
        self._act_run.setEnabled(connected and not running)
        self._act_abort.setEnabled(running)
        self._act_export.setEnabled(has_results and not running)

    # ------------------------------------------------------------------
    # Helpers de layout
    # ------------------------------------------------------------------

    @staticmethod
    def _section_header(text: str) -> QLabel:
        lbl = QLabel(text)
        font = lbl.font()
        font.setBold(True)
        lbl.setFont(font)
        return lbl

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    # ------------------------------------------------------------------
    # Fechar janela
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._runner.is_running:
            self._runner.abort()
        if self._device.is_connected:
            self._device.disconnect()
        registry = InstrumentRegistry.instance()
        registry.disconnect_all()
        registry.save()
        super().closeEvent(event)


def _board_key(name: str) -> str:
    """Normaliza nome de placa para matching tolerante (minúsculas, hífen→_)."""
    return name.lower().replace("-", "_").replace(" ", "_")


def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item
