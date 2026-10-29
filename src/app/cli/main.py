"""CLI da Plataforma de Bring-up.

Uso:
    python -m bringup run [--target TARGET] [--json]
    python -m bringup list-probes
    python -m bringup --version

Exemplos:
    python -m bringup run
    python -m bringup run --json > resultado.json
    python -m bringup run --target stm32f446retx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bringup",
        description="Plataforma de Bring-up STM32 via ST-Link.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"bringup-platform {__version__}",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMANDO")

    # ------------------------------------------------------------------ run
    p_run = sub.add_parser("run", help="Executa a suite de testes embutidos.")
    p_run.add_argument(
        "--target",
        default="stm32f446retx",
        metavar="ID",
        help="Identificador pyOCD do alvo (padrão: stm32f446retx)",
    )
    p_run.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Saída em JSON (útil para integração CI)",
    )

    # ------------------------------------------------------------- list-probes
    sub.add_parser("list-probes", help="Lista ST-Link detectados.")

    return parser


# ---------------------------------------------------------------------------
# Subcomandos
# ---------------------------------------------------------------------------


def _cmd_run(args: argparse.Namespace) -> int:
    from adapters.stlink.adiv5 import StLinkADIv5
    from core.pal.access import PeripheralAccessLayer
    from core.svd.parser import parse
    from tests_builtin import STANDARD_SUITE, run_suite, summarize, TestStatus

    svd_path = Path(__file__).parents[3] / "devices" / "stm32f446" / "STM32F446.svd"

    print(f"Conectando a '{args.target}'...", flush=True)
    try:
        adiv5 = StLinkADIv5(target=args.target, mode="halt")
        adiv5._open()
        dpidr = adiv5.init()
    except Exception as exc:
        print(f"ERRO: Não foi possível conectar ao probe — {exc}", file=sys.stderr)
        return 2

    print(f"Conectado.  DPIDR=0x{dpidr:08X}\n")

    svd = parse(svd_path)
    pal = PeripheralAccessLayer(adiv5, svd)

    try:
        results = run_suite(pal, STANDARD_SUITE)
    finally:
        adiv5._close()

    if args.as_json:
        _print_json(results)
    else:
        _print_table(results)

    counts = summarize(results)
    fail_err = counts[TestStatus.FAIL] + counts[TestStatus.ERROR]
    return 1 if fail_err else 0


def _print_table(results: list) -> None:
    _SYM = {"PASS": "✓", "FAIL": "✗", "ERROR": "!", "SKIP": "-"}
    width_name = max(len(r.name) for r in results) + 2
    print(f"{'Status':<6}  {'Teste':<{width_name}}  {'ms':>6}  Mensagem")
    print("-" * 72)
    for r in results:
        sym = _SYM.get(r.status.value, "?")
        print(
            f"[{sym}] {r.status.value:<4}  {r.name:<{width_name}}  "
            f"{r.duration_ms:>6.1f}  {r.message}"
        )
    print()


def _print_json(results: list) -> None:
    payload = [
        {
            "name":        r.name,
            "status":      r.status.value,
            "message":     r.message,
            "measured":    r.measured,
            "expected":    r.expected,
            "duration_ms": r.duration_ms,
        }
        for r in results
    ]
    print(json.dumps(payload, indent=2, default=str))


def _cmd_list_probes() -> int:
    from app.services.device import DeviceService

    probes = DeviceService.list_probes()
    if not probes:
        print("Nenhum ST-Link detectado.")
        return 1
    for i, desc in enumerate(probes):
        print(f"  [{i}] {desc}")
    return 0


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return _cmd_run(args)
    if args.command == "list-probes":
        return _cmd_list_probes()

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
