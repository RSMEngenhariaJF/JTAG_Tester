"""Dialog de gerenciamento de perfis de critérios de análise.

Permite criar, editar, importar e exportar AnalysisConfig (perfis JSON
que definem os limites de aprovação por nome de métrica).

Fluxo de uso:
    1. O usuário abre o dialog pela aba "Projeto" → botão "Critérios..."
    2. Seleciona um perfil existente no ComboBox ou clica "Novo"
    3. Edita a tabela de métricas (nome, limites, tolerância, descrição)
    4. Clica "Salvar" para gravar em analysis_configs/
    5. Clica "Usar no projeto" para vincular ao projeto ativo
    6. Pode importar/exportar JSON para compartilhar entre projetos

Para importar um JSON de outro sistema (ex: arquivo de outro projeto):
    Importar JSON... → seleciona o arquivo → popula a tabela → salvar como...
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.analysis.config import (
    AnalysisConfig,
    MetricConfig,
    _CONFIGS_DIR,
    find_configs,
    set_active_analysis_config,
)

_COL_NAME  = 0
_COL_LMIN  = 1
_COL_LMAX  = 2
_COL_TOL   = 3
_COL_NOM   = 4
_COL_DESC  = 5
_HEADERS   = ["Métrica", "Lim. Mín.", "Lim. Máx.", "Tolerância %", "Nominal", "Descrição"]

_PLACEHOLDER = {
    _COL_NAME: "nome_da_metrica",
    _COL_LMIN: "ex: 3.135",
    _COL_LMAX: "ex: 3.465  ou  1e-6",
    _COL_TOL:  "ex: 5.0",
    _COL_NOM:  "ex: 3.3",
    _COL_DESC: "descrição opcional",
}


class AnalysisConfigDialog(QDialog):
    """Dialog de edição e gerenciamento de perfis de análise."""

    def __init__(self, parent=None, *, active_config_name: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Perfis de Critérios de Análise")
        self.setMinimumSize(820, 560)
        self.resize(1000, 640)

        self._configs: list[AnalysisConfig] = find_configs()
        self._current_path: Path | None = None
        self._modified = False

        self._build_ui()
        self._populate_combo()

        # Seleciona o perfil vinculado ao projeto ativo, se existir
        if active_config_name:
            for i in range(self._combo_perfil.count()):
                if self._combo_perfil.itemData(i) == active_config_name:
                    self._combo_perfil.setCurrentIndex(i)
                    break

    # ── Construção da UI ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ── Seleção de perfil ─────────────────────────────────────────────────
        sel_group = QGroupBox("Perfil")
        sel_lay   = QHBoxLayout(sel_group)

        self._combo_perfil = QComboBox()
        self._combo_perfil.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._combo_perfil.currentIndexChanged.connect(self._on_perfil_selected)
        sel_lay.addWidget(self._combo_perfil)

        btn_novo = QPushButton("Novo")
        btn_novo.clicked.connect(self._new_config)
        sel_lay.addWidget(btn_novo)

        self._btn_excluir = QPushButton("Excluir")
        self._btn_excluir.clicked.connect(self._delete_config)
        sel_lay.addWidget(self._btn_excluir)

        root.addWidget(sel_group)

        # ── Cabeçalho do perfil ───────────────────────────────────────────────
        hdr_group = QGroupBox("Informações do perfil")
        hdr_form  = QFormLayout(hdr_group)
        hdr_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._edit_name = QLineEdit()
        self._edit_name.setPlaceholderText("Ex: Padrão Industrial")
        self._edit_name.textChanged.connect(self._mark_modified)
        hdr_form.addRow("Nome:", self._edit_name)

        self._edit_desc = QLineEdit()
        self._edit_desc.setPlaceholderText("Descrição do perfil e critérios utilizados")
        self._edit_desc.textChanged.connect(self._mark_modified)
        hdr_form.addRow("Descrição:", self._edit_desc)

        self._edit_author = QLineEdit()
        self._edit_author.setPlaceholderText("Responsável técnico (opcional)")
        self._edit_author.textChanged.connect(self._mark_modified)
        hdr_form.addRow("Autor:", self._edit_author)

        root.addWidget(hdr_group)

        # ── Tabela de métricas ────────────────────────────────────────────────
        tbl_group = QGroupBox("Critérios por métrica")
        tbl_lay   = QVBoxLayout(tbl_group)

        info = QLabel(
            "Cada linha define os limites de uma métrica identificada pelo "
            "nome retornado pelos analyzers. Deixe campos em branco para sem limite."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #555; font-size: 11px;")
        tbl_lay.addWidget(info)

        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_DESC, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_NAME, QHeaderView.ResizeMode.Interactive
        )
        self._table.setColumnWidth(_COL_NAME, 160)
        self._table.setColumnWidth(_COL_LMIN,  90)
        self._table.setColumnWidth(_COL_LMAX,  90)
        self._table.setColumnWidth(_COL_TOL,   90)
        self._table.setColumnWidth(_COL_NOM,   80)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.itemChanged.connect(self._mark_modified)
        tbl_lay.addWidget(self._table)

        # Botões da tabela
        tbl_btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Linha")
        btn_add.clicked.connect(self._add_row)
        tbl_btn_row.addWidget(btn_add)

        btn_del = QPushButton("− Linha selecionada")
        btn_del.clicked.connect(self._del_row)
        tbl_btn_row.addWidget(btn_del)

        tbl_btn_row.addStretch()

        btn_imp = QPushButton("Importar JSON...")
        btn_imp.setToolTip("Carrega um arquivo JSON externo e popula a tabela")
        btn_imp.clicked.connect(self._import_json)
        tbl_btn_row.addWidget(btn_imp)

        btn_exp = QPushButton("Exportar JSON...")
        btn_exp.setToolTip("Salva o perfil atual como arquivo JSON em qualquer pasta")
        btn_exp.clicked.connect(self._export_json)
        tbl_btn_row.addWidget(btn_exp)

        tbl_lay.addLayout(tbl_btn_row)
        root.addWidget(tbl_group, stretch=1)

        # ── Botões do dialog ──────────────────────────────────────────────────
        dlg_btns = QDialogButtonBox()

        self._btn_salvar = QPushButton("Salvar perfil")
        self._btn_salvar.setToolTip("Grava em analysis_configs/")
        self._btn_salvar.clicked.connect(self._save_config)
        dlg_btns.addButton(self._btn_salvar, QDialogButtonBox.ButtonRole.ActionRole)

        self._btn_aplicar = QPushButton("Usar no projeto ✓")
        self._btn_aplicar.setToolTip(
            "Salva e define este perfil como ativo para o projeto corrente"
        )
        self._btn_aplicar.clicked.connect(self._apply_and_accept)
        dlg_btns.addButton(self._btn_aplicar, QDialogButtonBox.ButtonRole.AcceptRole)

        btn_fechar = QPushButton("Fechar")
        btn_fechar.clicked.connect(self.reject)
        dlg_btns.addButton(btn_fechar, QDialogButtonBox.ButtonRole.RejectRole)

        root.addWidget(dlg_btns)

    # ── Helpers de tabela ─────────────────────────────────────────────────────

    def _add_row(self, name: str = "", lmin: str = "", lmax: str = "",
                 tol: str = "", nom: str = "", desc: str = "") -> None:
        r = self._table.rowCount()
        self._table.blockSignals(True)
        self._table.insertRow(r)
        for col, val in enumerate([name, lmin, lmax, tol, nom, desc]):
            item = QTableWidgetItem(val)
            if col != _COL_NAME:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(r, col, item)
        self._table.blockSignals(False)

    def _del_row(self) -> None:
        rows = sorted({i.row() for i in self._table.selectedItems()}, reverse=True)
        for r in rows:
            self._table.removeRow(r)
        self._mark_modified()

    def _mark_modified(self) -> None:
        self._modified = True

    # ── Leitura/escrita da tabela ─────────────────────────────────────────────

    def _table_to_config(self) -> AnalysisConfig | None:
        name = self._edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Campo obrigatório", "O nome do perfil é obrigatório.")
            return None

        metrics: dict[str, MetricConfig] = {}
        for r in range(self._table.rowCount()):
            metric_name = (self._table.item(r, _COL_NAME) or QTableWidgetItem("")).text().strip()
            if not metric_name:
                continue

            def _float(col: int) -> float | None:
                item = self._table.item(r, col)
                if item is None:
                    return None
                txt = item.text().strip()
                if not txt:
                    return None
                try:
                    return float(txt)
                except ValueError:
                    return None

            desc_item = self._table.item(r, _COL_DESC)
            desc = desc_item.text().strip() if desc_item else ""

            mc = MetricConfig(
                limit_min     = _float(_COL_LMIN),
                limit_max     = _float(_COL_LMAX),
                tolerance_pct = _float(_COL_TOL),
                nominal       = _float(_COL_NOM),
                description   = desc,
            )
            if not mc.is_empty() or mc.description:
                metrics[metric_name] = mc

        return AnalysisConfig(
            name        = name,
            description = self._edit_desc.text().strip(),
            author      = self._edit_author.text().strip(),
            metrics     = metrics,
        )

    def _populate_table(self, cfg: AnalysisConfig) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for mname, mc in sorted(cfg.metrics.items()):
            self._add_row(
                name = mname,
                lmin = f"{mc.limit_min}"     if mc.limit_min     is not None else "",
                lmax = f"{mc.limit_max}"     if mc.limit_max     is not None else "",
                tol  = f"{mc.tolerance_pct}" if mc.tolerance_pct is not None else "",
                nom  = f"{mc.nominal}"       if mc.nominal       is not None else "",
                desc = mc.description,
            )
        self._table.blockSignals(False)
        self._modified = False

    # ── Combo de perfis ───────────────────────────────────────────────────────

    def _populate_combo(self) -> None:
        self._combo_perfil.blockSignals(True)
        self._combo_perfil.clear()
        for cfg in self._configs:
            fname = f"{_slug(cfg.name)}.json"
            self._combo_perfil.addItem(cfg.name, userData=fname)
        if not self._configs:
            self._combo_perfil.addItem("(nenhum perfil — clique em Novo)", userData=None)
        self._combo_perfil.blockSignals(False)

        has = bool(self._configs)
        self._btn_excluir.setEnabled(has)
        self._btn_aplicar.setEnabled(has)
        self._btn_salvar.setEnabled(True)

        if has:
            self._load_config_at(0)

    def _on_perfil_selected(self, index: int) -> None:
        if self._modified:
            ans = QMessageBox.question(
                self, "Alterações não salvas",
                "O perfil foi modificado. Descartar as alterações?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans == QMessageBox.StandardButton.No:
                return
        self._load_config_at(index)

    def _load_config_at(self, index: int) -> None:
        if index < 0 or index >= len(self._configs):
            return
        cfg = self._configs[index]
        self._edit_name.blockSignals(True)
        self._edit_desc.blockSignals(True)
        self._edit_author.blockSignals(True)
        self._edit_name.setText(cfg.name)
        self._edit_desc.setText(cfg.description)
        self._edit_author.setText(cfg.author)
        self._edit_name.blockSignals(False)
        self._edit_desc.blockSignals(False)
        self._edit_author.blockSignals(False)
        self._populate_table(cfg)

        fname = self._combo_perfil.itemData(index)
        self._current_path = _CONFIGS_DIR / fname if fname else None
        self._modified = False

    # ── Ações ─────────────────────────────────────────────────────────────────

    def _new_config(self) -> None:
        self._table.setRowCount(0)
        self._edit_name.clear()
        self._edit_desc.clear()
        self._edit_author.clear()
        self._current_path = None
        self._modified = False
        self._combo_perfil.setCurrentIndex(-1)
        self._edit_name.setFocus()

    def _delete_config(self) -> None:
        idx = self._combo_perfil.currentIndex()
        if idx < 0 or idx >= len(self._configs):
            return
        fname = self._combo_perfil.itemData(idx)
        path  = _CONFIGS_DIR / fname if fname else None
        ans = QMessageBox.question(
            self, "Excluir perfil",
            f"Excluir o arquivo '{fname}'? Esta ação não pode ser desfeita.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        if path and path.exists():
            path.unlink()
        self._configs = find_configs()
        self._populate_combo()

    def _save_config(self) -> bool:
        cfg = self._table_to_config()
        if cfg is None:
            return False

        # Nome do arquivo baseado no nome do perfil
        fname = f"{_slug(cfg.name)}.json"
        dest  = self._current_path or (_CONFIGS_DIR / fname)
        cfg.save(dest)

        self._configs = find_configs()
        self._populate_combo()

        # Seleciona o perfil recém salvo
        for i in range(self._combo_perfil.count()):
            if self._combo_perfil.itemData(i) == fname:
                self._combo_perfil.blockSignals(True)
                self._combo_perfil.setCurrentIndex(i)
                self._combo_perfil.blockSignals(False)
                break

        self._modified = False
        return True

    def _apply_and_accept(self) -> None:
        if self._modified:
            if not self._save_config():
                return

        idx = self._combo_perfil.currentIndex()
        if idx < 0 or idx >= len(self._configs):
            return

        cfg = self._configs[idx]
        set_active_analysis_config(cfg)
        self._selected_filename = self._combo_perfil.itemData(idx) or ""
        self.accept()

    def _import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar perfil JSON", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            cfg  = AnalysisConfig.from_dict(data)
        except Exception as exc:
            QMessageBox.critical(self, "Erro ao importar", str(exc))
            return

        self._edit_name.setText(cfg.name)
        self._edit_desc.setText(cfg.description)
        self._edit_author.setText(cfg.author)
        self._populate_table(cfg)
        self._mark_modified()
        QMessageBox.information(
            self, "Importado",
            f"Perfil '{cfg.name}' importado com {len(cfg.metrics)} métrica(s).\n"
            "Clique em 'Salvar perfil' para gravar na biblioteca local."
        )

    def _export_json(self) -> None:
        cfg = self._table_to_config()
        if cfg is None:
            return
        fname_sugerido = f"{_slug(cfg.name)}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar perfil JSON", fname_sugerido, "JSON (*.json)"
        )
        if not path:
            return
        try:
            cfg.save(Path(path))
            QMessageBox.information(
                self, "Exportado",
                f"Perfil '{cfg.name}' exportado para:\n{path}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Erro ao exportar", str(exc))

    # ── Resultado do dialog ───────────────────────────────────────────────────

    @property
    def selected_filename(self) -> str:
        """Nome do arquivo do perfil selecionado (só válido após accept())."""
        return getattr(self, "_selected_filename", "")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slug(name: str) -> str:
    """Converte nome de perfil em nome de arquivo seguro."""
    import re
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    return s or "perfil"
