"""Testes unitários de core.project.ioc — .ioc sintético, sem arquivos externos.

Execução:
    pytest tests/unit/test_project_ioc.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.project.config import ProjectConfig
from core.project.ioc import parse_ioc

_IOC = r"""#MicroXplorer Configuration settings - do not modify
Mcu.CPN=STM32F446RET6
Mcu.Family=STM32F4
Mcu.Name=STM32F446R(C-E)Tx
Mcu.Package=LQFP64
Mcu.UserName=STM32F446RETx
ProjectManager.ProjectName=PLACA_TESTE
PA13.Mode=Serial_Wire
PA13.Signal=SYS_JTMS-SWDIO
PA14.Mode=Serial_Wire
PA14.Signal=SYS_JTCK-SWCLK
PH0-OSC_IN.Mode=HSE-External-Oscillator
PH0-OSC_IN.Signal=RCC_OSC_IN
PA0-WKUP.Signal=ADCx_IN0
SH.ADCx_IN0.0=ADC1_IN0,IN0
SH.ADCx_IN0.1=ADC2_IN0,IN0
SH.ADCx_IN0.ConfNb=2
PF10.Signal=SharedAnalog_PF10
SH.SharedAnalog_PF10.0=ADC3_INN2
SH.SharedAnalog_PF10.1=ADC3_INP6,IN6-Single-Ended
SH.SharedAnalog_PF10.ConfNb=2
PA9.Mode=Asynchronous
PA9.Signal=USART1_TX
PA10.Mode=Asynchronous
PA10.Signal=USART1_RX
USART1.BaudRate=9600
PA5.Mode=Full_Duplex_Master
PA5.Signal=SPI1_SCK
PA8.Signal=S_TIM1_CH1
PA11.Signal=TIM1_CH4
TIM1.Channel-PWM\ Generation4\ CH4=TIM_CHANNEL_4
PC4.GPIOParameters=GPIO_Label
PC4.GPIO_Label=LED1
PC4.Signal=GPIO_Output
PC5.GPIO_Label=BOT 1
PC5.GPIO_PuPd=GPIO_PULLUP
PC5.Signal=GPIO_Input
PB5.GPIO_ModeDefaultEXTI=GPIO_MODE_IT_FALLING
PB5.GPIO_PuPd=GPIO_PULLUP
PB5.Signal=GPXTI5
PA12.GPIO_Label=USB_DP
PA12.Signal=USB_OTG_FS_DP
VP_SYS_VS_Systick.Mode=SysTick
VP_SYS_VS_Systick.Signal=SYS_VS_Systick
"""


@pytest.fixture
def ioc():
    return parse_ioc(_IOC)


class TestIocMcu:
    def test_mcu_fields(self, ioc) -> None:
        assert ioc.project_name == "PLACA_TESTE"
        assert ioc.cpn == "STM32F446RET6"
        assert ioc.family == "STM32F4"
        assert ioc.package == "LQFP64"

    def test_target_matches_board_config_format(self, ioc) -> None:
        from boards.nucleo_f446re import BOARD
        assert ioc.target == BOARD.target


class TestIocPins:
    def test_debug_and_oscillator_pins_skipped(self, ioc) -> None:
        assert ioc.skipped == [
            "PA13 (SYS_JTMS-SWDIO)", "PA14 (SYS_JTCK-SWCLK)", "PH0-OSC_IN (RCC_OSC_IN)",
        ]
        assert all(p.pin not in (13, 14) or p.port != "GPIOA" for p in ioc.pins.values())

    def test_virtual_pins_ignored(self, ioc) -> None:
        assert not any("systick" in k for k in ioc.pins)

    def test_uart_with_baudrate(self, ioc) -> None:
        tx = ioc.pins["usart1_tx"]
        assert (tx.port, tx.pin) == ("GPIOA", 9)
        assert tx.peripheral.periph_type == "UART"
        assert tx.peripheral.name == "USART1"
        assert tx.peripheral.role == "TX"
        assert tx.peripheral.params == {"baudrate": 9600}

    def test_spi(self, ioc) -> None:
        sck = ioc.pins["spi1_sck"]
        assert (sck.peripheral.periph_type, sck.peripheral.role) == ("SPI", "SCK")

    def test_gpio_label_becomes_signal_name(self, ioc) -> None:
        assert ioc.pins["led1"].port == "GPIOC"
        assert ioc.pins["led1"].peripheral.periph_type == "GPIO"
        assert "bot_1" in ioc.pins
        assert "pull-up" in ioc.pins["bot_1"].description

    def test_shared_adc_picks_first_option(self, ioc) -> None:
        adc = ioc.pins["adc1_in0"]
        assert (adc.port, adc.pin) == ("GPIOA", 0)
        assert (adc.peripheral.name, adc.peripheral.role) == ("ADC1", "IN0")

    def test_shared_adc_prefers_positive_input(self, ioc) -> None:
        adc = ioc.pins["adc3_inp6"]
        assert (adc.port, adc.pin) == ("GPIOF", 10)
        assert "ADC3_INP6" in adc.description

    def test_exti_edge(self, ioc) -> None:
        exti = ioc.pins["pb5_exti"]
        assert exti.peripheral.periph_type == "EXTI"
        assert (exti.peripheral.name, exti.peripheral.role) == ("EXTI5", "FALLING")

    def test_tim_pwm_detected(self, ioc) -> None:
        assert ioc.pins["tim1_ch4"].peripheral.periph_type == "PWM"

    def test_unsupported_function_kept_as_gpio_with_signal(self, ioc) -> None:
        usb = ioc.pins["usb_dp"]
        assert usb.peripheral.periph_type == "GPIO"
        assert "USB_OTG_FS_DP" in usb.description

    def test_pins_sorted_by_port_and_number(self, ioc) -> None:
        order = [(p.port, p.pin) for p in ioc.pins.values()]
        assert order == sorted(order)

    def test_duplicate_names_get_suffix(self) -> None:
        text = "PA1.GPIO_Label=LED\nPA1.Signal=GPIO_Output\n" \
               "PA2.GPIO_Label=LED\nPA2.Signal=GPIO_Output\n"
        assert list(parse_ioc(text).pins) == ["led", "led_2"]

    def test_round_trip_through_project_json(self, ioc) -> None:
        proj = ProjectConfig(name="x", project_code="y", board="z", pins=ioc.pins)
        again = ProjectConfig.from_dict(proj.to_dict())
        assert again.pins == ioc.pins


class TestIocBoardMatch:
    """Duas placas com o mesmo MCU: kit ST pelo nome, placa própria por board=custom."""

    _BOARDS = [SimpleNamespace(name="NUCLEO-H753ZI", target="stm32h753zitx"),
               SimpleNamespace(name="MINHA-PLACA", target="stm32h753zitx"),
               SimpleNamespace(name="NUCLEO-F446RE", target="stm32f446retx")]

    @pytest.mark.parametrize(("board_key", "expected"), [
        ("NUCLEO-H753ZI", "NUCLEO-H753ZI"),
        ("custom", "MINHA-PLACA"),
        ("", "NUCLEO-H753ZI"),
    ])
    def test_same_mcu_two_boards(self, board_key, expected) -> None:
        ioc = parse_ioc(f"Mcu.UserName=STM32H753ZITx\nboard={board_key}\n")
        assert ioc.match_board(self._BOARDS).name == expected

    def test_unknown_mcu(self) -> None:
        assert parse_ioc("Mcu.UserName=STM32G474RETx\n").match_board(self._BOARDS) is None


class TestProjectDialogImport:
    def test_import_fills_table_and_selects_board(self, qtbot, tmp_path) -> None:
        from PySide6.QtWidgets import QMessageBox

        from app.gui.project_dialog import ProjectEditorDialog

        path = tmp_path / "placa.ioc"
        path.write_text(_IOC, encoding="utf-8")
        dlg = ProjectEditorDialog()
        qtbot.addWidget(dlg)
        with patch("app.gui.project_dialog.QFileDialog.getOpenFileName",
                   return_value=(str(path), "")), \
             patch("app.gui.project_dialog.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes):
            dlg._import_ioc()
        pins = dlg._pin_table.pins()
        assert "usart1_tx" in pins and "led1" in pins
        assert dlg._name.text() == "PLACA_TESTE"
        assert dlg._board_combo.currentText() == "NUCLEO-F446RE"
