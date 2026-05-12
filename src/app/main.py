"""Entry point da aplicação GUI (Sprint 01)."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from app import __version__
from app._metadata import AUTHOR, NAME, build_label
from app.gui.main_window import MainWindow
from app.logging_setup import is_dev_mode, setup_logging

logger = logging.getLogger("app.main")


def main() -> int:
    log_path = setup_logging()

    logger.info("Iniciando %s (build %s)", NAME, build_label())
    logger.info("Autor: %s", AUTHOR)
    logger.info("Modo: %s", "desenvolvimento" if is_dev_mode() else "produção")
    if log_path is not None:
        logger.info("Log de arquivo: %s", log_path)

    app = QApplication(sys.argv)
    app.setApplicationName("Bring-up Platform")
    app.setApplicationDisplayName(NAME)
    app.setApplicationVersion(__version__)

    window = MainWindow()
    window.show()
    logger.info("Janela principal aberta")

    code = app.exec()
    logger.info("Aplicação encerrada (exit=%d)", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
