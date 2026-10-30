"""UsartLoopbackTest — loopback TX→RX conforme pinos definidos no BoardConfig.

Conexão necessária (NUCLEO-F446RE):
    D8 (PA9 = USART1_TX)  ──►──  D2 (PA10 = USART1_RX)
"""

from __future__ import annotations

from core.board.config import BoardConfig, get_active_board
from instruments.rcc_helper import detect_pclk2
from instruments.usart import UsartInstrument
from tests_builtin.base import BuiltinTest, TestResult

_TEST_BYTE = 0xA5


class UsartLoopbackTest(BuiltinTest):
    name        = "USART Loopback"
    description = "Envia 0xA5 pela USART e aguarda eco (pinos definidos no BoardConfig)"

    def __init__(self, cfg: BoardConfig | None = None) -> None:
        self._cfg = cfg

    def _run(self, pal) -> TestResult:
        cfg   = self._cfg if self._cfg is not None else get_active_board()
        ucfg  = cfg.usart
        if ucfg is None:
            return self._skip(f"{cfg.name}: sem USART de loopback configurada no BoardConfig")
        tx    = ucfg.tx
        rx    = ucfg.rx

        # Salva estado original dos pinos TX e RX
        saved = {
            f"MODER_TX":  pal.read_field(tx.port, "MODER", tx.moder_field),
            f"AFR_TX":    pal.read_field(tx.port, tx.afr_reg, tx.afr_field),
            f"MODER_RX":  pal.read_field(rx.port, "MODER", rx.moder_field),
            f"AFR_RX":    pal.read_field(rx.port, rx.afr_reg, rx.afr_field),
        }

        # Habilita clocks
        pal.modify_field("RCC", "AHB1ENR", f"GPIO{tx.port[-1]}EN", 1)
        if rx.port != tx.port:
            pal.modify_field("RCC", "AHB1ENR", f"GPIO{rx.port[-1]}EN", 1)
        pal.modify_field("RCC", ucfg.clock_reg, ucfg.clock_field, 1)

        # Configura pinos como Alternate Function
        pal.modify_field(tx.port, "MODER", tx.moder_field, 0b10)
        pal.modify_field(tx.port, tx.afr_reg, tx.afr_field, tx.af)
        pal.modify_field(rx.port, "MODER", rx.moder_field, 0b10)
        pal.modify_field(rx.port, rx.afr_reg, rx.afr_field, rx.af)

        usart = UsartInstrument(ucfg.n, pal)
        try:
            f_clk = detect_pclk2(pal)
            usart.configure(baud=ucfg.loopback_baud, f_clk=f_clk)
            usart.enable()

            usart.send_byte(_TEST_BYTE)
            received = usart.receive_byte(timeout_ms=200)

            if received == _TEST_BYTE:
                return self._pass(
                    f"eco OK 0x{_TEST_BYTE:02X} @ {ucfg.loopback_baud} baud"
                    f"  (PCLK2={f_clk // 1_000_000} MHz)",
                    measured=received,
                    expected=_TEST_BYTE,
                )
            return self._fail(
                f"esperado 0x{_TEST_BYTE:02X}, recebido 0x{received:02X}",
                measured=received,
                expected=_TEST_BYTE,
            )

        except TimeoutError as exc:
            pin_tx = f"{tx.port}{tx.pin}"
            pin_rx = f"{rx.port}{rx.pin}"
            return self._fail(
                f"timeout — verifique fio {pin_tx}→{pin_rx}: {exc}",
                measured=None,
                expected=_TEST_BYTE,
            )
        finally:
            usart.disable()
            pal.modify_field(tx.port, "MODER", tx.moder_field, saved["MODER_TX"])
            pal.modify_field(tx.port, tx.afr_reg, tx.afr_field, saved["AFR_TX"])
            pal.modify_field(rx.port, "MODER", rx.moder_field, saved["MODER_RX"])
            pal.modify_field(rx.port, rx.afr_reg, rx.afr_field, saved["AFR_RX"])
            pal.modify_field("RCC", ucfg.clock_reg, ucfg.clock_field, 0)
