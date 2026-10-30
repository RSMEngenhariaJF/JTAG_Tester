"""Testes unitários das subcamadas genéricas e dos blocos de clock, PWM e RS485.

Simulação sobre o SVD real do H753 (GpioSim de test_testbench) com:
  RCC que reage como o chip (HSEON → HSERDY, PLL1ON → PLL1RDY, SW → SWS,
  LSEON → LSERDY), partindo do reset (sem firmware) ou já configurado como um
  .ioc típico (HSE 25 MHz → PLL1 400 MHz); DWT_CYCCNT contando na frequência da
  árvore atual (com o cristal "real" podendo diferir do projeto); núcleo com
  halt/resume; UART7 que responde (eco opcional) e pino DE ativo enquanto há
  transmissão; pinos de PWM comutando.

Execução:
    pytest tests/unit/test_clock_pwm_rs485.py -v
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from test_testbench import GpioSim

from core.pal.access import PeripheralAccessLayer
from core.project.config import PeripheralRef, PinDef, ProjectConfig, set_active_project
from core.project.ioc import parse_ioc
from core.svd.parser import parse
from hal import afmap
from hal.clock import DHCSR, DWT_CYCCNT, clock_tree
from hal.common import pin_af
from hal.tim import PwmChannel
from tests_builtin.base import TestStatus
from tests_builtin.params import Signal
from tests_builtin.plan import resolve_ref

ROOT = Path(__file__).resolve().parents[2]
SVD_H7 = ROOT / "devices/stm32h753/STM32H753.svd"
F_CPU = 400e6

# RCC como o CubeMX deixa para HSE 25 MHz, M=5, N=160, P=2, HPRE /2, APBx /2
_RCC = {
    "CR": 1 << 2 | 1 << 16 | 1 << 17 | 1 << 24 | 1 << 25,   # HSIRDY, HSEON/RDY, PLL1ON/RDY
    "CFGR": 3 << 3 | 3,                                      # SWS = SW = PLL1
    "PLLCKSELR": 2 | 5 << 4,                                 # PLLSRC=HSE, DIVM1=5
    "PLL1DIVR": 159 | 1 << 9 | 7 << 16 | 1 << 24,            # N=160, P=2, Q=8, R=2
    "D1CFGR": 8 | 4 << 4,                                    # HPRE /2, D1PPRE /2
    "D2CFGR": 4 << 4 | 4 << 8,                               # D2PPRE1 /2, D2PPRE2 /2
    "D3CFGR": 4 << 4,                                        # D3PPRE /2
}
CLOCKS = {"HSE": 25e6, "SYSCLK": 400e6, "CPU": 400e6, "HCLK": 200e6, "APB1": 100e6,
          "APB2": 100e6, "APB3": 100e6, "APB4": 100e6, "TIM_APB1": 200e6, "TIM_APB2": 200e6,
          "fonte": "PLL1", "HSE_BYPASS": False, "LSE": 32768.0, "LSE_BYPASS": False,
          "PLL1": {"m": 5, "n": 160, "p": 2, "q": 8, "r": 2}, "PLL_SRC": "HSE",
          "DIV": {"D1CPRE": 1, "HPRE": 2, "D1PPRE": 2, "D2PPRE1": 2, "D2PPRE2": 2, "D3PPRE": 2},
          "VOS": 1, "SUPPLY": "LDO_SUPPLY"}


class ChipSim(GpioSim):
    """GpioSim + RCC/PWR que reagem, DWT, núcleo com halt, UART7 com DE e PWM."""

    def __init__(self, dev, *, reset: bool = False) -> None:
        super().__init__(dev)
        rcc, pwr = dev.peripheral("RCC"), dev.peripheral("PWR")
        self.a = {r: rcc.address_of(r) for r in ("CR", "CFGR", "BDCR")}
        self.a.update(D3CR=pwr.address_of("D3CR"), CSR1=pwr.address_of("CSR1"))
        if reset:                                   # sem firmware: HSI, núcleo parado
            self.m[self.a["CR"]] = 1 | 1 << 2
            self.m[pwr.address_of("CR3")] = 0b110    # LDOEN + SCUEN (alimentação não travada)
        else:
            for reg, v in _RCC.items():
                self.m[rcc.address_of(reg)] = v
        self.halted = reset
        self.hse_real = 25e6                        # cristal montado na placa
        self.hse_dead = False
        self.regs: dict[int, int] = {}
        self._pal = PeripheralAccessLayer(self, dev)
        u = dev.peripheral("UART7")
        self.u_isr, self.u_tdr, self.u_rdr = (u.address_of(r) for r in ("ISR", "TDR", "RDR"))
        self.echo = False
        self.rx: list[int] = []
        self.last_tx = -1.0
        self.de = ("GPIOF", 8)
        self.toggling: set[tuple[str, int]] = set()
        self._flip: dict[tuple[str, int], int] = {}

    def _level(self, port: str, pin: int) -> int:
        if (port, pin) == self.de:
            return int(time.perf_counter() - self.last_tx < 0.025)    # < repouso (~30 ms)
        if (port, pin) in self.toggling:
            self._flip[(port, pin)] = self._flip.get((port, pin), 0) ^ 1
            return self._flip[(port, pin)]
        return super()._level(port, pin)

    # núcleo (o que o idle_loop usa)
    def halt(self) -> None:
        self.halted = True

    def resume(self) -> None:
        self.halted = False

    def read_core_register(self, reg: int) -> int:
        return self.regs.get(reg, 0)

    def write_core_register(self, reg: int, value: int) -> None:
        self.regs[reg] = value

    def cpu_hz(self) -> float:
        return clock_tree(self._pal, self.hse_real).cpu

    def read_mem32(self, addr: int) -> int:
        a, v = self.a, self.m.get(addr, 0)
        if addr == a["CR"]:                          # RDY segue ON (HSE pode estar morto)
            hse = int(bool(v >> 16 & 1) and not self.hse_dead)
            return v | 1 << 2 | hse << 17 | (v >> 24 & 1) << 25
        if addr == a["CFGR"]:
            return v & ~(7 << 3) | (v & 7) << 3      # SWS = SW
        if addr == a["BDCR"]:
            return v | (v & 1) << 1                  # LSERDY = LSEON
        if addr in (a["D3CR"], a["CSR1"]):
            return v | 1 << 13                       # VOSRDY / ACTVOSRDY
        if addr == DHCSR:
            return (1 << 17) if self.halted else 0
        if addr == DWT_CYCCNT:
            f = 0.0 if self.halted else self.cpu_hz()
            return int(time.perf_counter() * f) & 0xFFFFFFFF
        if addr == self.u_isr:
            return (1 << 7 | 1 << 6 | 1 << 21 | 1 << 22) | (1 << 5 if self.rx else 0)
        if addr == self.u_rdr:
            return self.rx.pop(0) if self.rx else 0
        return super().read_mem32(addr)

    # bits só de leitura (RDY/SWS): a escrita não os grava, como no chip
    _RO = {"CR": 1 << 2 | 1 << 17 | 1 << 25 | 1 << 27 | 1 << 29, "CFGR": 7 << 3,
           "BDCR": 1 << 1, "D3CR": 1 << 13, "CSR1": 1 << 13}

    def write_mem32(self, addr: int, value: int) -> None:
        for reg, mask in self._RO.items():
            if addr == self.a[reg]:
                value &= ~mask
        if addr == self.u_tdr:
            self.last_tx = time.perf_counter()
            if self.echo:
                self.rx.append(value & 0xFF)
            return
        super().write_mem32(addr, value)


@pytest.fixture
def chip():
    dev = parse(SVD_H7)
    s = ChipSim(dev)
    return s, PeripheralAccessLayer(s, dev)


@pytest.fixture
def blank():
    """Placa sem firmware: estado de reset, núcleo parado."""
    dev = parse(SVD_H7)
    s = ChipSim(dev, reset=True)
    return s, PeripheralAccessLayer(s, dev)


@pytest.fixture
def board():
    from boards.nucleo_h753zi import BOARD
    from core.board.config import set_active_board
    set_active_board(BOARD)                    # sram_base para o laço de medida
    return BOARD


@pytest.fixture
def project():
    pwm = lambda tim, ch: PeripheralRef("PWM", tim, ch)   # noqa: E731
    uart = lambda role: PeripheralRef("UART", "UART7", role)   # noqa: E731
    proj = ProjectConfig("CT", "CT-1", "x", clocks=dict(CLOCKS), pins={
        "servo1": PinDef("GPIOB", 10, peripheral=pwm("TIM2", "CH3")),
        "servo3": PinDef("GPIOB", 14, peripheral=pwm("TIM12", "CH1")),
        "rs485_tx": PinDef("GPIOE", 8, peripheral=uart("TX")),
        "rs485_rx": PinDef("GPIOE", 7, peripheral=uart("RX")),
        "rs485_de": PinDef("GPIOF", 8, peripheral=uart("DE")),
        "rs232_tx": PinDef("GPIOC", 12, peripheral=PeripheralRef("UART", "UART5", "TX")),
    })
    set_active_project(proj)
    yield proj
    set_active_project(None)


def _run(ref: str, params: dict, pal):
    return resolve_ref(ref)().configure(params, "t").run(pal)


# ── Subcamada: AF por pino ───────────────────────────────────────────────────

class TestAfLayer:
    def test_device_map_wins_over_table(self, tmp_path, monkeypatch, chip) -> None:
        _, pal = chip
        (tmp_path / "stm32h753").mkdir()
        (tmp_path / "stm32h753" / "af.json").write_text(json.dumps(
            {"pins": {"PE7": {"UART7_RX": 7}, "PB14": {"TIM12_CH1": 2}}}), encoding="utf-8")
        monkeypatch.setattr(afmap, "DEVICES_DIR", tmp_path)
        afmap.load.cache_clear()
        try:
            assert pin_af(pal, Signal("rx", "GPIOE", 7, role="RX", periph_name="UART7")) == 7
            assert pin_af(pal, Signal("s", "GPIOB", 14, role="CH1", periph_name="TIM12")) == 2
            # fora do mapa: tabela por família; AF do Pinout vence tudo
            assert pin_af(pal, Signal("tx", "GPIOC", 12, role="TX", periph_name="UART5")) == 8
            assert pin_af(pal, Signal("rx", "GPIOE", 7, role="RX", periph_name="UART7",
                                      af=3)) == 3
        finally:
            afmap.load.cache_clear()

    def test_table_fallback_depends_on_port(self, tmp_path, monkeypatch, chip) -> None:
        _, pal = chip
        monkeypatch.setattr(afmap, "DEVICES_DIR", tmp_path)       # sem af.json
        afmap.load.cache_clear()
        try:
            assert pin_af(pal, Signal("rx", "GPIOE", 7, role="RX", periph_name="UART7")) == 7
            assert pin_af(pal, Signal("rx", "GPIOA", 8, role="RX", periph_name="UART7")) == 11
        finally:
            afmap.load.cache_clear()

    def test_generator_reads_cubemx_modes(self, tmp_path) -> None:
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        from gerar_af import extract
        xml = tmp_path / "GPIO-X_Modes.xml"
        xml.write_text(
            '<IP xmlns="http://dummy.com"><GPIO_Pin PortName="PE" Name="PE7">'
            '<PinSignal Name="UART7_RX"><SpecificParameter Name="GPIO_AF">'
            '<PossibleValue>GPIO_AF7_UART7</PossibleValue></SpecificParameter></PinSignal>'
            '</GPIO_Pin></IP>', encoding="utf-8")
        assert extract(xml) == {"PE7": {"UART7_RX": 7}}


# ── Subcamada: clock do projeto (.ioc) ───────────────────────────────────────

class TestIocClocksAndEth:
    def test_clocks_and_eth_imported(self) -> None:
        ioc = parse_ioc("Mcu.UserName=STM32H753ZITx\nRCC.HSE_VALUE=25000000\n"
                        "RCC.SYSCLKFreq_VALUE=400000000\nRCC.SYSCLKSource=RCC_SYSCLKSOURCE_PLLCLK\n"
                        "RCC.Tim1OutputFreq_Value=200000000\nPA2.Signal=ETH_MDIO\n"
                        "PC1.Signal=ETH_MDC\n")
        assert ioc.clocks == {"HSE": 25e6, "SYSCLK": 400e6, "TIM_APB1": 200e6, "fonte": "PLL1"}
        assert {p.peripheral.role for p in ioc.pins.values()} == {"MDIO", "MDC"}
        assert all(p.peripheral.periph_type == "ETH" for p in ioc.pins.values())

    def test_pll_and_oscillators_imported(self) -> None:
        ioc = parse_ioc("Mcu.UserName=STM32H753ZITx\nRCC.DIVM1=5\nRCC.DIVN1=160\n"
                        "RCC.DIVP1=2\nRCC.DIVQ1=8\nRCC.DIVR1=2\nRCC.HPRE=RCC_HCLK_DIV2\n"
                        "RCC.PLLSourceVirtual=RCC_PLLSOURCE_HSE\n"
                        "PH0-OSC_IN\\ (PH0).Mode=HSE-External-Clock-Source\n"
                        "PC14-OSC32_IN\\ (OSC32_IN).Mode=LSE-External-Oscillator\n")
        c = ioc.clocks
        assert c["PLL1"] == {"m": 5, "n": 160, "p": 2, "q": 8, "r": 2}
        assert c["PLL_SRC"] == "HSE" and c["VOS"] == 1
        assert c["DIV"]["HPRE"] == 2 and c["DIV"]["D1CPRE"] == 1
        assert c["HSE_BYPASS"] is True and c["LSE_BYPASS"] is False and c["LSE"] == 32768

    def test_project_round_trip(self) -> None:
        p = ProjectConfig("P", "P", "b", clocks={"SYSCLK": 1.0})
        assert ProjectConfig.from_dict(p.to_dict()).clocks == {"SYSCLK": 1.0}
        assert "clocks" not in ProjectConfig("P", "P", "b").to_dict()


# ── Clock ─────────────────────────────────────────────────────────────────────

class TestClock:
    def test_tree_from_rcc(self, chip) -> None:
        _, pal = chip
        t = clock_tree(pal, 25e6)
        assert (t.source, t.pll_src) == ("PLL1", "HSE")
        assert t.values()["SYSCLK"] == pytest.approx(400e6)
        assert (t.cpu, t.hclk) == (pytest.approx(400e6), pytest.approx(200e6))
        assert t.apb == {k: pytest.approx(100e6) for k in ("APB1", "APB2", "APB3", "APB4")}
        assert t.timers == {"APB1": pytest.approx(200e6), "APB2": pytest.approx(200e6)}
        assert t.plls["PLL1"]["q"] == pytest.approx(100e6)

    LER = {"modo": "ler como está (com firmware)"}
    REF = "TESTES_PLATAFORMA/BLOCOS/clock.py:AnaliseClock"

    def test_read_mode_uses_project_clocks(self, chip, project) -> None:
        _, pal = chip
        r = _run(self.REF, self.LER, pal)
        assert r.status == TestStatus.PASS, r.message
        assert "fonte PLL1 ← HSE" in r.message and "CPU medida" in r.message
        medida = next(m for m in r.measurements if m.name == "clk_cpu_medido_hz")
        assert medida.value == pytest.approx(F_CPU, rel=1e-3)
        nomes = {m.name for m in r.measurements}
        assert {"clk_sysclk_hz", "clk_apb4_hz", "clk_tim_apb2_hz", "clk_cpu_medido_hz"} <= nomes

    def test_read_mode_detects_wrong_crystal_param(self, chip, project) -> None:
        _, pal = chip
        r = _run(self.REF, {**self.LER, "hse_mhz": 8.0, "medir_cpu": False}, pal)
        assert r.status == TestStatus.FAIL and "SYSCLK=128 MHz" in r.message

    # ── sem firmware: o testador monta o clock ────────────────────────────

    def test_configure_from_reset_and_restore(self, blank, project, board) -> None:
        s, pal = blank
        r = _run(self.REF, {"janela_s": 0.1}, pal)
        assert r.status == TestStatus.PASS, r.message
        med = {m.name: m for m in r.measurements}
        assert med["clk_hse_medido_hz"].value == pytest.approx(25e6, rel=2e-3)
        assert med["clk_cpu_medido_hz"].value == pytest.approx(400e6, rel=2e-3)
        assert {"clk_hse_partida_ms", "clk_lse_partida_ms", "clk_sysclk_hz"} <= set(med)
        assert "HSE partiu em" in r.message and "LSE partiu em" in r.message
        # voltou ao reset: HSI, PLL e HSE desligados, LSE desligado, núcleo parado
        assert pal.read_field("RCC", "CFGR", "SWS") == 0
        assert not pal.read_field("RCC", "CR", "PLL1ON")
        assert not pal.read_field("RCC", "CR", "HSEON")
        assert not pal.read_field("RCC", "BDCR", "LSEON") and s.halted

    def test_dead_crystal(self, blank, project, board) -> None:
        s, pal = blank
        s.hse_dead = True
        r = _run(self.REF, {"janela_s": 0.05, "lse": "não"}, pal)
        assert r.status == TestStatus.FAIL
        assert "HSE não ficou pronto" in r.message and "OSC_IN/OSC_OUT" in r.message

    def test_wrong_crystal_value(self, blank, project, board) -> None:
        s, pal = blank
        s.hse_real = 8e6                                # montaram cristal de 8 MHz
        r = _run(self.REF, {"janela_s": 0.1, "lse": "não"}, pal)
        assert r.status == TestStatus.FAIL
        assert "(esperado 25 MHz" in r.message
        hse = next(m for m in r.measurements if m.name == "clk_hse_medido_hz")
        assert hse.value == pytest.approx(8e6, rel=0.01) and hse.within_limits is False

    def test_configure_needs_pll_from_ioc(self, blank, project, board) -> None:
        _, pal = blank
        project.clocks = {"HSE": 25e6}
        r = _run(self.REF, {}, pal)
        assert r.status == TestStatus.FAIL and "importe o .ioc" in r.message

    def test_block_without_hse_fails_clearly(self, chip, project) -> None:
        _, pal = chip
        project.clocks = {}
        r = _run(self.REF, {}, pal)
        assert r.status == TestStatus.FAIL and "HSE desconhecido" in r.message


# ── PWM ───────────────────────────────────────────────────────────────────────

class TestPwm:
    def test_channel_generate_read_restore(self, chip) -> None:
        _, pal = chip
        before = pal.read_reg("TIM2", "ARR")
        with PwmChannel(pal, "TIM2", 3, 200e6) as ch:
            st = ch.generate(50, 1.5e-3)
            assert st.freq_hz == pytest.approx(50, rel=1e-3)
            assert st.pulse_s == pytest.approx(1.5e-3, abs=1e-6)
            assert st.enabled and st.pwm_mode
        assert pal.read_reg("TIM2", "ARR") == before

    def test_gerar_block(self, chip, project) -> None:
        s, pal = chip
        s.toggling |= {("GPIOB", 10), ("GPIOB", 14)}
        r = _run("TESTES_PLATAFORMA/BLOCOS/pwm.py:PwmServoGerar",
                 {"pinos": ["servo1", "servo3"], "espera_ms": 0}, pal)
        assert r.status == TestStatus.PASS, r.message
        assert {"pwm_pulso_erro_us_servo1", "pwm_pino_parado_servo3"} <= \
            {m.name for m in r.measurements}

    def test_firmware_block_flags_idle_timer(self, chip, project) -> None:
        _, pal = chip
        r = _run("TESTES_PLATAFORMA/BLOCOS/pwm.py:PwmFirmware",
                 {"pinos": ["servo1"], "verificar_pino": False}, pal)
        assert r.status == TestStatus.FAIL and "servo1: inativo" in r.message


# ── RS485 ─────────────────────────────────────────────────────────────────────

class TestRs485:
    REF = "TESTES_PLATAFORMA/BLOCOS/comunicacao.py:Rs485Eco"

    def test_de_without_echo(self, chip, project) -> None:
        _, pal = chip
        r = _run(self.REF, {"periferico": "UART7", "bytes": 4}, pal)
        assert r.status == TestStatus.PASS, r.message
        assert r.message.startswith("UART7 @ 1200 baud, 4 bytes")

    def test_echo_and_de(self, chip, project) -> None:
        s, pal = chip
        s.echo = True
        r = _run(self.REF, {"periferico": "UART7", "bytes": 4,
                            "modo": "eco no barramento (receptor ativo ou jumper)"}, pal)
        assert r.status == TestStatus.PASS and "4/4 iguais" in r.message

    def test_echo_missing_fails(self, chip, project) -> None:
        _, pal = chip
        r = _run(self.REF, {"periferico": "UART7", "bytes": 2, "verificar_de": False,
                            "modo": "eco no barramento (receptor ativo ou jumper)"}, pal)
        assert r.status == TestStatus.FAIL and "recebido nada" in r.message

    def test_requires_de_pin(self, chip, project) -> None:
        _, pal = chip
        r = _run(self.REF, {"periferico": "UART5"}, pal)
        assert r.status == TestStatus.FAIL and "sem pino DE" in r.message
