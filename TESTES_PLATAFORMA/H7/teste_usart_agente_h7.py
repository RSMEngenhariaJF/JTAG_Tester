"""Exemplo — H7: velocidade máxima do USART3 medida pelo agente na RAM.

Carrega stubs/stm32h7/usart_sweep.c na AXI SRAM, varre o baud rate de 115200
a 8 Mbaud (HSI 64 MHz) com o USART3 em half-duplex — eco pelo pino PD8, sem
fio externo — e calcula o BER de cada passo com analyze_ber.

O firmware da placa é interrompido (reset) durante o teste e volta a rodar no
fim. PD8 vai ao Virtual COM do STLINK-V3: um terminal aberto mostra lixo.
"""

from core.agent import max_reliable_baud, run_sweep
from core.analysis import MeasurementSet
from core.board.config import get_active_board
from tests_builtin.base import BuiltinTest, TestResult

DEV_ID_H74X_H75X = 0x450
N_BYTES = 1024
BAUD_MINIMO = 4_000_000     # critério de exemplo — ajuste ao requisito do produto


class UsartAgenteH7Test(BuiltinTest):
    name        = "USART Agente H7"
    description = "Varredura de baud do USART3 por stub na RAM; BER por passo."

    def _run(self, pal) -> TestResult:
        cfg = get_active_board()
        if cfg.expected_dev_id != DEV_ID_H74X_H75X:
            return self._skip(f"Stub só para STM32H74x/H75x (placa: {cfg.name})")
        t = pal.mem
        if not all(hasattr(t, m) for m in ("read_block32", "write_block32",
                                           "reset_and_halt", "write_core_register")):
            return self._skip("Probe sem controle de núcleo / acesso em bloco (use ST-Link)")

        t.reset_and_halt()               # clocks no estado de reset (HSI 64 MHz)
        try:
            results = run_sweep(t, n_bytes=N_BYTES)
        finally:
            # Firmware volta a rodar. No H7, reset + resume derruba o acesso de
            # debug; reabrir a sessão (modo da placa) o restaura para os testes seguintes.
            if hasattr(t, "reconnect"):
                t.reconnect()
                if cfg.resume_after_connect and t.is_halted():
                    t.resume()
            else:
                t.reset_system()

        ms = MeasurementSet()
        for r in results:
            if r.ber is not None:
                ms.add(r.ber)
        best = max_reliable_baud(results)
        if best is None:
            return self._fail("Nenhum baud rate passou sem erro", measurements=ms)
        msg = (f"maior baud sem erro: {best.baud_nominal / 1e6:.3f} Mbaud "
               f"(efetivo {best.throughput_bps / 1e6:.3f} Mb/s)")
        if best.baud_nominal >= BAUD_MINIMO:
            return self._pass(msg, measured=best.baud_nominal, expected=BAUD_MINIMO,
                              measurements=ms)
        return self._fail(msg, measured=best.baud_nominal, expected=BAUD_MINIMO,
                          measurements=ms)
