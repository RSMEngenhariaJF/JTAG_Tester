"""Prova de conceito: varredura de baud do USART3 por stub de RAM (NUCLEO-H743ZI/H753ZI).

Sem fio externo: USART3 em half-duplex lê o próprio eco pelo pino PD8 (TX).
PD8 também vai ao Virtual COM do ST-Link — um terminal aberto nessa porta vai
mostrar lixo durante o teste.

Uso (a partir da raiz do repositório):
    python tools/agent_usart_sweep.py [--bytes 1024] [--keep-halted]

O firmware da placa é interrompido durante o teste e volta a rodar no fim (reset).
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from adapters.stlink.adiv5 import StLinkADIv5
from core.agent import StepResult, max_reliable_baud, run_sweep


def consumer(q: queue.Queue) -> None:
    """Thread de análise: imprime cada passo assim que o stub o publica."""
    print(f"{'baud':>10} {'real':>10} {'rx/tx':>11} {'erros':>5} {'ORE':>4} "
          f"{'FE':>4} {'NE':>4} {'BER':>9} {'efetivo':>12} {'efic.':>6}")
    while (r := q.get()) is not None:
        r: StepResult
        eff = r.throughput_bps / r.baud_real * 100 if r.baud_real else 0
        print(f"{r.baud_nominal:>10} {r.baud_real:>10.0f} {r.received:>5}/{r.sent:<5} "
              f"{r.byte_errors:>5} {r.overrun:>4} {r.framing:>4} {r.noise:>4} "
              f"{r.ber.value if r.ber else float('nan'):>9.2e} "
              f"{r.throughput_bps / 1e6:>8.3f} Mb/s {eff:>5.0f}%  {'OK' if r.ok else 'FALHA'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bytes", type=int, default=1024, help="bytes por baud rate (múltiplo de 4)")
    ap.add_argument("--keep-halted", action="store_true", help="não reinicia o firmware no fim")
    args = ap.parse_args()

    q: queue.Queue = queue.Queue()
    th = threading.Thread(target=consumer, args=(q,), daemon=True)
    th.start()

    with StLinkADIv5(target="stm32h743xx", mode="under-reset") as t:
        t.reset_and_halt()
        try:
            results = run_sweep(t, n_bytes=args.bytes, out=q)
        finally:
            th.join(timeout=5)
            if not args.keep_halted:
                t.reset_system()

    best = max_reliable_baud(results)
    print()
    if best is None:
        print("Nenhum baud rate passou sem erro.")
        return 1
    print(f"Maior baud sem erro: {best.baud_nominal} (real {best.baud_real:.0f}), "
          f"taxa efetiva {best.throughput_bps / 1e6:.3f} Mb/s em {best.seconds * 1e3:.2f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
