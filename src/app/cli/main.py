"""CLI da Plataforma de Bring-up — Sprint 01 entrega apenas o esqueleto."""

from __future__ import annotations

import argparse
import sys

from app import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bringup",
        description="Plataforma de Bring-up via SWD/JTAG — interface de linha de comando.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"bringup-platform {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    print(
        "CLI ainda não implementada no Sprint 01 — execute 'bringup-gui' para abrir a GUI.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
