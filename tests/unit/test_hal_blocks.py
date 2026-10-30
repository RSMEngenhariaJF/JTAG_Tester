"""Testes unitários da HAL (src/hal) e dos blocos de TESTES_PLATAFORMA/BLOCOS — sem placa.

Usam os SVDs reais (F446 e H753) com uma memória em dicionário: conferem a
escolha de registradores/bits por família, cálculos de timing, salvar/restaurar
pinos e a integração dos blocos com o Plano de testes. O comportamento elétrico
foi validado na NUCLEO-H753ZI (ver docstrings dos módulos).

Execução:
    pytest tests/unit/test_hal_blocks.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.pal.access import PeripheralAccessLayer
from core.project.config import PeripheralRef, PinDef, ProjectConfig, TestPlanEntry
from core.svd.parser import parse
from hal.common import (
    default_af,
    family,
    find_clock,
    restore_pin,
    set_af,
    snapshot_pin,
)
from tests_builtin import params as tp

ROOT = Path(__file__).resolve().parents[2]
SVD = {"H7": ROOT / "devices/stm32h753/STM32H753.svd",
       "F4": ROOT / "devices/stm32f446/STM32F446.svd"}


class DictMem:
    def __init__(self) -> None:
        self.m: dict[int, int] = {}

    def read_mem32(self, addr: int) -> int:
        return self.m.get(addr, 0)

    def write_mem32(self, addr: int, value: int) -> None:
        self.m[addr] = value & 0xFFFFFFFF


@pytest.fixture(params=["H7", "F4"])
def pal(request):
    return PeripheralAccessLayer(DictMem(), parse(SVD[request.param]))


@pytest.fixture
def pal_h7():
    return PeripheralAccessLayer(DictMem(), parse(SVD["H7"]))


# ── common ────────────────────────────────────────────────────────────────────

class TestCommon:
    def test_family(self, pal) -> None:
        expected = "H7" if pal.device.peripheral("RCC").base_address == 0x58024400 else "F4"
        assert family(pal) == expected

    @pytest.mark.parametrize("fam,name,reg,field", [
        ("H7", "GPIOB", "AHB4ENR", "GPIOBEN"), ("H7", "USART3", "APB1LENR", "USART3EN"),
        ("H7", "UART7", "APB1LENR", "USART7EN"), ("H7", "FDCAN1", "APB1HENR", "FDCANEN"),
        ("H7", "ETH", "AHB1ENR", "ETH1MACEN"), ("F4", "GPIOB", "AHB1ENR", "GPIOBEN"),
        ("F4", "CAN1", "APB1ENR", "CAN1EN"), ("F4", "SPI1", "APB2ENR", "SPI1EN"),
    ])
    def test_find_clock(self, fam, name, reg, field) -> None:
        p = PeripheralAccessLayer(DictMem(), parse(SVD[fam]))
        assert find_clock(p, name) == (reg, field)

    def test_missing_clock(self, pal_h7) -> None:
        with pytest.raises(LookupError):
            find_clock(pal_h7, "CAN1")

    @pytest.mark.parametrize("name,fam,af", [
        ("USART3", "H7", 7), ("UART4", "H7", 8), ("SPI1", "H7", 5), ("I2C1", "H7", 4),
        ("FDCAN1", "H7", 9), ("ETH", "H7", 11), ("USART6", "F4", 8), ("SPI3", "F4", 6),
        ("CAN1", "F4", 9),
    ])
    def test_default_af(self, name, fam, af) -> None:
        assert default_af(name, fam) == af

    def test_af_override_and_unknown(self) -> None:
        assert default_af("USART3", "H7", override=3) == 3
        with pytest.raises(LookupError, match="params"):
            default_af("SAI1", "H7")

    def test_pin_snapshot_restore(self, pal) -> None:
        snap = snapshot_pin(pal, "GPIOB", 9)
        set_af(pal, "GPIOB", 9, 4, open_drain=True, pull="pull-up")
        assert pal.read_field("GPIOB", "MODER", "MODER9") == 0b10
        assert pal.read_field("GPIOB", "AFRH", "AFRH9") == 4
        assert pal.read_field("GPIOB", "OTYPER", "OT9") == 1
        restore_pin(pal, snap)
        assert snapshot_pin(pal, "GPIOB", 9) == snap


# ── cálculos de timing ────────────────────────────────────────────────────────

class TestTiming:
    def test_i2c_timingr_64mhz(self) -> None:
        from hal.i2c import timingr_100k
        t = timingr_100k(64_000_000)
        presc, scll, sclh = t >> 28, t & 0xFF, t >> 8 & 0xFF
        tick = (presc + 1) / 64e6
        period = (scll + 1 + sclh + 1) * tick
        assert presc == 15 and 8.9e-6 < period < 9.5e-6       # ~110 kHz sem tempos de borda

    def test_can_nbtp(self) -> None:
        from hal.can import nbtp_for
        nbtp, real = nbtp_for(8_000_000, 500_000)
        assert real == 500_000
        assert nbtp >> 16 & 0x1FF == 0 and nbtp >> 8 & 0xFF == 12 and nbtp & 0x7F == 1

    def test_exti_irq_numbers(self) -> None:
        from hal.exti import irq_of_line
        assert [irq_of_line(n) for n in (0, 4, 5, 9, 10, 13, 15)] == [6, 10, 23, 23, 40, 40, 40]


# ── drivers: registradores escolhidos por geração ─────────────────────────────

class TestDriverGeneration:
    def test_uart_spi_i2c_versions(self, pal) -> None:
        from hal.i2c import I2c
        from hal.spi import Spi
        from hal.uart import Uart
        h7 = family(pal) == "H7"
        assert Uart(pal, "USART3").v2 is h7
        assert Spi(pal, "SPI1").v2 is h7
        assert I2c(pal, "I2C1").v2 is h7

    def test_can_driver_by_svd(self, pal) -> None:
        from hal.can import BxcanLoopback, FdcanLoopback, can_for
        if family(pal) == "H7":
            assert isinstance(can_for(pal, "FDCAN1"), FdcanLoopback)
        else:
            assert isinstance(can_for(pal, "CAN1"), BxcanLoopback)

    def test_eth_absent_on_f446(self) -> None:
        from hal.eth import EthMdio
        with pytest.raises(LookupError):
            EthMdio(PeripheralAccessLayer(DictMem(), parse(SVD["F4"])))

    def test_uart_v2_setup_brr_and_restore(self, pal_h7) -> None:
        from hal.uart import ISR_REACK, ISR_TEACK, ST_TXE, Uart
        mem = pal_h7.mem
        mem.write_mem32(0x58024400, 1 << 2)                         # RCC_CR.HSIRDY, HSIDIV=0
        isr = pal_h7.address_of("USART3", "ISR")
        mem.write_mem32(isr, ISR_TEACK | ISR_REACK | ST_TXE)
        pal_h7.write_reg("USART3", "BRR", 0x1234)
        u = Uart(pal_h7, "USART3")
        real = u.setup(115200, half_duplex=True)
        assert pal_h7.read_reg("USART3", "BRR") == round(64e6 / 115200)
        assert pal_h7.read_reg("USART3", "CR3") & (1 << 3)
        assert real == pytest.approx(115200, rel=0.01)
        assert pal_h7.read_field("RCC", "D2CCIP2R", "USART234578SEL") == 0b011
        u.restore()
        assert pal_h7.read_reg("USART3", "BRR") == 0x1234
        assert pal_h7.read_field("RCC", "D2CCIP2R", "USART234578SEL") == 0


# ── Parâmetro de periférico ───────────────────────────────────────────────────

def _proj() -> ProjectConfig:
    return ProjectConfig("P", "P-1", "nucleo_h753zi", pins={
        "tx": PinDef("GPIOD", 8, peripheral=PeripheralRef("UART", "USART3", "TX")),
        "rx": PinDef("GPIOD", 9, peripheral=PeripheralRef("UART", "USART3", "RX", {"af": 7})),
        "scl": PinDef("GPIOB", 8, peripheral=PeripheralRef("I2C", "I2C1", "SCL")),
        "led": PinDef("GPIOB", 0),
    })


class TestPeripheralParam:
    def test_options_validate_resolve(self) -> None:
        prm = tp.Periph("Periférico", ("UART",))
        proj = _proj()
        assert prm.options(proj.pins) == ["USART3"]
        assert prm.validate("", proj) and prm.validate("I2C1", proj)
        assert prm.validate("USART3", proj) == []
        per = prm.resolve("USART3", proj)
        assert per.pin("tx").port == "GPIOD" and per.pin("RX").af == 7
        assert per.has("TX") and not per.has("CTS")
        with pytest.raises(KeyError, match="CTS"):
            per.pin("CTS")

    def test_text_param(self) -> None:
        prm = tp.Text("Endereços", "", "ex.: 0x50")
        assert prm.default() == "" and prm.validate("0x50", None) == []


# ── Blocos na biblioteca e no plano ───────────────────────────────────────────

BLOCOS = ["UART — Loopback", "SPI — Loopback MOSI→MISO", "I2C — Varredura do barramento",
          "CAN — Loopback interno", "Ethernet — PHY por MDIO", "Interrupção — EXTI de um pino",
          "GPIO — Nível de entrada", "GPIO — Pull-up/pull-down (curto)",
          "GPIO — Loopback saída→entrada", "Piscar LED"]


class TestLibrary:
    def test_blocks_listed_with_category(self) -> None:
        from tests_builtin.plan import list_library
        lib = {i.name: i for i in list_library()}
        for name in BLOCOS:
            assert name in lib, name
            assert lib[name].category != "Outros", name
        cats = [i.category for i in list_library()]
        assert cats == sorted(cats)

    def test_block_skips_when_peripheral_missing(self, pal_h7) -> None:
        from core.project.config import set_active_project
        from tests_builtin.plan import resolve_ref
        proj = _proj()
        proj.pins["can_tx"] = PinDef("GPIOA", 12, peripheral=PeripheralRef("CAN", "CAN1", "TX"))
        set_active_project(proj)
        try:
            cls = resolve_ref("TESTES_PLATAFORMA/BLOCOS/comunicacao.py:CanLoopback")
            r = cls().configure({"periferico": "CAN1"}).run(pal_h7)
        finally:
            set_active_project(None)
        assert r.status.value == "SKIP" and "CAN1" in r.message

    def test_editor_peripheral_combo(self, qtbot) -> None:
        from PySide6.QtWidgets import QComboBox

        from app.gui.test_plan_editor import TestPlanEditor
        pins = _proj().pins
        ed = TestPlanEditor(lambda: pins, library_provider=lambda: [])
        qtbot.addWidget(ed)
        ed.set_entries([TestPlanEntry("TESTES_PLATAFORMA/BLOCOS/comunicacao.py:UartLoopback", "U")])
        combo = next(w for w in ed._scroll.widget().findChildren(QComboBox)
                     if w.findText("USART3") >= 0)
        assert combo.currentText() == "USART3"
        assert ed.entries()[0].params["periferico"] == "USART3"
        assert ed.validate(pins) == []
