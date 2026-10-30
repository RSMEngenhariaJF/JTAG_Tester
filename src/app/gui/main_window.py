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
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QStandardPaths, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QFont, QKeySequence
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
    QMessageBox,
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
from app.gui.test_detail import TestDetailPanel, result_name
from core.macros.registry import MacroRegistry, _MACROS_DIR
from app.services.device import PROBE_FT2232H, DeviceService, ProbeInfo
from app.services.runner import TestRunnerService
from core.board.config import BoardConfig, set_active_board
from core.board.loader import find_boards
from core.instruments.registry import InstrumentRegistry
from core.analysis.config      import (
    AnalysisConfig,
    config_path,
    get_active_analysis_config,
    set_active_analysis_config,
)
from core.analysis.criteria_report import criteria_dict
from core.analysis.report      import HtmlReport
from core.analysis.report_docx import DocxReport
from core.analysis.report_pdf  import PdfReport
from core.project.config import ProjectConfig, set_active_project
from core.project.loader import find_projects, save_project
from core.target import STM32_DEV_IDS, McuInfo
from tests_builtin import STANDARD_SUITE, summarize
from tests_builtin.base import BuiltinTest, TestResult, TestStatus
from tests_builtin.plan import build_plan
from app.gui.log_window import LogWindow
from app.log_buffer import get_log_buffer

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
        self._results_by_name: dict[str, TestResult] = {}   # último resultado de cada teste
        self._suite_t0: datetime | None = None               # início/fim da última suíte
        self._suite_t1: datetime | None = None
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

        m_view = bar.addMenu("E&xibir")
        act_logs = QAction("Logs...", self)
        act_logs.setShortcut(QKeySequence("Ctrl+L"))
        act_logs.triggered.connect(self._open_logs)
        m_view.addAction(act_logs)

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

        btn_row = QHBoxLayout()
        self._btn_identify = QPushButton("Identificar MCU")
        self._btn_identify.setMinimumHeight(32)
        self._btn_identify.setToolTip(
            "Lê os registradores de ID do microcontrolador ligado ao probe (sem halt)"
        )
        self._btn_identify.clicked.connect(self._identify_mcu)
        btn_row.addWidget(self._btn_identify)

        self._btn_connect = QPushButton("Conectar")
        self._btn_connect.setMinimumHeight(32)
        self._btn_connect.clicked.connect(self._toggle_connect)
        btn_row.addWidget(self._btn_connect)
        lay.addLayout(btn_row)

        self._lbl_mcu = QLabel("MCU: não identificado")
        self._lbl_mcu.setWordWrap(True)
        self._lbl_mcu.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._lbl_mcu.setStyleSheet("color: gray; font-size: 11px;")
        lay.addWidget(self._lbl_mcu)

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
        lay.addWidget(self._section_header("Plano e testes do projeto"))

        self._project_tests_list = QListWidget()
        self._project_tests_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._project_tests_list.setMaximumHeight(160)
        self._project_tests_list.setToolTip(
            "▶ = instância do plano de testes (roda com Executar Suite)\n"
            "Demais = arquivos pytest associados ao projeto.\n"
            "Clique: detalhes no painel abaixo dos resultados. Clique duplo: editar o plano."
        )
        self._project_tests_list.currentRowChanged.connect(self._show_plan_detail)
        self._project_tests_list.itemDoubleClicked.connect(lambda _i: self._edit_plan())
        lay.addWidget(self._project_tests_list)

        self._lbl_no_tests = QLabel("Nenhum teste configurado no projeto.")
        self._lbl_no_tests.setStyleSheet("color: #888; font-size: 11px;")
        self._lbl_no_tests.setVisible(True)
        lay.addWidget(self._lbl_no_tests)

        self._btn_edit_plan = QPushButton("Editar plano de testes...")
        self._btn_edit_plan.setToolTip(
            "Escolhe os testes parametrizáveis do projeto e em quais pinos/valores\n"
            "cada um é aplicado (ex.: Piscar LED nos LEDs indicadores)."
        )
        self._btn_edit_plan.clicked.connect(lambda: self._edit_plan())
        lay.addWidget(self._btn_edit_plan)

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
        self._table.itemSelectionChanged.connect(self._show_result_detail)

        # Resultados em cima, detalhes do teste selecionado embaixo
        self._detail = TestDetailPanel()
        self._results_split = QSplitter(Qt.Orientation.Vertical)
        self._results_split.setChildrenCollapsible(False)
        self._results_split.addWidget(self._table)
        self._results_split.addWidget(self._detail)
        self._results_split.setStretchFactor(0, 3)
        self._results_split.setStretchFactor(1, 2)
        lay.addWidget(self._results_split, stretch=1)

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

        self._btn_pdf = QPushButton("Exportar PDF")
        self._btn_pdf.setMinimumHeight(36)
        self._btn_pdf.setEnabled(False)
        self._btn_pdf.setToolTip("Salva o relatório da última execução em PDF (A4)")
        self._btn_pdf.clicked.connect(self._generate_pdf_report)
        btn_row.addWidget(self._btn_pdf)

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

        self._sb_logs = QPushButton("Logs")
        self._sb_logs.setFlat(True)
        self._sb_logs.setToolTip("Abrir a janela de logs (Ctrl+L)")
        self._sb_logs.clicked.connect(self._open_logs)
        bar.addPermanentWidget(self._sb_logs)

        # Registros chegam de qualquer thread: o sinal leva a contagem para a GUI
        self._log_window: LogWindow | None = None
        self._log_bridge = _LogCountBridge(self)
        self._log_bridge.changed.connect(self._update_log_counter,
                                         Qt.ConnectionType.QueuedConnection)
        self._log_listener = lambda _entry: self._log_bridge.changed.emit()
        get_log_buffer().add_listener(self._log_listener)
        self._update_log_counter()

    # ------------------------------------------------------------------
    # Conexão de sinais
    # ------------------------------------------------------------------

    def _wire_signals(self) -> None:
        self._device.probe_connected.connect(self._on_probe_connected)
        self._device.probe_disconnected.connect(self._on_probe_disconnected)
        self._device.probe_error.connect(self._on_probe_error)
        self._device.mcu_identified.connect(self._on_mcu_identified)

        self._runner.suite_started.connect(self._on_suite_started)
        self._runner.test_started.connect(self._on_test_started)
        self._runner.test_finished.connect(self._on_test_finished)
        self._runner.suite_finished.connect(self._on_suite_finished)

    # ------------------------------------------------------------------
    # Inicialização de projetos
    # ------------------------------------------------------------------

    def _load_projects(self, select_code: str | None = None) -> None:
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
            idx = next((i for i, p in enumerate(projects)
                        if select_code and p.project_code == select_code), 0)
            self._combo_projects.setCurrentIndex(idx)
            self._on_project_changed(idx)

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
        if self._lbl_mcu.text() == "MCU: identificando...":
            self._lbl_mcu.setText("MCU: não identificado")
        self._refresh_button_states()

    @Slot(object)
    def _on_mcu_identified(self, info: McuInfo) -> None:
        logger.info("MCU identificado: %s", info.summary().replace("\n", " | "))
        text = info.summary()
        style = "color: green; font-size: 11px;"
        board = self._active_board
        if board is not None and info.dev_id is not None:
            if info.dev_id != board.expected_dev_id:
                expected = STM32_DEV_IDS.get(board.expected_dev_id, "?")
                text += (
                    f"\n⚠ Não confere com a placa do projeto ({board.name}): "
                    f"esperado DEV_ID 0x{board.expected_dev_id:03X} ({expected})"
                )
                style = "color: #b35900; font-weight: bold; font-size: 11px;"
            else:
                text += f"\n✓ Confere com a placa do projeto ({board.name})"
        elif info.dev_id is None:
            text += "\nDEV_ID não lido (chip fora da tabela STM32)"
        self._lbl_mcu.setText(text)
        self._lbl_mcu.setStyleSheet(style)
        self.statusBar().showMessage(f"MCU identificado: {info.name}", 5000)

    # ------------------------------------------------------------------
    # Handlers da suite
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_suite_started(self, total: int) -> None:
        self._total_tests = total
        self._pass_count  = 0
        self._fail_count  = 0
        self._suite_t0 = datetime.now().astimezone()
        self._suite_t1 = None
        self._table.setRowCount(0)
        self._results_by_name.clear()
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
        tip = _measurements_tooltip(result)
        for col in range(len(_COL_HEADERS)):
            item = self._table.item(row, col)
            if item and tip:
                item.setToolTip(tip)
        self._table.item(row, _COL_NAME).setData(Qt.ItemDataRole.UserRole, result)
        self._results_by_name[result.name] = result
        if self._detail.current == result.name:          # painel aberto neste teste
            self._refresh_detail(result.name)

        if result.status in (TestStatus.FAIL, TestStatus.ERROR):
            log = logger.error if result.status == TestStatus.ERROR else logger.warning
            extra = f"  params={result.params}" if result.params else ""
            log("Teste %s: %s — %s%s", result.status.value, result.name, result.message, extra)

        if result.status == TestStatus.PASS:
            self._pass_count += 1
        elif result.status in (TestStatus.FAIL, TestStatus.ERROR):
            self._fail_count += 1

        self._progress.setValue(self._pass_count + self._fail_count)

    @Slot(object)
    def _on_suite_finished(self, results: list[TestResult]) -> None:
        self._last_results = results
        self._suite_t1 = datetime.now().astimezone()
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
            self._combo_probes.addItem(str(p), userData=p)
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
            probe: ProbeInfo | None = self._combo_probes.currentData()
            if probe is not None and probe.kind == PROBE_FT2232H:
                self.statusBar().showMessage(
                    "Conexão completa via FT2232H ainda não suportada — "
                    "use 'Identificar MCU'.", 6000
                )
                return
            self.statusBar().showMessage("Conectando ao probe...", 0)
            self._btn_connect.setEnabled(False)
            self._device.connect(
                board=self._active_board,
                uid=probe.unique_id if probe else None,
            )

    def _identify_mcu(self) -> None:
        probe: ProbeInfo | None = self._combo_probes.currentData()
        self.statusBar().showMessage("Identificando MCU...", 0)
        self._lbl_mcu.setText("MCU: identificando...")
        self._lbl_mcu.setStyleSheet("color: gray; font-size: 11px;")
        self._device.identify(probe)

    def _run_suite(self) -> None:
        if self._runner.is_running:
            return
        # Ordem: embutidos → plano de testes do projeto → plugins carregados à mão
        plan = tuple(build_plan(self._active_project))
        suite = STANDARD_SUITE + plan + tuple(self._plugin_tests)
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
            configurable = [t for t in tests if t.params]
            if configurable and self._offer_plan(path, configurable):
                tests = [t for t in tests if not t.params]
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

    def _offer_plan(self, path: str, tests: list[BuiltinTest]) -> bool:
        """Teste com parâmetros precisa de pinos/valores: propõe o plano do projeto."""
        from tests_builtin.plan import make_ref

        if self._active_project is None:
            QMessageBox.information(
                self, "Teste configurável",
                "Este arquivo tem testes com parâmetros (pinos, valores).\n"
                "Selecione um projeto para adicioná-los ao plano de testes."
            )
            return False
        names = ", ".join(t.name for t in tests)
        answer = QMessageBox.question(
            self, "Teste configurável",
            f"{names} tem parâmetros (pinos, ciclos...).\n\n"
            f"Adicionar ao plano de testes do projeto "
            f"\"{self._active_project.name}\" e escolher os pinos agora?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self._edit_plan([make_ref(path, type(t).__name__) for t in tests])
        return True

    def _edit_plan(self, add_refs: list[str] | tuple[str, ...] = ()) -> None:
        """Abre o editor do projeto ativo direto na aba "Plano de testes"."""
        project: ProjectConfig | None = self._combo_projects.currentData()
        if project is None:
            self.statusBar().showMessage("Selecione ou crie um projeto primeiro.", 4000)
            return
        dlg = ProjectEditorDialog(self, project=project)
        dlg.open_plan(add_refs)
        if dlg.exec() == ProjectEditorDialog.DialogCode.Accepted:
            self._load_projects(select_code=project.project_code)

    def _edit_project(self) -> None:
        project: ProjectConfig | None = self._combo_projects.currentData()
        if project is None:
            return
        dlg = ProjectEditorDialog(self, project=project)
        if dlg.exec() == ProjectEditorDialog.DialogCode.Accepted:
            self._load_projects(select_code=project.project_code)

    # ── Painel de detalhes do teste ───────────────────────────────────────

    def _plan_entry_for(self, name: str):
        """Entrada do plano cujo resultado se chama `name` (None se não for do plano)."""
        project = self._active_project
        if project is None:
            return None
        return next((e for e in project.test_plan if result_name(e) == name), None)

    def _show_plan_detail(self, row: int) -> None:
        project = self._active_project
        if project is None or not 0 <= row < len(project.test_plan):
            return                                   # linha de arquivo pytest: sem detalhes
        entry = project.test_plan[row]
        self._detail.show_entry(entry, project, self._results_by_name.get(result_name(entry)))

    def _show_result_detail(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        item = self._table.item(rows[0].row(), _COL_NAME)
        result = item.data(Qt.ItemDataRole.UserRole) if item else None
        if result is not None:
            self._refresh_detail(result.name, result)

    def _refresh_detail(self, name: str, result: TestResult | None = None) -> None:
        result = result or self._results_by_name.get(name)
        entry = self._plan_entry_for(name)
        if entry is not None:
            self._detail.show_entry(entry, self._active_project, result)
        elif result is not None:
            self._detail.show_result(result)

    def _refresh_project_tests(self) -> None:
        project = self._active_project
        self._detail.clear()
        self._project_tests_list.clear()
        if project and (project.test_paths or project.test_plan):
            for entry in project.test_plan:
                params = ", ".join(
                    f"{k}={'+'.join(v) if isinstance(v, list) else v}"
                    for k, v in entry.params.items()
                )
                reps = f"  x{entry.repeat}" if entry.repeat > 1 else ""
                item = QListWidgetItem(
                    f"{'▶' if entry.enabled else '⏸'} {entry.label or entry.test}{reps}"
                )
                item.setToolTip(f"{entry.test}\n{params}")
                self._project_tests_list.addItem(item)
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

    def _open_logs(self) -> None:
        if self._log_window is not None and self._log_window.isVisible():
            self._log_window.raise_()
            self._log_window.activateWindow()
            return
        self._log_window = LogWindow(self, context_provider=self._log_context,
                                     save_path_provider=self._ask_save_path)
        self._log_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._log_window.destroyed.connect(lambda *_: setattr(self, "_log_window", None))
        self._log_window.show()

    def _update_log_counter(self) -> None:
        buf = get_log_buffer()
        erros, avisos = buf.count("ERROR"), buf.count("WARNING") - buf.count("ERROR")
        if erros:
            self._sb_logs.setText(f"⚠ Logs: {erros} erro(s)")
            self._sb_logs.setStyleSheet("color: #C00000; font-weight: bold;")
        elif avisos:
            self._sb_logs.setText(f"Logs: {avisos} aviso(s)")
            self._sb_logs.setStyleSheet("color: #B35900;")
        else:
            self._sb_logs.setText("Logs")
            self._sb_logs.setStyleSheet("")

    def _log_context(self) -> dict:
        """Contexto da sessão gravado no topo dos logs exportados."""
        import platform

        proj, board = self._active_project, self._active_board
        crit = get_active_analysis_config()
        return {
            "app_version": __version__,
            "python": platform.python_version(),
            "os": f"{platform.system()} {platform.release()}",
            "project": f"{proj.project_code} — {proj.name}" if proj else "",
            "board": board.name if board else "",
            "probe": self._sb_probe.text().removeprefix("Probe: "),
            "criteria": f"{crit.name} v{crit.version}" if crit else "",
            "suite": self._sb_suite.text().removeprefix("Suite: "),
        }

    def _export_results(self) -> None:
        if not self._last_results:
            return
        path, selected_filter = self._ask_save_path(
            "Exportar resultados",
            f"resultados_{self._report_default_stem().removeprefix('relatorio_')}",
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
            instruments  = _instrument_trace(),
            criteria     = criteria_dict(get_active_analysis_config()),
            environment  = self._report_environment(),
        )

    def _report_environment(self) -> dict:
        """Ambiente da execução para auditoria (sem dados pessoais: sem usuário/máquina)."""
        import hashlib
        import platform

        proj, board = self._active_project, self._active_board
        env: dict = {"software": f"JTAG Tester v{__version__}",
                     "python": platform.python_version()}
        try:
            import pyocd
            env["pyocd"] = pyocd.__version__
        except Exception:
            pass
        probe = self._lbl_probe.text()
        if probe and probe != "nao conectado":
            env["sonda"] = probe
        mcu = self._lbl_mcu.text().removeprefix("MCU: ")
        if mcu and "não identificado" not in mcu:
            env["mcu"] = mcu
        if board:
            env["placa"] = f"{board.name} (alvo {board.pyocd_target or board.target}, "\
                           f"conexão {board.connect_mode})"
        if proj:
            env["projeto"] = f"{proj.name} ({proj.project_code})"
            blob = json.dumps(proj.to_dict(), sort_keys=True, ensure_ascii=False)
            env["projeto_sha256"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16] + \
                " (configuração usada: pinos, plano, clocks)"
        cfg = get_active_analysis_config()
        env["perfil"] = f"{cfg.name} v{cfg.version}" if cfg else "nenhum (limites dos testes)"
        if self._suite_t0:
            env["inicio"] = self._suite_t0.isoformat(timespec="seconds")
        if self._suite_t1:
            env["fim"] = self._suite_t1.isoformat(timespec="seconds")
            if self._suite_t0:
                env["duracao"] = f"{(self._suite_t1 - self._suite_t0).total_seconds():.1f} s"
        if self._last_results:
            env["testes"] = str(len(self._last_results))
        return env

    def _report_default_stem(self) -> str:
        proj = self._active_project
        code = proj.project_code if proj else "sem_projeto"
        return f"relatorio_{code}_{datetime.now():%Y%m%d_%H%M}"

    def _ask_save_path(self, title: str, filename: str, filters: str) -> tuple[str, str]:
        """Diálogo de salvar que abre na última pasta usada (ou em Documentos)."""
        settings = _settings()
        start_dir = str(settings.value(_SETTINGS_LAST_DIR, "") or "")
        if not start_dir or not Path(start_dir).is_dir():
            start_dir = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.DocumentsLocation
            )
        path, selected = QFileDialog.getSaveFileName(
            self, title, str(Path(start_dir) / filename), filters
        )
        if path:
            settings.setValue(_SETTINGS_LAST_DIR, str(Path(path).parent))
        return path, selected

    # ── Handlers de relatório ────────────────────────────────────────────────

    def _generate_html_report(self) -> None:
        if not self._last_results:
            return
        path, _ = self._ask_save_path(
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
        path, _ = self._ask_save_path(
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
        path, _ = self._ask_save_path(
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
        except Exception as exc:
            logger.exception("Falha ao gerar relatório PDF")
            QMessageBox.warning(self, "Exportar PDF", f"Não foi possível gerar o PDF:\n{exc}")
            return
        self.statusBar().showMessage(f"Relatório PDF salvo: {saved.name}", 5000)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(saved)))

    def _export_json(self, dest: Path) -> None:
        proj  = self._active_project
        board = self._active_board
        data  = {
            "project_code": proj.project_code if proj else "—",
            "project_name": proj.name         if proj else "—",
            "board":        board.name        if board else "—",
            "instruments":  _instrument_trace(),
            "criteria":     criteria_dict(get_active_analysis_config()),
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
        self._btn_identify.setEnabled(not running)
        self._btn_refresh.setEnabled(not running and not connected)
        self._btn_run.setEnabled(connected and not running)
        self._btn_abort.setEnabled(running)
        self._btn_export.setEnabled(has_results and not running)
        self._btn_report.setEnabled(has_results and not running)
        self._btn_pdf.setEnabled(has_results and not running)
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
        get_log_buffer().remove_listener(self._log_listener)
        super().closeEvent(event)


_SETTINGS_LAST_DIR = "export/last_dir"


class _LogCountBridge(QObject):
    changed = Signal()


def _settings() -> QSettings:
    """Preferências do usuário (pasta da última exportação etc.)."""
    return QSettings("JTAG_Tester", "Bring-up Platform")


def _measurements_tooltip(result: TestResult) -> str:
    """Valor, limites, origem do limite e margem de cada medida (dica da linha)."""
    ms = getattr(result, "measurements", None)
    if not ms:
        return ""
    from core.analysis.criteria_report import detail_text, limits_text, margin_text
    from core.analysis.report import _fmt

    lines = []
    for m in ms:
        line = f"{m.status}  {m.name} = {_fmt(m.value, m.unit)}"
        if lim := limits_text(m, _fmt):
            line += f"   limite {lim}   margem {margin_text(m)}"
        if det := detail_text(m, _fmt):
            line += f"\n      {det}"
        lines.append(line)
    return "\n".join(lines)


def _instrument_trace() -> list[dict]:
    """Identificação e calibração dos instrumentos conectados na sessão."""
    return [rec.to_dict() for rec in InstrumentRegistry.instance().trace_records()]


def _board_key(name: str) -> str:
    """Normaliza nome de placa para matching tolerante (minúsculas, hífen→_)."""
    return name.lower().replace("-", "_").replace(" ", "_")


def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item
