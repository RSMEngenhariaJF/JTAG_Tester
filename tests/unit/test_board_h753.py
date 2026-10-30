"""Testes unitários do suporte à NUCLEO-H753ZI (STM32H7) — sem hardware.

Cobre: sinônimos de campo do SVD (MODER5 ↔ MODE5...), BoardConfig e projeto
da placa, conexão com pyocd_target/connect_mode/resume, SKIP dos loopbacks sem
USART/SPI e os plugins de TESTES_PLATAFORMA/H7.

Execução:
    pytest tests/unit/test_board_h753.py -v
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.svd.model import SvdField, SvdRegister, _field_aliases
from core.svd.parser import parse
from tests_builtin.base import TestStatus

ROOT = Path(__file__).resolve().parents[2]
SVD_H753 = ROOT / "devices" / "stm32h753" / "STM32H753.svd"
SVD_F446 = ROOT / "devices" / "stm32f446" / "STM32F446.svd"


# ── Sinônimos de campo ────────────────────────────────────────────────────────

class TestFieldAliases:
    @pytest.mark.parametrize("name,alias", [
        ("MODER5", "MODE5"), ("MODE5", "MODER5"), ("ODR13", "OD13"), ("ID13", "IDR13"),
        ("AFRH8", "AFSEL8"), ("AFRL3", "AFSEL3"), ("AFSEL14", "AFRH14"), ("AFSEL2", "AFRL2"),
        ("OSPEEDR2", "OSPEED2"), ("PUPD4", "PUPDR4"),
    ])
    def test_pairs(self, name: str, alias: str) -> None:
        assert _field_aliases(name) == [alias]

    def test_unrelated_name_has_no_alias(self) -> None:
        assert _field_aliases("GPIOAEN") == []

    def test_exact_name_wins(self) -> None:
        reg = SvdRegister("R", "", 0, 32, "", 0, (
            SvdField("MODE5", "", 10, 2, ""), SvdField("MODER5", "", 0, 2, ""),
        ))
        assert reg.field("MODER5").bit_offset == 0
        assert reg.field("MODE5").bit_offset == 10

    def test_unknown_field_still_raises(self) -> None:
        reg = SvdRegister("R", "", 0, 32, "", 0, (SvdField("MODE5", "", 10, 2, ""),))
        with pytest.raises(KeyError, match="MODER6"):
            reg.field("MODER6")

    def test_h753_svd_accepts_f4_names(self) -> None:
        dev = parse(SVD_H753)
        gpiob = dev.peripheral("GPIOB")
        assert gpiob.base_address == 0x58020400
        assert gpiob.register("MODER").field("MODER0").name == "MODE0"
        assert gpiob.register("AFRH").field("AFRH14").bit_offset == 24
        assert dev.peripheral("RCC").address_of("AHB4ENR") == 0x580244E0

    def test_f446_svd_unchanged(self) -> None:
        f = parse(SVD_F446).peripheral("GPIOA").register("MODER").field("MODER5")
        assert f.name == "MODER5"


# ── Placa e projeto ───────────────────────────────────────────────────────────

class TestBoardAndProject:
    def test_board_discovered(self) -> None:
        from core.board.loader import find_boards
        board = next(b for b in find_boards() if b.name == "NUCLEO-H753ZI")
        assert board.pyocd_target == "stm32h743xx"
        assert board.connect_mode == "under-reset" and board.resume_after_connect
        assert board.usart is None and board.spi is None
        assert (ROOT / board.svd_path).is_file()

    def test_board_matches_cubemx_target(self) -> None:
        from boards.nucleo_h753zi import BOARD
        assert BOARD.target == "stm32h753zitx"     # Mcu.UserName.lower() do .ioc

    def test_project_points_to_board(self) -> None:
        from core.project.loader import find_projects
        proj = next(p for p in find_projects() if p.project_code == "NUCLEO-H753-001")
        assert proj.board == "nucleo_h753zi"
        assert {"led", "led_amarelo", "led_vermelho", "button"} <= set(proj.pins)
        assert proj.pin("button").active_low is False

    def test_f446_defaults_unchanged(self) -> None:
        from boards.nucleo_f446re import BOARD
        assert (BOARD.pyocd_target, BOARD.connect_mode, BOARD.resume_after_connect) == \
            ("", "halt", False)


# ── Conexão ───────────────────────────────────────────────────────────────────

class TestConnect:
    def _connect(self, board, qtbot):
        from app.services.device import DeviceService
        svc = DeviceService()
        adiv5 = MagicMock()
        adiv5.init.return_value = 0x6BA02477
        adiv5.is_halted.return_value = True
        with patch("app.services.device.parse", return_value=MagicMock()), \
             patch("adapters.stlink.adiv5.StLinkADIv5", return_value=adiv5) as cls:
            svc.connect(board)
        return cls, adiv5

    def test_h753_uses_pyocd_target_mode_and_resumes(self, qtbot) -> None:
        from boards.nucleo_h753zi import BOARD
        cls, adiv5 = self._connect(BOARD, qtbot)
        assert cls.call_args.kwargs["target"] == "stm32h743xx"
        assert cls.call_args.kwargs["mode"] == "under-reset"
        adiv5.resume.assert_called_once()

    def test_f446_keeps_halt_and_no_resume(self, qtbot) -> None:
        from boards.nucleo_f446re import BOARD
        cls, adiv5 = self._connect(BOARD, qtbot)
        assert cls.call_args.kwargs["target"] == "stm32f446retx"
        assert cls.call_args.kwargs["mode"] == "halt"
        adiv5.resume.assert_not_called()


# ── Loopbacks sem USART/SPI ───────────────────────────────────────────────────

class TestLoopbackSkip:
    def test_usart_and_spi_skip_without_config(self) -> None:
        from boards.nucleo_f446re import BOARD
        from tests_builtin.spi_loopback import SpiLoopbackTest
        from tests_builtin.usart_loopback import UsartLoopbackTest
        cfg = dataclasses.replace(BOARD, usart=None, spi=None)
        pal = MagicMock()
        for test in (UsartLoopbackTest(cfg), SpiLoopbackTest(cfg)):
            r = test.run(pal)
            assert r.status == TestStatus.SKIP and "loopback" in r.message
        pal.modify_field.assert_not_called()


# ── Plugins H7 ────────────────────────────────────────────────────────────────

class TestH7Plugins:
    @pytest.fixture
    def plugins(self):
        from tests_builtin.loader import PluginLoader
        d = ROOT / "TESTES_PLATAFORMA" / "H7"
        return {t.name: t for f in sorted(d.glob("*.py"))
                for t in PluginLoader.load_from_file(f)}

    def test_agent_skips_on_other_chip(self, plugins) -> None:
        from boards.nucleo_f446re import BOARD
        from core.board.config import set_active_board
        set_active_board(BOARD)
        r = plugins["USART Agente H7"].run(MagicMock())
        assert r.status == TestStatus.SKIP and "H74x" in r.message
