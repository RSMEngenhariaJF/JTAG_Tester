"""Janela de logs — acompanha, filtra, salva e limpa os registros da sessão.

Não-modal: pode ficar aberta ao lado da janela principal enquanto a suite roda.
Os registros chegam de qualquer thread pelo LogBuffer e são repassados à thread
de interface por um sinal Qt (conexão enfileirada).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.log_buffer import LEVELS, LogBuffer, LogEntry, _redact, get_log_buffer

_LEVEL_FILTERS = (("Todos", "DEBUG"), ("Info e acima", "INFO"),
                  ("Avisos e erros", "WARNING"), ("Só erros", "ERROR"))
_COLORS = {"DEBUG": "#808080", "INFO": "#000000", "WARNING": "#B35900",
           "ERROR": "#C00000", "CRITICAL": "#C00000"}
_BG = {"ERROR": "#FFE5E5", "CRITICAL": "#FFC8C8", "WARNING": "#FFF4E0"}
_HEADERS = ("Hora", "Nível", "Origem", "Mensagem")


class _Bridge(QObject):
    """Leva o registro da thread que logou para a thread da GUI."""

    record = Signal(object)


class LogWindow(QDialog):
    """Visualizador de logs com filtro, busca, detalhe, salvar, copiar e limpar."""

    def __init__(self, parent: QWidget | None = None, buffer: LogBuffer | None = None,
                 context_provider: Callable[[], dict] | None = None,
                 save_path_provider: Callable[[str, str, str], tuple[str, str]] | None = None
                 ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Logs da sessão")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(980, 520)
        self._buf = buffer or get_log_buffer()
        self._context = context_provider or (lambda: {})
        self._ask_path = save_path_provider
        self._shown: list[LogEntry] = []

        self._bridge = _Bridge()
        self._bridge.record.connect(self._on_record, Qt.ConnectionType.QueuedConnection)
        self._listener = self._bridge.record.emit
        self._buf.add_listener(self._listener)

        self._build_ui()
        self._reload()

    # ── Layout ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Nível:"))
        self._level = QComboBox()
        for text, lvl in _LEVEL_FILTERS:
            self._level.addItem(text, lvl)
        self._level.setCurrentIndex(1)
        self._level.currentIndexChanged.connect(self._reload)
        top.addWidget(self._level)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Buscar na mensagem ou origem...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._reload)
        top.addWidget(self._search, stretch=1)

        self._follow = QCheckBox("Rolar automaticamente")
        self._follow.setChecked(True)
        top.addWidget(self._follow)
        lay.addLayout(top)

        split = QSplitter(Qt.Orientation.Vertical)
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 100)
        self._table.setColumnWidth(1, 80)
        self._table.setColumnWidth(2, 200)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._show_detail)
        split.addWidget(self._table)

        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setPlaceholderText("Selecione um registro para ver o detalhe e o traceback.")
        self._detail.setStyleSheet("font-family: Consolas, 'Courier New'; font-size: 11px;")
        split.addWidget(self._detail)
        split.setSizes([360, 130])
        lay.addWidget(split, stretch=1)

        bottom = QHBoxLayout()
        self._summary = QLabel()
        self._summary.setStyleSheet("color: #555;")
        bottom.addWidget(self._summary)
        bottom.addStretch(1)
        for text, slot, tip in (
            ("Copiar", self._copy, "Copia os registros filtrados como texto"),
            ("Salvar...", self._save, "Texto (.log) ou JSON Lines (.jsonl) para análise"),
            ("Limpar", self._clear, "Esvazia os logs da sessão (o arquivo em disco fica)"),
            ("Fechar", self.close, ""),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            if tip:
                b.setToolTip(tip)
            bottom.addWidget(b)
        lay.addLayout(bottom)

    # ── Dados ─────────────────────────────────────────────────────────────

    def _accepts(self, e: LogEntry) -> bool:
        if e.levelno < LEVELS[self._level.currentData()]:
            return False
        q = self._search.text().strip().lower()
        return not q or q in e.message.lower() or q in e.logger.lower() \
            or q in e.exception.lower()

    def _reload(self) -> None:
        self._shown = [e for e in self._buf.records() if self._accepts(e)]
        self._table.setRowCount(0)
        for e in self._shown:
            self._append_row(e)
        self._update_summary()
        if self._follow.isChecked():
            self._table.scrollToBottom()

    def _append_row(self, e: LogEntry) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        hora = e.timestamp[11:23]
        msg = _redact(e.message) + ("  [traceback]" if e.exception else "")
        for col, text in enumerate((hora, e.level, e.logger, msg)):
            item = QTableWidgetItem(text)
            item.setForeground(QBrush(QColor(_COLORS.get(e.level, "#000000"))))
            if e.level in _BG:
                item.setBackground(QBrush(QColor(_BG[e.level])))
            self._table.setItem(row, col, item)

    def _on_record(self, entry: LogEntry | None) -> None:
        if entry is None:            # buffer limpo
            self._reload()
            return
        if self._accepts(entry):
            self._shown.append(entry)
            self._append_row(entry)
            if self._follow.isChecked():
                self._table.scrollToBottom()
        self._update_summary()

    def _update_summary(self) -> None:
        total = len(self._buf.records())
        erros = self._buf.count("ERROR")
        avisos = self._buf.count("WARNING") - erros
        self._summary.setText(f"{len(self._shown)} exibidos de {total}  ·  "
                              f"{erros} erro(s)  ·  {avisos} aviso(s)")

    def _show_detail(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self._shown):
            self._detail.clear()
            return
        e = self._shown[rows[0].row()]
        local = f"{e.module}:{e.line}" if e.module else ""
        txt = (f"{e.timestamp}  {e.level}  {e.logger}  {local}  [{e.thread}]\n\n"
               f"{e.message}")
        if e.exception:
            txt += f"\n\n{e.exception}"
        self._detail.setPlainText(_redact(txt))   # sem o nome da pasta do usuário

    # ── Ações ─────────────────────────────────────────────────────────────

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(
            self._buf.export_text(self._shown, self._context()))
        self.setWindowTitle(f"Logs da sessão — {len(self._shown)} registro(s) copiados")

    def _save(self) -> None:
        if not self._shown:
            QMessageBox.information(self, "Salvar logs", "Nenhum registro para salvar.")
            return
        filters = "JSON Lines para análise (*.jsonl);;Texto (*.log)"
        name = "logs_sessao.jsonl"
        if self._ask_path is not None:
            path, _ = self._ask_path("Salvar logs", name, filters)
        else:
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getSaveFileName(self, "Salvar logs", name, filters)
        if not path:
            return
        try:
            saved = self._buf.save(path, self._shown, self._context())
        except OSError as exc:
            QMessageBox.warning(self, "Salvar logs", f"Não foi possível salvar:\n{exc}")
            return
        self.setWindowTitle(f"Logs da sessão — salvo em {saved.name}")

    def _clear(self) -> None:
        if QMessageBox.question(
            self, "Limpar logs",
            "Esvaziar os logs desta sessão?\nO arquivo de log em disco (modo dev) não é apagado."
        ) == QMessageBox.StandardButton.Yes:
            self._buf.clear()

    def closeEvent(self, event) -> None:  # noqa: N802 — override do Qt
        self._buf.remove_listener(self._listener)
        super().closeEvent(event)
