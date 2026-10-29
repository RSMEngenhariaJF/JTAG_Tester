"""Diálogo de gerenciamento de instrumentos externos."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.instruments.config import DriverType, InstrumentConfig
from core.instruments.registry import InstrumentRegistry

logger = logging.getLogger("app.gui.instrument_dialog")

_COL_STATUS  = 0
_COL_NAME    = 1
_COL_TYPE    = 2
_COL_ADDRESS = 3
_COL_DESC    = 4
_HEADERS = ["", "Nome", "Tipo", "Endereço", "Descrição"]


class InstrumentManagerDialog(QDialog):
    """Diálogo principal: lista instrumentos, permite adicionar/remover/conectar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Gerenciar Instrumentos")
        self.setMinimumSize(700, 380)
        self.resize(820, 440)
        self._registry = InstrumentRegistry.instance()
        self._build_ui()
        self._registry.add_listener(self._refresh_table)
        self._refresh_table()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_DESC, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_STATUS, QHeaderView.ResizeMode.Fixed
        )
        self._table.setColumnWidth(_COL_STATUS, 24)
        self._table.setColumnWidth(_COL_NAME,   120)
        self._table.setColumnWidth(_COL_TYPE,    72)
        self._table.setColumnWidth(_COL_ADDRESS, 180)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.selectionModel().selectionChanged.connect(self._on_selection)
        lay.addWidget(self._table)

        btn_row = QHBoxLayout()

        self._btn_add = QPushButton("Adicionar...")
        self._btn_add.clicked.connect(self._add_instrument)
        btn_row.addWidget(self._btn_add)

        self._btn_remove = QPushButton("Remover")
        self._btn_remove.setEnabled(False)
        self._btn_remove.clicked.connect(self._remove_instrument)
        btn_row.addWidget(self._btn_remove)

        btn_row.addStretch(1)

        self._btn_connect = QPushButton("Conectar")
        self._btn_connect.setEnabled(False)
        self._btn_connect.clicked.connect(self._toggle_connect)
        btn_row.addWidget(self._btn_connect)

        btn_row.addStretch(1)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.accept)
        btn_row.addWidget(box)

        lay.addLayout(btn_row)

    # ── Tabela ───────────────────────────────────────────────────────────

    def _refresh_table(self) -> None:
        self._table.setRowCount(0)
        for cfg in self._registry.configs():
            row = self._table.rowCount()
            self._table.insertRow(row)
            connected = self._registry.is_connected(cfg.name)
            status_item = QTableWidgetItem("●" if connected else "○")
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(
                Qt.GlobalColor.green if connected else Qt.GlobalColor.gray
            )
            self._table.setItem(row, _COL_STATUS,  status_item)
            self._table.setItem(row, _COL_NAME,    _cell(cfg.name))
            self._table.setItem(row, _COL_TYPE,    _cell(cfg.driver_type.value))
            self._table.setItem(row, _COL_ADDRESS, _cell(cfg.address))
            self._table.setItem(row, _COL_DESC,    _cell(cfg.description))
        self._on_selection()

    def _selected_name(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._table.item(rows[0].row(), _COL_NAME).text()

    def _on_selection(self) -> None:
        name = self._selected_name()
        has  = name is not None
        self._btn_remove.setEnabled(has)
        self._btn_connect.setEnabled(has)
        if has and self._registry.is_connected(name):
            self._btn_connect.setText("Desconectar")
        else:
            self._btn_connect.setText("Conectar")

    # ── Ações ────────────────────────────────────────────────────────────

    def _add_instrument(self) -> None:
        dlg = _AddInstrumentDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cfg = dlg.result_config()
            if cfg:
                self._registry.add_config(cfg)

    def _remove_instrument(self) -> None:
        name = self._selected_name()
        if name is None:
            return
        if QMessageBox.question(
            self, "Remover instrumento", f"Remover '{name}' da lista?"
        ) == QMessageBox.StandardButton.Yes:
            self._registry.remove_config(name)

    def _toggle_connect(self) -> None:
        name = self._selected_name()
        if name is None:
            return
        try:
            if self._registry.is_connected(name):
                self._registry.disconnect(name)
            else:
                self._registry.connect(name)
        except Exception as exc:
            QMessageBox.warning(self, "Erro de conexão", str(exc))


# ---------------------------------------------------------------------------
# Diálogo de adição com campos dinâmicos
# ---------------------------------------------------------------------------


class _AddInstrumentDialog(QDialog):
    """Formulário cujos campos se adaptam ao tipo de driver selecionado."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Adicionar Instrumento")
        self.setMinimumWidth(500)
        self._page_widgets: dict[DriverType, dict] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # ── Campos comuns ────────────────────────────────────────────────
        top = QFormLayout()
        top.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name = QLineEdit()
        self._name.setPlaceholderText("dmm, osc, fonte, analisador...")
        top.addRow("Nome *", self._name)

        self._desc = QLineEdit()
        self._desc.setPlaceholderText("Rigol DM3058 — multímetro bancada")
        top.addRow("Descrição", self._desc)

        self._driver = QComboBox()
        _LABELS = {
            DriverType.VISA:   "VISA  (GPIB, USB-TMC, VXI-11...)",
            DriverType.SERIAL: "Serial / UART  (RS-232, USB-CDC)",
            DriverType.SOCKET: "TCP/IP  (LAN, LXI, Ethernet)",
            DriverType.MOCK:   "Mock  (simulado — para testes)",
        }
        for dt in DriverType:
            self._driver.addItem(_LABELS[dt], userData=dt)
        top.addRow("Tipo *", self._driver)

        lay.addLayout(top)

        # ── Separador ────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        lay.addWidget(sep)

        # ── Área de parâmetros específicos ───────────────────────────────
        self._stacked = QStackedWidget()
        for i, dt in enumerate(DriverType):
            page, widgets = self._build_page(dt)
            self._page_widgets[dt] = widgets
            self._stacked.addWidget(page)

        self._driver.currentIndexChanged.connect(
            lambda idx: self._stacked.setCurrentIndex(idx)
        )
        lay.addWidget(self._stacked)

        # ── Botões ───────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._validate_and_accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    # ── Construtores de página ────────────────────────────────────────────

    def _build_page(self, dt: DriverType) -> tuple[QWidget, dict]:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setContentsMargins(0, 4, 0, 4)
        widgets: dict = {}

        if dt == DriverType.VISA:
            widgets = self._page_visa(form)
        elif dt == DriverType.SERIAL:
            widgets = self._page_serial(form)
        elif dt == DriverType.SOCKET:
            widgets = self._page_socket(form)
        elif dt == DriverType.MOCK:
            widgets = self._page_mock(form)

        return page, widgets

    def _page_visa(self, form: QFormLayout) -> dict:
        resource = QLineEdit()
        resource.setPlaceholderText(
            "GPIB0::22::INSTR    USB0::0x0957::0x0588::INSTR    TCPIP::192.168.1.5::INSTR"
        )
        timeout = QSpinBox()
        timeout.setRange(100, 60_000)
        timeout.setValue(5_000)
        timeout.setSuffix(" ms")
        timeout.setSingleStep(500)

        form.addRow("Recurso VISA *", resource)
        form.addRow("Timeout de leitura", timeout)
        form.addRow(
            _hint("Dica: use o endereço exato exibido pelo NI-MAX ou pyvisa-shell")
        )
        return {"address": resource, "timeout_ms": timeout}

    def _page_serial(self, form: QFormLayout) -> dict:
        port = QLineEdit()
        port.setPlaceholderText("COM3   /   /dev/ttyUSB0")

        baudrate = QComboBox()
        for b in [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]:
            baudrate.addItem(str(b), userData=b)
        baudrate.setCurrentText("9600")

        bytesize = QComboBox()
        for d in [5, 6, 7, 8]:
            bytesize.addItem(str(d), userData=d)
        bytesize.setCurrentText("8")

        parity = QComboBox()
        for label, code in [
            ("Nenhuma (N)", "N"),
            ("Par — Even (E)", "E"),
            ("Ímpar — Odd (O)", "O"),
            ("Mark (M)", "M"),
            ("Space (S)", "S"),
        ]:
            parity.addItem(label, userData=code)

        stopbits = QComboBox()
        for label, val in [("1", 1), ("1.5", 1.5), ("2", 2)]:
            stopbits.addItem(label, userData=val)

        timeout = QDoubleSpinBox()
        timeout.setRange(0.1, 30.0)
        timeout.setValue(1.0)
        timeout.setSuffix(" s")
        timeout.setDecimals(1)
        timeout.setSingleStep(0.1)

        form.addRow("Porta *",          port)
        form.addRow("Baudrate",         baudrate)
        form.addRow("Bits de dados",    bytesize)
        form.addRow("Paridade",         parity)
        form.addRow("Bits de parada",   stopbits)
        form.addRow("Timeout de leitura", timeout)

        return {
            "address":  port,
            "baudrate": baudrate,
            "bytesize": bytesize,
            "parity":   parity,
            "stopbits": stopbits,
            "timeout":  timeout,
        }

    def _page_socket(self, form: QFormLayout) -> dict:
        host = QLineEdit()
        host.setPlaceholderText("192.168.1.10")

        tcp_port = QSpinBox()
        tcp_port.setRange(1, 65535)
        tcp_port.setValue(5025)

        timeout = QDoubleSpinBox()
        timeout.setRange(0.5, 60.0)
        timeout.setValue(5.0)
        timeout.setSuffix(" s")
        timeout.setDecimals(1)
        timeout.setSingleStep(0.5)

        terminator = QComboBox()
        terminator.addItem("LF  (\\n)  — padrão SCPI", userData="\n")
        terminator.addItem("CR+LF  (\\r\\n)",           userData="\r\n")
        terminator.addItem("CR  (\\r)",                 userData="\r")

        form.addRow("Host *",               host)
        form.addRow("Porta TCP",            tcp_port)
        form.addRow("Timeout de conexão",   timeout)
        form.addRow("Terminador de linha",  terminator)
        form.addRow(
            _hint("Porta padrão LXI/SCPI: 5025   |   VXI-11: use tipo VISA")
        )

        return {
            "address":    host,
            "port":       tcp_port,
            "timeout":    timeout,
            "terminator": terminator,
        }

    def _page_mock(self, form: QFormLayout) -> dict:
        lbl = QLabel(
            "O driver Mock simula respostas para testes sem hardware real.\n\n"
            "Configure respostas no script pytest:\n"
            "    drv = get_instrument(\"dmm\")\n"
            "    drv.set_response(\"MEAS:VOLT:DC?\", \"3.300\")\n\n"
            "Ou via InstrumentConfig(params={\"responses\": {\"CMD\": \"VAL\"}})."
        )
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            "color: #555; background: #f8f8f8; padding: 10px; border-radius: 4px;"
        )
        form.addRow(lbl)
        return {}

    # ── Validação e resultado ────────────────────────────────────────────

    def _validate_and_accept(self) -> None:
        dt = self._driver.currentData()

        if not self._name.text().strip():
            QMessageBox.warning(self, "Campo obrigatório", "Informe um nome para o instrumento.")
            return

        if dt != DriverType.MOCK:
            wg    = self._page_widgets[dt]
            addr  = wg.get("address")
            if addr and not addr.text().strip():
                labels = {
                    DriverType.VISA:   "recurso VISA",
                    DriverType.SERIAL: "porta serial",
                    DriverType.SOCKET: "host",
                }
                QMessageBox.warning(
                    self, "Campo obrigatório",
                    f"Informe o {labels.get(dt, 'endereço')} do instrumento."
                )
                return

        self.accept()

    def result_config(self) -> InstrumentConfig | None:
        name = self._name.text().strip()
        desc = self._desc.text().strip()
        dt   = self._driver.currentData()
        if not name:
            return None

        wg:     dict = self._page_widgets[dt]
        params: dict = {}

        if dt == DriverType.VISA:
            address              = wg["address"].text().strip()
            params["timeout_ms"] = wg["timeout_ms"].value()

        elif dt == DriverType.SERIAL:
            address            = wg["address"].text().strip()
            params["baudrate"] = wg["baudrate"].currentData()
            params["bytesize"] = wg["bytesize"].currentData()
            params["parity"]   = wg["parity"].currentData()
            params["stopbits"] = wg["stopbits"].currentData()
            params["timeout"]  = round(wg["timeout"].value(), 2)

        elif dt == DriverType.SOCKET:
            address               = wg["address"].text().strip()
            params["port"]        = wg["port"].value()
            params["timeout"]     = round(wg["timeout"].value(), 2)
            params["terminator"]  = wg["terminator"].currentData()

        else:  # MOCK
            address = "mock://local"

        return InstrumentConfig(
            name        = name,
            driver_type = dt,
            address     = address,
            description = desc,
            params      = params,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def _hint(text: str) -> QLabel:
    lbl = QLabel(f"<small style='color:#888'>{text}</small>")
    lbl.setWordWrap(True)
    return lbl
