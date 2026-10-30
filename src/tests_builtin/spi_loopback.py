"""SpiLoopbackTest — loopback MOSI→MISO conforme pinos definidos no BoardConfig.

Conexão necessária (NUCLEO-F446RE):
    D11 (PA7 = SPI1_MOSI)  ──►──  D12 (PA6 = SPI1_MISO)
"""

from __future__ import annotations

from core.board.config import BoardConfig, get_active_board
from instruments.spi import SpiBaudDiv, SpiInstrument
from tests_builtin.base import BuiltinTest, TestResult

_TEST_BYTE = 0x5A


class SpiLoopbackTest(BuiltinTest):
    name        = "SPI Loopback"
    description = "Transfere 0x5A pela SPI e aguarda eco (pinos definidos no BoardConfig)"

    def __init__(self, cfg: BoardConfig | None = None) -> None:
        self._cfg = cfg

    def _run(self, pal) -> TestResult:
        cfg  = self._cfg if self._cfg is not None else get_active_board()
        scfg = cfg.spi
        if scfg is None:
            return self._skip(f"{cfg.name}: sem SPI de loopback configurada no BoardConfig")

        # Reúne os 3 pinos num único dict para salvar/restaurar
        pins = {"sck": scfg.sck, "miso": scfg.miso, "mosi": scfg.mosi}
        saved = {
            key: {
                "moder": pal.read_field(p.port, "MODER", p.moder_field),
                "afr":   pal.read_field(p.port, p.afr_reg, p.afr_field),
            }
            for key, p in pins.items()
        }

        # Habilita clocks (GPIO + SPI)
        ports_needed = {p.port for p in pins.values()}
        for port in ports_needed:
            pal.modify_field("RCC", "AHB1ENR", f"GPIO{port[-1]}EN", 1)
        pal.modify_field("RCC", scfg.clock_reg, scfg.clock_field, 1)

        # Configura pinos como Alternate Function
        for p in pins.values():
            pal.modify_field(p.port, "MODER", p.moder_field, 0b10)
            pal.modify_field(p.port, p.afr_reg, p.afr_field, p.af)

        spi = SpiInstrument(scfg.n, pal)
        try:
            spi.configure(mode=0, baud_div=SpiBaudDiv.DIV_256, sw_nss=True)
            spi.enable()

            received = spi.transfer_byte(_TEST_BYTE)

            if received == _TEST_BYTE:
                return self._pass(
                    f"eco OK 0x{_TEST_BYTE:02X}  (DIV_256)",
                    measured=received,
                    expected=_TEST_BYTE,
                )
            return self._fail(
                f"esperado 0x{_TEST_BYTE:02X}, recebido 0x{received:02X}",
                measured=received,
                expected=_TEST_BYTE,
            )

        except TimeoutError as exc:
            mosi = scfg.mosi
            miso = scfg.miso
            return self._fail(
                f"timeout — verifique fio {mosi.port}{mosi.pin}→{miso.port}{miso.pin}: {exc}",
                measured=None,
                expected=_TEST_BYTE,
            )
        finally:
            spi.disable()
            for key, p in pins.items():
                pal.modify_field(p.port, "MODER", p.moder_field, saved[key]["moder"])
                pal.modify_field(p.port, p.afr_reg, p.afr_field, saved[key]["afr"])
            pal.modify_field("RCC", scfg.clock_reg, scfg.clock_field, 0)
