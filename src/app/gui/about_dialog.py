"""Diálogo "Sobre" — versionamento, autor e ambiente.

Centraliza informações canônicas do projeto vindas de ``app._metadata``,
exibindo:

- nome, versão (com commit hash quando rodando de checkout Git) e sprint atual;
- repositório GitHub e licença;
- autor, organização e contato;
- versões de Python / PySide6 / Qt e plataforma.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import _metadata as meta


def _build_about_html() -> str:
    pyside_ver, qt_ver = meta.pyside_versions()
    return (
        f"<h2 style='margin:0'>{meta.NAME}</h2>"
        f"<p style='color:gray;margin-top:2px'>{meta.DESCRIPTION}</p>"
        "<hr>"
        f"<p><b>Versão:</b> {meta.build_label()}<br>"
        f"<b>Sprint:</b> {meta.SPRINT}<br>"
        f"<b>Especificação:</b> {meta.SPEC_VERSION}</p>"
        "<h3>Projeto</h3>"
        f"<p><b>Repositório:</b> "
        f"<a href='{meta.REPOSITORY_URL}'>{meta.REPOSITORY_URL}</a><br>"
        f"<b>Issues:</b> <a href='{meta.ISSUES_URL}'>{meta.ISSUES_URL}</a><br>"
        f"<b>Licença:</b> {meta.LICENSE}</p>"
        "<h3>Autor</h3>"
        f"<p><b>{meta.AUTHOR}</b><br>"
        f"<a href='mailto:{meta.AUTHOR_EMAIL}'>{meta.AUTHOR_EMAIL}</a></p>"
        "<h3>Ambiente</h3>"
        f"<p><b>Python:</b> {meta.python_version_str()}<br>"
        f"<b>PySide6:</b> {pyside_ver}<br>"
        f"<b>Qt:</b> {qt_ver}<br>"
        f"<b>Sistema:</b> {meta.platform_str()}</p>"
    )


def _build_about_plain() -> str:
    pyside_ver, qt_ver = meta.pyside_versions()
    return (
        f"{meta.NAME}\n"
        f"{meta.DESCRIPTION}\n\n"
        f"Versão: {meta.build_label()}\n"
        f"Sprint: {meta.SPRINT}\n"
        f"Especificação: {meta.SPEC_VERSION}\n\n"
        f"Repositório: {meta.REPOSITORY_URL}\n"
        f"Issues: {meta.ISSUES_URL}\n"
        f"Licença: {meta.LICENSE}\n\n"
        f"Autor: {meta.AUTHOR}\n"
        f"E-mail: {meta.AUTHOR_EMAIL}\n\n"
        f"Python: {meta.python_version_str()}\n"
        f"PySide6: {pyside_ver}\n"
        f"Qt: {qt_ver}\n"
        f"Sistema: {meta.platform_str()}\n"
    )


class AboutDialog(QDialog):
    """Diálogo modal com versionamento e informações do projeto."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Sobre — {meta.NAME}")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(8)

        body = QLabel(_build_about_html())
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setOpenExternalLinks(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        body.setWordWrap(True)
        layout.addWidget(body)

        buttons = QDialogButtonBox()

        btn_copy = QPushButton("Copiar info do sistema")
        btn_copy.setToolTip("Copia versão, autor e ambiente para a área de transferência.")
        btn_copy.clicked.connect(self._copy_to_clipboard)
        buttons.addButton(btn_copy, QDialogButtonBox.ButtonRole.ActionRole)

        btn_repo = QPushButton("Abrir repositório")
        btn_repo.setToolTip(meta.REPOSITORY_URL)
        btn_repo.clicked.connect(self._open_repository)
        buttons.addButton(btn_repo, QDialogButtonBox.ButtonRole.ActionRole)

        btn_close = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        if btn_close is not None:
            btn_close.clicked.connect(self.accept)
            btn_close.setDefault(True)

        layout.addWidget(buttons)

    def _copy_to_clipboard(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(_build_about_plain())

    def _open_repository(self) -> None:
        QDesktopServices.openUrl(QUrl(meta.REPOSITORY_URL))
