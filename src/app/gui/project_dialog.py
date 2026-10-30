"""Diálogo de criação e edição de ProjectConfig."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.board.loader import find_boards
from core.project.config import (
    PERIPH_ROLES,
    PERIPH_TYPES,
    PeripheralRef,
    PinDef,
    ProjectConfig,
)
from app.gui.test_plan_editor import TestPlanEditor
from core.project.ioc import parse_ioc
from core.project.loader import save_project

logger = logging.getLogger("app.gui.project_dialog")

_GPIO_PORTS = [f"GPIO{c}" for c in "ABCDEFGHIJK"]


# ---------------------------------------------------------------------------
# Diálogo principal
# ---------------------------------------------------------------------------


class ProjectEditorDialog(QDialog):
    """Cria ou edita um ProjectConfig com pinout completo e lista de testes."""

    def __init__(
        self,
        parent: QWidget | None = None,
        project: ProjectConfig | None = None,
    ) -> None:
        super().__init__(parent)
        self._original = project
        self._clocks: dict = dict(project.clocks) if project else {}
        self.setWindowTitle("Editar Projeto" if project else "Novo Projeto")
        self.setMinimumSize(820, 540)
        self.resize(920, 600)
        self._build_ui()
        if project:
            self._populate(project)

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        # ── Campos gerais ────────────────────────────────────────────────
        top = QFormLayout()
        top.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Motor Controller v1")
        top.addRow("Nome *", self._name)

        self._code = QLineEdit()
        self._code.setPlaceholderText("MTR-001")
        top.addRow("Código *", self._code)

        self._board_combo = QComboBox()
        self._boards = find_boards()
        for b in self._boards:
            self._board_combo.addItem(b.name, userData=b.name)
        top.addRow("Placa base *", self._board_combo)

        self._desc = QLineEdit()
        self._desc.setPlaceholderText("Descrição breve do produto")
        top.addRow("Descrição", self._desc)

        lay.addLayout(top)

        # ── Abas de detalhes ─────────────────────────────────────────────
        tabs = QTabWidget()
        self._tabs = tabs
        tabs.addTab(self._build_pins_tab(),   "Pinout")
        self._plan_editor = TestPlanEditor(lambda: self._pin_table.pins())
        tabs.addTab(self._plan_editor,        "Plano de testes")
        tabs.addTab(self._build_tests_tab(),  "Testes")
        # O formulário do plano lista os sinais do Pinout: refaz ao entrar na aba
        tabs.currentChanged.connect(
            lambda i: self._plan_editor.refresh() if tabs.widget(i) is self._plan_editor else None
        )
        tabs.addTab(self._build_instrs_tab(), "Instrumentos")
        lay.addWidget(tabs, stretch=1)

        # ── Botões ───────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._validate_and_save)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    # ── Aba Pinout ────────────────────────────────────────────────────────

    def _build_pins_tab(self) -> QWidget:
        widget = QWidget()
        lay    = QVBoxLayout(widget)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        hint = QLabel(
            "Mapeie cada sinal do produto para o pino físico e, se aplicável, "
            "ao periférico do MCU (UART, SPI, ADC, PWM…)."
        )
        hint.setStyleSheet("color: #666; font-size: 11px;")
        lay.addWidget(hint)

        self._pin_table = _PinTable()
        lay.addWidget(self._pin_table, stretch=1)

        btn_row = QHBoxLayout()

        btn_add = QPushButton("+ Adicionar sinal")
        btn_add.clicked.connect(self._pin_table.add_empty_row)
        btn_row.addWidget(btn_add)

        btn_rem = QPushButton("− Remover selecionado")
        btn_rem.clicked.connect(self._pin_table.remove_selected)
        btn_row.addWidget(btn_rem)

        btn_row.addStretch(1)

        btn_ioc_import = QPushButton("Importar .ioc...")
        btn_ioc_import.setToolTip(
            "Importa o pinout de um projeto STM32CubeMX (.ioc).\n"
            "Usa os rótulos (GPIO_Label) como nome do sinal e seleciona a placa\n"
            "cujo alvo corresponde ao MCU do arquivo, se houver."
        )
        btn_ioc_import.clicked.connect(self._import_ioc)
        btn_row.addWidget(btn_ioc_import)

        btn_csv_import = QPushButton("Importar CSV...")
        btn_csv_import.setToolTip(
            "Importa pinout a partir de um CSV.\n"
            "Colunas: sinal, porta, pino, tipo, periferico, funcao, descricao, ativo_baixo"
        )
        btn_csv_import.clicked.connect(self._import_csv)
        btn_row.addWidget(btn_csv_import)

        btn_csv_export = QPushButton("Exportar CSV")
        btn_csv_export.setToolTip("Exporta o pinout atual para CSV")
        btn_csv_export.clicked.connect(self._export_csv)
        btn_row.addWidget(btn_csv_export)

        lay.addLayout(btn_row)
        return widget

    # ── Aba Testes ────────────────────────────────────────────────────────

    def _build_tests_tab(self) -> QWidget:
        widget = QWidget()
        lay    = QVBoxLayout(widget)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        hint = QLabel(
            "Arquivos .py ou diretórios com testes pytest associados a este projeto.\n"
            "Serão exibidos na aba Testes da janela principal."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px;")
        lay.addWidget(hint)

        self._tests_list = QListWidget()
        lay.addWidget(self._tests_list, stretch=1)

        btn_row = QHBoxLayout()
        btn_file = QPushButton("Adicionar arquivo...")
        btn_file.clicked.connect(self._add_test_file)
        btn_row.addWidget(btn_file)

        btn_dir = QPushButton("Adicionar diretório...")
        btn_dir.clicked.connect(self._add_test_dir)
        btn_row.addWidget(btn_dir)

        btn_rem = QPushButton("Remover")
        btn_rem.clicked.connect(self._remove_test)
        btn_row.addWidget(btn_rem)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        return widget

    # ── Aba Instrumentos ──────────────────────────────────────────────────

    def _build_instrs_tab(self) -> QWidget:
        widget = QWidget()
        lay    = QVBoxLayout(widget)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        hint = QLabel(
            "Nomes dos instrumentos obrigatórios para este projeto.\n"
            "Devem corresponder aos nomes configurados em Gerenciar Instrumentos."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px;")
        lay.addWidget(hint)

        self._instr_list = QListWidget()
        lay.addWidget(self._instr_list, stretch=1)

        btn_row = QHBoxLayout()
        self._instr_edit = QLineEdit()
        self._instr_edit.setPlaceholderText("dmm, osc, fonte...")
        btn_row.addWidget(self._instr_edit, stretch=1)

        btn_add = QPushButton("Adicionar")
        btn_add.clicked.connect(self._add_instrument)
        self._instr_edit.returnPressed.connect(self._add_instrument)
        btn_row.addWidget(btn_add)

        btn_rem = QPushButton("Remover")
        btn_rem.clicked.connect(self._remove_instrument)
        btn_row.addWidget(btn_rem)
        lay.addLayout(btn_row)
        return widget

    # ── CSV ───────────────────────────────────────────────────────────────

    def _import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar pinout de CSV", "", "CSV (*.csv);;Todos os arquivos (*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
            pins = ProjectConfig.pins_from_csv(text)
            if not pins:
                QMessageBox.warning(self, "CSV vazio", "Nenhum pino encontrado no arquivo.")
                return
            answer = QMessageBox.question(
                self, "Importar CSV",
                f"Importar {len(pins)} pino(s)?\n"
                "Isso substituirá todos os pinos atuais da tabela.",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._replace_pins(pins)
        except Exception as exc:
            QMessageBox.warning(self, "Erro ao importar CSV", str(exc))

    def _replace_pins(self, pins: dict[str, PinDef]) -> None:
        self._pin_table.clear_rows()
        for sig, pd in pins.items():
            self._pin_table.add_row(
                signal      = sig,
                port        = pd.port,
                pin         = pd.pin,
                periph_type = pd.peripheral.periph_type,
                periph_name = pd.peripheral.name,
                periph_role = pd.peripheral.role,
                desc        = pd.description,
                active_low  = pd.active_low,
            )

    # ── STM32CubeMX (.ioc) ────────────────────────────────────────────────

    def _import_ioc(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar pinout do STM32CubeMX", "",
            "STM32CubeMX (*.ioc);;Todos os arquivos (*)"
        )
        if not path:
            return
        try:
            ioc = parse_ioc(Path(path).read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            QMessageBox.warning(self, "Erro ao importar .ioc", str(exc))
            return
        if not ioc.pins:
            QMessageBox.warning(self, ".ioc sem pinos", "Nenhum pino configurado no arquivo.")
            return

        board = ioc.match_board(self._boards)
        lines = [
            f"MCU: {ioc.cpn or ioc.user_name}  {ioc.package}",
            f"{len(ioc.pins)} pino(s) — substituirá todos os pinos atuais da tabela.",
        ]
        if board is not None:
            lines.append(f"Placa base: {board.name} (selecionada automaticamente)")
        else:
            lines.append(
                f"⚠ Nenhuma placa cadastrada para '{ioc.user_name}'. "
                "O projeto ficará com a placa base selecionada no formulário."
            )
        if ioc.skipped:
            lines.append("Ignorados (debug/oscilador): " + ", ".join(ioc.skipped))
        if "SYSCLK" in ioc.clocks:
            lines.append(f"Clock esperado: SYSCLK {ioc.clocks['SYSCLK'] / 1e6:g} MHz "
                         f"({ioc.clocks.get('fonte', '?')}), {len(ioc.clocks)} valor(es)")
        answer = QMessageBox.question(
            self, "Importar .ioc", "\n".join(lines) + "\n\nImportar?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._replace_pins(ioc.pins)
        if ioc.clocks:
            self._clocks = dict(ioc.clocks)      # clock esperado do produto
        if board is not None:
            self._board_combo.setCurrentIndex(self._board_combo.findData(board.name))
        if not self._name.text().strip() and ioc.project_name:
            self._name.setText(ioc.project_name)
        if not self._desc.text().strip():
            self._desc.setText(f"Pinout importado de {Path(path).name} ({ioc.cpn or ioc.user_name})")
        logger.info("Pinout importado de %s: %d pino(s)", path, len(ioc.pins))

    def _export_csv(self) -> None:
        pins = self._pin_table.pins()
        if not pins:
            QMessageBox.information(self, "Exportar CSV", "Nenhum pino para exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar pinout CSV", "pinout.csv", "CSV (*.csv)"
        )
        if not path:
            return
        project = ProjectConfig(
            name="tmp", project_code="", board="", pins=pins
        )
        Path(path).write_text(project.to_csv(), encoding="utf-8")

    # ── Ações de testes ───────────────────────────────────────────────────

    def _add_test_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Selecionar arquivos de teste", "", "Python (*.py)"
        )
        for p in paths:
            self._tests_list.addItem(p)

    def _add_test_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Selecionar diretório de testes")
        if path:
            self._tests_list.addItem(path)

    def _remove_test(self) -> None:
        row = self._tests_list.currentRow()
        if row >= 0:
            self._tests_list.takeItem(row)

    # ── Ações de instrumentos ─────────────────────────────────────────────

    def _add_instrument(self) -> None:
        name = self._instr_edit.text().strip()
        if name:
            self._instr_list.addItem(name)
            self._instr_edit.clear()

    def _remove_instrument(self) -> None:
        row = self._instr_list.currentRow()
        if row >= 0:
            self._instr_list.takeItem(row)

    # ── Preenche formulário ao editar ─────────────────────────────────────

    def _populate(self, p: ProjectConfig) -> None:
        self._name.setText(p.name)
        self._code.setText(p.project_code)
        self._desc.setText(p.description)

        def _key(name: str) -> str:
            return (name or "").strip().lower().replace("-", "_")

        idx = next((i for i in range(self._board_combo.count())
                    if _key(self._board_combo.itemData(i)) == _key(p.board)), -1)
        if idx >= 0:
            self._board_combo.setCurrentIndex(idx)
        else:
            logger.warning("Placa '%s' do projeto não encontrada em src/boards", p.board)

        for sig, pin in p.pins.items():
            self._pin_table.add_row(
                signal      = sig,
                port        = pin.port,
                pin         = pin.pin,
                periph_type = pin.peripheral.periph_type,
                periph_name = pin.peripheral.name,
                periph_role = pin.peripheral.role,
                desc        = pin.description,
                active_low  = pin.active_low,
            )

        self._plan_editor.set_entries(p.test_plan)

        for path in p.test_paths:
            self._tests_list.addItem(path)

        for instr in p.instruments:
            self._instr_list.addItem(instr)

    # ── Validação e salvamento ────────────────────────────────────────────

    def _validate_and_save(self) -> None:
        name = self._name.text().strip()
        code = self._code.text().strip()

        if not name:
            QMessageBox.warning(self, "Campo obrigatório", "Informe o nome do projeto.")
            return
        if not code:
            QMessageBox.warning(self, "Campo obrigatório", "Informe o código do projeto.")
            return

        errors = self._pin_table.validate()
        if errors:
            QMessageBox.warning(
                self, "Pinout inválido",
                "Corrija os seguintes problemas:\n• " + "\n• ".join(errors)
            )
            return

        plan_errors = self._plan_editor.validate(self._pin_table.pins())
        if plan_errors:
            QMessageBox.warning(
                self, "Plano de testes inválido",
                "Corrija na aba Plano de testes:\n• " + "\n• ".join(plan_errors)
            )
            return

        project = ProjectConfig(
            name         = name,
            project_code = code,
            board        = self._board_combo.currentData() or "",
            description  = self._desc.text().strip(),
            pins         = self._pin_table.pins(),
            test_paths   = [
                self._tests_list.item(i).text()
                for i in range(self._tests_list.count())
            ],
            instruments  = [
                self._instr_list.item(i).text()
                for i in range(self._instr_list.count())
            ],
            analysis_config = self._original.analysis_config if self._original else "",
            clocks          = self._clocks,
            test_plan       = self._plan_editor.entries(),
        )

        try:
            path = save_project(project)
            logger.info("Projeto salvo: %s", path)
        except Exception as exc:
            QMessageBox.critical(self, "Erro ao salvar", str(exc))
            return

        self._saved_project = project
        self.accept()

    def open_plan(self, add_refs: list[str] | tuple[str, ...] = ()) -> None:
        """Mostra a aba "Plano de testes", acrescentando os testes `add_refs`."""
        for ref in add_refs:
            self._plan_editor.add_entry(ref)
        self._tabs.setCurrentWidget(self._plan_editor)

    def saved_project(self) -> ProjectConfig | None:
        return getattr(self, "_saved_project", None)


# ---------------------------------------------------------------------------
# Tabela de pinout com widgets nativos
# ---------------------------------------------------------------------------


class _PinTable(QTableWidget):
    """Tabela de pinout com ComboBox, SpinBox e CheckBox por célula.

    Colunas: Sinal | Porta | Pino | Tipo | Periférico | Função | Descrição | A.Baixo
    """

    _COL_SIGNAL = 0
    _COL_PORT   = 1
    _COL_PIN    = 2
    _COL_PTYPE  = 3
    _COL_PNAME  = 4
    _COL_PROLE  = 5
    _COL_DESC   = 6
    _COL_ALOW   = 7

    _HEADERS = [
        "Sinal *", "Porta *", "Pino *",
        "Tipo", "Periférico", "Função/Canal",
        "Descrição", "Ativo\nBaixo",
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 8, parent)
        self.setHorizontalHeaderLabels(self._HEADERS)

        hh = self.horizontalHeader()
        hh.setSectionResizeMode(self._COL_DESC, QHeaderView.ResizeMode.Stretch)
        for col, w in [
            (self._COL_SIGNAL, 100),
            (self._COL_PORT,    80),
            (self._COL_PIN,     50),
            (self._COL_PTYPE,   80),
            (self._COL_PNAME,   90),
            (self._COL_PROLE,   90),
            (self._COL_ALOW,    60),
        ]:
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.setColumnWidth(col, w)

        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

    # ── Manipulação de linhas ─────────────────────────────────────────────

    def add_empty_row(self) -> None:
        self.add_row("", "GPIOA", 0, "GPIO", "", "", "", False)

    def add_row(
        self,
        signal:      str,
        port:        str,
        pin:         int,
        periph_type: str  = "GPIO",
        periph_name: str  = "",
        periph_role: str  = "",
        desc:        str  = "",
        active_low:  bool = False,
    ) -> None:
        row = self.rowCount()
        self.insertRow(row)

        # Sinal
        sig_edit = QLineEdit(signal)
        sig_edit.setPlaceholderText("led, uart2_tx…")
        self.setCellWidget(row, self._COL_SIGNAL, sig_edit)

        # Porta
        port_combo = QComboBox()
        port_combo.addItems(_GPIO_PORTS)
        idx = _GPIO_PORTS.index(port) if port in _GPIO_PORTS else 0
        port_combo.setCurrentIndex(idx)
        self.setCellWidget(row, self._COL_PORT, port_combo)

        # Pino
        pin_spin = QSpinBox()
        pin_spin.setRange(0, 15)
        pin_spin.setValue(pin)
        self.setCellWidget(row, self._COL_PIN, pin_spin)

        # Tipo de periférico
        type_combo = QComboBox()
        type_combo.addItems(PERIPH_TYPES)
        tidx = PERIPH_TYPES.index(periph_type) if periph_type in PERIPH_TYPES else 0
        type_combo.setCurrentIndex(tidx)
        self.setCellWidget(row, self._COL_PTYPE, type_combo)

        # Nome do periférico
        pname_edit = QLineEdit(periph_name)
        pname_edit.setPlaceholderText("USART2, SPI1…")
        self.setCellWidget(row, self._COL_PNAME, pname_edit)

        # Função/Canal — atualiza placeholder conforme tipo
        prole_edit = QLineEdit(periph_role)
        self._update_role_placeholder(type_combo.currentText(), prole_edit)
        type_combo.currentTextChanged.connect(
            lambda t, w=prole_edit: self._update_role_placeholder(t, w)
        )
        self.setCellWidget(row, self._COL_PROLE, prole_edit)

        # Descrição
        desc_edit = QLineEdit(desc)
        desc_edit.setPlaceholderText("Descrição opcional")
        self.setCellWidget(row, self._COL_DESC, desc_edit)

        # Ativo baixo (checkbox centralizado)
        check_widget = QWidget()
        check_lay    = QHBoxLayout(check_widget)
        check_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        check_lay.setContentsMargins(0, 0, 0, 0)
        check = QCheckBox()
        check.setChecked(active_low)
        check_lay.addWidget(check)
        self.setCellWidget(row, self._COL_ALOW, check_widget)

        self.scrollToBottom()

    @staticmethod
    def _update_role_placeholder(periph_type: str, widget: QLineEdit) -> None:
        roles = PERIPH_ROLES.get(periph_type, [])
        if roles:
            widget.setPlaceholderText("  /  ".join(roles[:4]))
        else:
            widget.setPlaceholderText("")

    def clear_rows(self) -> None:
        self.setRowCount(0)

    def remove_selected(self) -> None:
        row = self.currentRow()
        if row >= 0:
            self.removeRow(row)

    # ── Extração de dados ─────────────────────────────────────────────────

    def validate(self) -> list[str]:
        errors: list[str] = []
        seen: set[str] = set()
        for row in range(self.rowCount()):
            sig = self.cellWidget(row, self._COL_SIGNAL).text().strip()
            if not sig:
                errors.append(f"Linha {row + 1}: nome do sinal vazio")
            elif sig in seen:
                errors.append(f"Sinal duplicado: '{sig}'")
            else:
                seen.add(sig)
        return errors

    def pins(self) -> dict[str, PinDef]:
        result: dict[str, PinDef] = {}
        for row in range(self.rowCount()):
            signal = self.cellWidget(row, self._COL_SIGNAL).text().strip()
            if not signal:
                continue
            port        = self.cellWidget(row, self._COL_PORT).currentText()
            pin         = self.cellWidget(row, self._COL_PIN).value()
            periph_type = self.cellWidget(row, self._COL_PTYPE).currentText()
            periph_name = self.cellWidget(row, self._COL_PNAME).text().strip().upper()
            periph_role = self.cellWidget(row, self._COL_PROLE).text().strip().upper()
            desc        = self.cellWidget(row, self._COL_DESC).text().strip()
            container   = self.cellWidget(row, self._COL_ALOW)
            alow        = container.layout().itemAt(0).widget().isChecked()

            result[signal] = PinDef(
                port        = port,
                pin         = pin,
                description = desc,
                active_low  = alow,
                peripheral  = PeripheralRef(
                    periph_type = periph_type,
                    name        = periph_name,
                    role        = periph_role,
                ),
            )
        return result
