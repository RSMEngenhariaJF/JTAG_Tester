"""Editor do "Plano de testes" — aba do editor de projeto.

À esquerda, as instâncias do plano (marcadas = ativas). À direita, um formulário
gerado a partir dos ``params`` declarados pelo teste: sinais do Pinout com caixas
de seleção, números, opções e sim/não. Nada aqui conhece pinos fixos: a lista de
sinais vem do Pinout que está sendo editado.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.project.config import PinDef, TestPlanEntry
from tests_builtin import params as tp
from tests_builtin.plan import LibraryItem, list_library, make_ref, resolve_ref

logger = logging.getLogger("app.gui.test_plan_editor")


class TestPlanEditor(QWidget):
    """Lista de instâncias + formulário de parâmetros."""

    __test__ = False

    def __init__(self, pins_provider: Callable[[], dict[str, PinDef]],
                 library_provider: Callable[[], list[LibraryItem]] = list_library,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pins_provider = pins_provider
        self._library_provider = library_provider
        self._entries: list[TestPlanEntry] = []
        self._building = False
        self._build_ui()

    # ── Layout ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        hint = QLabel(
            "Instâncias de testes parametrizáveis: escolha o teste uma vez e aplique-o aos "
            "sinais do Pinout. Marcadas = executadas na suite, na ordem da lista."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px;")
        lay.addWidget(hint)

        split = QSplitter(Qt.Orientation.Horizontal)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._show_form)
        self._list.itemChanged.connect(self._on_item_changed)
        split.addWidget(self._list)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        split.addWidget(self._scroll)
        split.setSizes([260, 520])
        lay.addWidget(split, stretch=1)

        row = QHBoxLayout()
        for text, slot in (("+ Adicionar teste...", self._add), ("Duplicar", self._duplicate),
                           ("Remover", self._remove), ("↑", lambda: self._move(-1)),
                           ("↓", lambda: self._move(1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self._show_form(-1)

    # ── API ───────────────────────────────────────────────────────────────

    def set_entries(self, entries: list[TestPlanEntry]) -> None:
        self._entries = [copy.deepcopy(e) for e in entries]
        self._reload_list(0 if self._entries else -1)

    def entries(self) -> list[TestPlanEntry]:
        return [copy.deepcopy(e) for e in self._entries]

    def validate(self, pins: dict[str, PinDef]) -> list[str]:
        """Erros de parâmetro de cada instância, contra o Pinout informado."""
        from core.project.config import ProjectConfig

        proj = ProjectConfig(name="", project_code="", board="", pins=pins)
        errs: list[str] = []
        for i, e in enumerate(self._entries, 1):
            who = f"{i}. {e.label or e.test}"
            try:
                cls = resolve_ref(e.test)
            except Exception as exc:
                errs.append(f"{who}: {exc}")
                continue
            errs += [f"{who}: {m}" for m in tp.validate(cls.params, e.params, proj)]
        return errs

    def add_entry(self, ref: str, label: str = "") -> None:
        """Acrescenta uma instância do teste `ref` com os valores padrão e a seleciona."""
        cls = resolve_ref(ref)
        self._entries.append(TestPlanEntry(test=ref, label=label,
                                           params=tp.defaults(cls.params)))
        self._reload_list(len(self._entries) - 1)

    def refresh(self) -> None:
        """Reconstrói o formulário (ex.: o Pinout mudou em outra aba)."""
        self._show_form(self._list.currentRow())

    # ── Lista ─────────────────────────────────────────────────────────────

    def _title(self, e: TestPlanEntry) -> str:
        try:
            name = resolve_ref(e.test).name
        except Exception:
            name = e.test
        title = f"{e.label}  ·  {name}" if e.label else name
        return f"{title}  x{e.repeat}" if e.repeat > 1 else title

    def _reload_list(self, select: int) -> None:
        self._building = True
        self._list.clear()
        for e in self._entries:
            item = QListWidgetItem(self._title(e))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if e.enabled else Qt.CheckState.Unchecked)
            item.setToolTip(e.test)
            self._list.addItem(item)
        self._building = False
        self._list.setCurrentRow(select)
        self._show_form(select)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._building:
            return
        row = self._list.row(item)
        if 0 <= row < len(self._entries):
            self._entries[row].enabled = item.checkState() == Qt.CheckState.Checked

    def _add(self) -> None:
        dlg = _AddTestDialog(self._library_provider, self)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.choice is None:
            return
        item = dlg.choice
        self._entries.append(TestPlanEntry(test=item.ref, label="",
                                           params=tp.defaults(item.cls.params)))
        self._reload_list(len(self._entries) - 1)

    def _duplicate(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        e = copy.deepcopy(self._entries[row])
        e.label = f"{e.label} (cópia)" if e.label else "cópia"
        self._entries.insert(row + 1, e)
        self._reload_list(row + 1)

    def _remove(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        del self._entries[row]
        self._reload_list(min(row, len(self._entries) - 1))

    def _move(self, delta: int) -> None:
        row = self._list.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < len(self._entries):
            return
        self._entries[row], self._entries[new] = self._entries[new], self._entries[row]
        self._reload_list(new)

    # ── Formulário ────────────────────────────────────────────────────────

    def _show_form(self, row: int) -> None:
        box = QWidget()
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._scroll.setWidget(box)
        if not 0 <= row < len(self._entries):
            form.addRow(QLabel("Adicione um teste ou selecione uma instância à esquerda."))
            return
        e = self._entries[row]
        try:
            cls = resolve_ref(e.test)
        except Exception as exc:
            err = QLabel(f"⚠ {exc}")
            err.setStyleSheet("color: #c00000;")
            err.setWordWrap(True)
            form.addRow(err)
            return

        head = QLabel(f"<b>{cls.name}</b><br><span style='color:#666'>{cls.description}"
                      f"<br>{e.test}</span>")
        head.setWordWrap(True)
        form.addRow(head)

        label = QLineEdit(e.label)
        label.setPlaceholderText("ex.: LEDs indicadores")
        label.textChanged.connect(lambda t, e=e, r=row: self._set_label(r, t))
        form.addRow("Rótulo", label)

        reps = QSpinBox()
        reps.setRange(1, 1000)
        reps.setValue(e.repeat)
        reps.setSuffix(" x")
        reps.setToolTip("Repetibilidade: roda o teste N vezes e junta as métricas\n"
                        "(média, desvio, mín/máx; reprova se alguma repetição reprovar)")
        reps.valueChanged.connect(lambda v, r=row: self._set_repeat(r, v))
        form.addRow("Repetições", reps)

        merged = {**tp.defaults(cls.params), **e.params}
        e.params = merged
        for key, prm in cls.params.items():
            w = self._param_widget(e, key, prm, merged[key])
            if prm.help:
                w.setToolTip(prm.help)
            form.addRow(prm.label, w)

    def _set_repeat(self, row: int, value: int) -> None:
        self._entries[row].repeat = int(value)
        item = self._list.item(row)
        if item is not None:
            self._building = True
            item.setText(self._title(self._entries[row]))
            self._building = False

    def _set_label(self, row: int, text: str) -> None:
        self._entries[row].label = text.strip()
        item = self._list.item(row)
        if item is not None:
            self._building = True
            item.setText(self._title(self._entries[row]))
            self._building = False

    def _param_widget(self, e: TestPlanEntry, key: str, prm: tp.Param, value) -> QWidget:
        def setter(v, e=e, key=key):
            e.params[key] = v

        if isinstance(prm, tp.SignalsParam):
            return self._signals_widget(e, key, prm, list(value or []))
        if isinstance(prm, tp.PeripheralParam):
            options = prm.options(self._pins_provider())
            if not options:
                return QLabel(f"Nenhum periférico {'/'.join(prm.types)} no Pinout — cadastre os "
                              "pinos com tipo, periférico e função na aba Pinout.")
            w = QComboBox()
            w.addItems(options)
            if value in options:
                w.setCurrentText(value)
            else:
                e.params[key] = options[0]
            w.currentTextChanged.connect(setter)
            return w
        if isinstance(prm, tp.IntParam):
            w = QSpinBox()
            w.setRange(prm.minimum, prm.maximum)
            w.setValue(int(value))
            if prm.unit:
                w.setSuffix(f" {prm.unit}")
            w.valueChanged.connect(setter)
            return w
        if isinstance(prm, tp.FloatParam):
            w = QDoubleSpinBox()
            w.setDecimals(prm.decimals)
            w.setRange(prm.minimum, prm.maximum)
            w.setValue(float(value))
            if prm.unit:
                w.setSuffix(f" {prm.unit}")
            w.valueChanged.connect(setter)
            return w
        if isinstance(prm, tp.ChoiceParam):
            w = QComboBox()
            w.addItems(prm.choices)
            w.setCurrentText(str(value))
            w.currentTextChanged.connect(setter)
            return w
        if isinstance(prm, tp.TextParam):
            w = QLineEdit(str(value))
            w.setPlaceholderText(prm.placeholder)
            w.textChanged.connect(setter)
            return w
        if isinstance(prm, tp.BoolParam):
            w = QCheckBox()
            w.setChecked(bool(value))
            w.toggled.connect(setter)
            return w
        return QLabel(f"(tipo de parâmetro não suportado: {type(prm).__name__})")

    def _signals_widget(self, e: TestPlanEntry, key: str, prm: tp.SignalsParam,
                        selected: list[str]) -> QWidget:
        pins = self._pins_provider()
        lst = QListWidget()
        lst.setMinimumHeight(110)
        names = [n for n, pd in pins.items() if prm.accepts(pd.peripheral.periph_type)]
        for n in names:
            pd = pins[n]
            text = f"{n}   —   {pd.port}{pd.pin}"
            if pd.description:
                text += f"   ({pd.description})"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, n)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if n in selected else Qt.CheckState.Unchecked)
            lst.addItem(item)
        for n in selected:                 # sinal salvo que não existe mais no Pinout
            if n not in names:
                item = QListWidgetItem(f"{n}   —   não existe no Pinout (ou tipo incompatível)")
                item.setData(Qt.ItemDataRole.UserRole, n)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                item.setForeground(Qt.GlobalColor.red)
                lst.addItem(item)
        if lst.count() == 0:
            tipos = "/".join(prm.types) or "qualquer"
            return QLabel(f"Nenhum sinal do tipo {tipos} no Pinout — cadastre na aba Pinout.")

        def changed(_item=None, e=e, key=key, lst=lst) -> None:
            e.params[key] = [
                lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(lst.count())
                if lst.item(i).checkState() == Qt.CheckState.Checked
            ]

        lst.itemChanged.connect(changed)
        changed()
        return lst


class _AddTestDialog(QDialog):
    """Escolhe um teste parametrizável da biblioteca (TESTES_PLATAFORMA) ou de um arquivo."""

    def __init__(self, library_provider: Callable[[], list[LibraryItem]],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Adicionar teste ao plano")
        self.setMinimumSize(560, 340)
        self.choice: LibraryItem | None = None
        self._items: list[LibraryItem] = []
        self._rows: list[LibraryItem | None] = []      # linha → item (None = cabeçalho)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Testes parametrizáveis disponíveis:"))
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _i: self._accept())
        lay.addWidget(self._list, stretch=1)
        last_cat = None
        for item in library_provider():
            if item.category != last_cat:
                last_cat = item.category
                head = QListWidgetItem(item.category.upper())
                head.setFlags(Qt.ItemFlag.NoItemFlags)
                font = head.font()
                font.setBold(True)
                head.setFont(font)
                self._list.addItem(head)
                self._rows.append(None)
            self._append(item)

        row = QHBoxLayout()
        other = QPushButton("Outro arquivo...")
        other.clicked.connect(self._from_file)
        row.addWidget(other)
        row.addStretch(1)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        row.addWidget(btns)
        lay.addLayout(row)
        first = next((i for i, r in enumerate(self._rows) if r is not None), -1)
        if first >= 0:
            self._list.setCurrentRow(first)

    def _append(self, item: LibraryItem) -> None:
        self._items.append(item)
        self._rows.append(item)
        w = QListWidgetItem(f"    {item.name}   —   {item.description}")
        w.setToolTip(item.ref)
        self._list.addItem(w)

    def _from_file(self) -> None:
        from tests_builtin.loader import PluginLoader

        path, _ = QFileDialog.getOpenFileName(self, "Arquivo de teste", "", "Python (*.py)")
        if not path:
            return
        try:
            classes = [c for c in PluginLoader.load_classes(Path(path)) if c.params]
        except Exception as exc:
            QMessageBox.warning(self, "Arquivo de teste", f"Não carregou: {exc}")
            return
        if not classes:
            QMessageBox.information(self, "Arquivo de teste",
                                    "Nenhum teste com parâmetros (params) neste arquivo.")
            return
        for cls in classes:
            self._append(LibraryItem(make_ref(path, cls.__name__), cls.name,
                                     cls.description, cls))
        self._list.setCurrentRow(self._list.count() - 1)

    def _accept(self) -> None:
        row = self._list.currentRow()
        if row < 0 or self._rows[row] is None:
            return
        self.choice = self._rows[row]
        self.accept()
