"""Blocos de comunicação — UART, RS485, SPI, I2C, CAN e Ethernet.

O periférico (ex.: USART3, SPI1) é escolhido no Plano de testes entre os do
Pinout do projeto; os pinos são achados pela função (TX/RX, SCK/MISO/MOSI,
SCL/SDA, MDC/MDIO). Registradores e pinos são restaurados no fim de cada bloco.
"""

import random

from core.analysis import MeasurementSet, analyze_ber
from core.analysis.metrics import Measurement
from hal.common import pin_af, restore_pin, set_af, snapshot_pin
from testbench import ComposedTest, Step, Stimulus, Testbench
from testbench.decision import Expect, MatchesDrive
from testbench.gpio import GpioInputMonitor
from testbench.uart import UartLink, UartRxMonitor, UartTxDriver
from tests_builtin.base import BuiltinTest, TestResult
from tests_builtin.params import Bool, Choice, Float, Int, Periph, Text

PADROES = ("contador", "aleatório", "0x55 / 0xAA", "0x00 / 0xFF")


def _padrao(nome: str, n: int, bits: int = 8) -> list[int]:
    mask = (1 << bits) - 1
    if nome == "aleatório":
        rnd = random.Random(1234)                # reprodutível
        return [rnd.getrandbits(bits) for _ in range(n)]
    if nome == "0x55 / 0xAA":
        return [(0x55555555 if i % 2 == 0 else 0xAAAAAAAA) & mask for i in range(n)]
    if nome == "0x00 / 0xFF":
        return [0 if i % 2 == 0 else mask for i in range(n)]
    return [(i * 0x01010101 + i) & mask for i in range(n)]


def _to_bytes(words: list[int], bits: int) -> bytes:
    return b"".join(w.to_bytes(bits // 8, "little") for w in words)


class _PinosAf:
    """Coloca os pinos do periférico em AF e restaura no fim (context manager)."""

    def __init__(self, pal, periph, roles, open_drain=False, pull="nenhum") -> None:
        self.pal, self.periph = pal, periph
        self.sigs = [periph.pin(r) for r in roles]
        self.open_drain, self.pull = open_drain, pull
        self.snaps = []

    def __enter__(self):
        for s in self.sigs:
            self.snaps.append(snapshot_pin(self.pal, s.port, s.pin))
            set_af(self.pal, s.port, s.pin, pin_af(self.pal, s, self.periph.name),
                   open_drain=self.open_drain, pull=self.pull)
        return self

    def __exit__(self, *_exc) -> None:
        for snap in reversed(self.snaps):
            restore_pin(self.pal, snap)


# ── UART ──────────────────────────────────────────────────────────────────────

class UartLoopback(BuiltinTest):
    name        = "UART — Loopback"
    category    = "UART"
    description = ("Envia N bytes e compara o eco: half-duplex interno (só o pino TX, sem fio) "
                   "ou fio TX→RX. BER no relatório (métrica uart_ber_<baud>).")
    params = {
        "periferico": Periph("Periférico", ("UART",)),
        "modo":  Choice("Loopback", ("half-duplex interno (só TX)", "fio externo TX→RX")),
        "baud":  Int("Baud rate", 115200, minimum=300, maximum=12_000_000),
        "bytes": Int("Bytes", 64, minimum=1, maximum=4096),
        "padrao": Choice("Padrão", PADROES),
    }

    def _run(self, pal) -> TestResult:
        from hal.uart import Uart

        half = self.p.modo.startswith("half")
        roles = ("TX",) if half else ("TX", "RX")
        enviado = _padrao(self.p.padrao, self.p.bytes)
        recebido: list[int | None] = []          # None = não chegou (timeout)
        with _PinosAf(pal, self.p.periferico, roles), Uart(pal, self.p.periferico.name) as u:
            real = u.setup(self.p.baud, half_duplex=half)
            perdidos_seguidos = 0
            for b in enviado:
                u.write(b)
                try:
                    recebido.append(u.read())
                    perdidos_seguidos = 0
                except TimeoutError:
                    recebido.append(None)
                    perdidos_seguidos += 1
                    if perdidos_seguidos >= 8:   # linha muda: não espera os restantes
                        break
            erros = dict(u.errors)
        recebido += [None] * (len(enviado) - len(recebido))
        # byte perdido conta como 8 bits errados (complemento do enviado)
        comparado = bytes(r if r is not None else b ^ 0xFF for b, r in zip(enviado, recebido,
                                                                          strict=True))
        ok = sum(1 for b, r in zip(enviado, recebido, strict=True) if r == b)
        divergentes = [(i, b, r) for i, (b, r) in enumerate(zip(enviado, recebido, strict=True))
                       if r != b]
        self.audit["passos"] = [
            [str(i), f"byte {i}", "", f"0x{b:02X}", "nada" if r is None else f"0x{r:02X}"]
            for i, (b, r) in enumerate(zip(enviado, recebido, strict=True))][:300]
        ms = MeasurementSet()
        ms.add(analyze_ber(f"uart_ber_{self.p.baud}", bytes(enviado), comparado,
                           limit_max=0.0))
        ber = ms.get(f"uart_ber_{self.p.baud}")
        msg = (f"{self.p.periferico.name} @ {real:.0f} baud: {ok}/{len(enviado)} bytes iguais, "
               f"BER {ber.value:.2e}" + (f", erros {erros}" if any(erros.values()) else ""))
        if divergentes:
            amostra = ", ".join(f"#{i}: 0x{b:02X}→" + ("nada" if r is None else f"0x{r:02X}")
                                for i, b, r in divergentes[:5])
            msg += f"; divergentes: {amostra}" + (" ..." if len(divergentes) > 5 else "")
        if ms.all_within_limits() and not divergentes:
            return self._pass(msg, measured=ber.value, measurements=ms)
        return self._fail(msg, measured=ber.value, measurements=ms)


# ── SPI ───────────────────────────────────────────────────────────────────────

class SpiLoopback(BuiltinTest):
    name        = "SPI — Loopback MOSI→MISO"
    category    = "SPI"
    description = "Mestre envia palavras e compara o que volta em MISO (jumper MOSI→MISO)."
    params = {
        "periferico": Periph("Periférico", ("SPI",)),
        "palavras":   Int("Palavras", 16, minimum=1, maximum=1024),
        "divisor":    Choice("Divisor de clock", ("/256", "/128", "/64", "/32", "/16", "/8",
                                                  "/4", "/2")),
        "modo":       Choice("Modo SPI (CPOL/CPHA)", ("0", "1", "2", "3")),
        "padrao":     Choice("Padrão", PADROES),
        "ligacao":    Choice("Ligação", ("jumper MOSI→MISO", "só TX (sem MISO)"),
                             help="Só TX: confere que o mestre gera clock e esvazia a FIFO "
                                  "(periféricos TX-only, ex.: SPI4/SPI5)"),
    }

    def _run(self, pal) -> TestResult:
        from hal.spi import Spi

        div_log2 = int(self.p.divisor[1:]).bit_length() - 2
        so_tx = self.p.ligacao.startswith("só TX")
        roles = ("SCK", "MOSI") if so_tx else ("SCK", "MISO", "MOSI")
        with _PinosAf(pal, self.p.periferico, roles), \
                Spi(pal, self.p.periferico.name) as spi:
            spi.setup(div_log2, int(self.p.modo))
            enviado = _padrao(self.p.padrao, self.p.palavras, spi.bits)
            recebido = []
            for w in enviado:
                try:
                    recebido.append(spi.transfer(w))
                except TimeoutError:
                    break
            bits = spi.bits
        ms = MeasurementSet()
        if so_tx:
            perdidas = len(enviado) - len(recebido)
            ms.add(Measurement("spi_tx_palavras_perdidas", float(perdidas), "palavras",
                               limit_max=0.0, description="palavras que não saíram (TX-only)"))
            msg = (f"{self.p.periferico.name} {self.p.divisor} modo {self.p.modo} (só TX): "
                   f"{len(recebido)}/{len(enviado)} palavras de {bits} bits transmitidas")
            if ms.all_within_limits():
                return self._pass(msg, measured=len(recebido), measurements=ms)
            return self._fail(msg + " — clock não anda (SCK em AF? periférico com clock?)",
                              measured=len(recebido), measurements=ms)
        ms.add(analyze_ber("spi_ber", _to_bytes(enviado, bits), _to_bytes(recebido, bits),
                           limit_max=0.0))
        ber = ms.get("spi_ber")
        msg = (f"{self.p.periferico.name} {self.p.divisor} modo {self.p.modo}: "
               f"{len(recebido)}/{len(enviado)} palavras de {bits} bits, BER {ber.value:.2e}")
        if ms.all_within_limits() and len(recebido) == len(enviado):
            return self._pass(msg, measured=ber.value, measurements=ms)
        if all(w == recebido[0] for w in recebido) and recebido:
            msg += f" — MISO fixo em 0x{recebido[0]:X} (jumper MOSI→MISO ligado?)"
        return self._fail(msg, measured=ber.value, measurements=ms)


# ── I2C ───────────────────────────────────────────────────────────────────────

class I2cVarredura(BuiltinTest):
    name        = "I2C — Varredura do barramento"
    category    = "I2C"
    description = ("Procura dispositivos (ACK) de 0x08 a 0x77 e confere os endereços esperados. "
                   "Detecta também barramento preso (SCL/SDA em 0).")
    params = {
        "periferico": Periph("Periférico", ("I2C",)),
        "esperados":  Text("Endereços esperados", "", "ex.: 0x50, 0x68 (vazio = só listar)"),
        "pull_interno": Bool("Pull-up interno", True,
                             help="Desmarque se a placa já tem resistores de pull-up"),
    }

    def _run(self, pal) -> TestResult:
        from hal.i2c import I2c

        try:
            esperados = sorted({int(x, 16) for x in self.p.esperados.replace(";", ",").split(",")
                                if x.strip()})
        except ValueError:
            return self._fail(f"Endereços esperados inválidos: '{self.p.esperados}'")
        pull = "pull-up" if self.p.pull_interno else "nenhum"
        with _PinosAf(pal, self.p.periferico, ("SCL", "SDA"), open_drain=True, pull=pull), \
                I2c(pal, self.p.periferico.name) as bus:
            bus.setup()
            if bus.bus_busy():
                return self._fail(f"{self.p.periferico.name}: barramento ocupado antes do teste "
                                  "(SDA/SCL presos em 0? falta pull-up?)")
            achados = bus.scan()
        lista = ", ".join(f"0x{a:02X}" for a in achados) or "nenhum"
        faltando = [a for a in esperados if a not in achados]
        if faltando:
            return self._fail(f"faltando: {', '.join(f'0x{a:02X}' for a in faltando)} | "
                              f"responderam: {lista}", measured=achados, expected=esperados)
        return self._pass(f"{self.p.periferico.name}: responderam {lista}",
                          measured=achados, expected=esperados or None)


# ── CAN ───────────────────────────────────────────────────────────────────────

class CanLoopback(BuiltinTest):
    name        = "CAN — Loopback interno"
    category    = "CAN"
    description = ("Transmite quadros e os recebe de volta dentro do controlador (sem "
                   "transceptor). Valida clock, bit timing, filtros/RAM e o caminho TX→RX.")
    params = {
        "periferico": Periph("Periférico", ("CAN",)),
        "bitrate":    Choice("Bit rate", ("500000", "250000", "125000", "1000000")),
        "quadros":    Int("Quadros", 8, minimum=1, maximum=64),
        "hse_mhz":    Float("HSE / cristal (MHz, FDCAN)", 0.0, maximum=60.0,
                            help="0 = do projeto (.ioc); o FDCAN do H7 usa o HSE como clock"),
    }

    def _run(self, pal) -> TestResult:
        from hal.can import CanInUseError, Frame, can_for

        try:
            from testbench.clock import expected_hz, project_clocks
            drv = can_for(pal, self.p.periferico.name, hse_hz=expected_hz(self.p.hse_mhz, "HSE"),
                          hse_bypass=bool(project_clocks().get("HSE_BYPASS")))
        except LookupError as exc:
            return self._skip(str(exc))
        try:
            real = drv.setup(int(self.p.bitrate))
        except CanInUseError as exc:
            drv.restore()
            return self._skip(str(exc))
        except RuntimeError as exc:
            drv.restore()
            return self._skip(str(exc))
        falhas = []
        try:
            for i in range(self.p.quadros):
                tx = Frame(0x100 + i, bytes((i + k) & 0xFF for k in range(8)))
                rx = drv.send_receive(tx)
                if rx != tx:
                    falhas.append(f"#{i}: enviado {tx.std_id:#x}/{tx.data.hex()} "
                                  f"recebido {rx.std_id:#x}/{rx.data.hex()}")
            tec, rec = drv.error_counters()
        finally:
            drv.restore()
        msg = (f"{self.p.periferico.name} @ {real / 1000:.0f} kbit/s: "
               f"{self.p.quadros - len(falhas)}/{self.p.quadros} quadros iguais, "
               f"TEC={tec} REC={rec}")
        if falhas or tec or rec:
            return self._fail(msg + (" | " + "; ".join(falhas[:3]) if falhas else ""))
        return self._pass(msg)


# ── Ethernet ──────────────────────────────────────────────────────────────────

class EthernetPhy(BuiltinTest):
    name        = "Ethernet — PHY por MDIO"
    category    = "Ethernet"
    description = ("Lê o identificador do PHY e o estado do link pelo MDIO. Valida MAC, pinos "
                   "MDC/MDIO, alimentação/endereço do PHY e, opcionalmente, o cabo (link).")
    params = {
        "periferico": Periph("Interface", ("ETH",)),
        "endereco":   Int("Endereço do PHY", 0, minimum=0, maximum=31),
        "exigir_link": Bool("Exigir link ativo (cabo ligado)", False),
        "varrer":     Bool("Procurar o endereço (0 a 31)", False,
                           help="Usa o primeiro PHY que responder, ignorando 'Endereço'"),
    }

    def _run(self, pal) -> TestResult:
        from hal.eth import EthMdio

        # MII tem RX_CLK/TX_CLK no Pinout; RMII tem REF_CLK/CRS_DV (ou só MDC/MDIO)
        per = self.p.periferico
        try:
            mdio = EthMdio(pal, rmii=not (per.has("RX_CLK") or per.has("TX_CLK")))
        except LookupError as exc:
            return self._skip(str(exc))
        with _PinosAf(pal, self.p.periferico, ("MDC", "MDIO")):
            mdio.setup()
            try:
                enderecos = range(32) if self.p.varrer else (self.p.endereco,)
                for endereco in enderecos:
                    info = mdio.identify(endereco)
                    if info["id1"] not in (0x0000, 0xFFFF):
                        break
            finally:
                mdio.restore()
        ident = f"ID {info['id1']:04X}:{info['id2']:04X} (OUI {info['oui']:06X}, modelo " \
                f"{info['model']}, rev {info['rev']})"
        if info["id1"] in (0x0000, 0xFFFF):
            onde = "em nenhum endereço (0 a 31)" if self.p.varrer else \
                f"no endereço {self.p.endereco}"
            return self._fail(f"PHY não respondeu {onde}: {ident}")
        ident = f"endereço {endereco}, {ident}"
        link = "link ATIVO" if info["link"] else "sem link"
        if self.p.exigir_link and not info["link"]:
            return self._fail(f"{ident}, {link}")
        return self._pass(f"{ident}, {link}")


# ── RS485 ─────────────────────────────────────────────────────────────────────

class _Bytes(Stimulus):
    """Um byte por passo e, no fim, um passo de repouso (barramento livre, DE em 0)."""

    def __init__(self, driver: str, data: list[int], repouso_s: float) -> None:
        self.driver, self.data, self.repouso_s = driver, data, repouso_s

    def steps(self):
        for i, b in enumerate(self.data):
            yield Step({self.driver: b}, 0.0, f"byte {i}")
        yield Step({}, self.repouso_s, "repouso")


class Rs485Eco(ComposedTest):
    """UART com DE por hardware: driver de TX + monitores de DE e de RX (eco)."""

    name        = "RS485 — DE e eco"
    category    = "UART"
    description = ("UART com Driver Enable por hardware: confere o pino DE ativo durante a "
                   "transmissão e em repouso no fim; com eco (receptor sempre ativo ou jumper "
                   "Y→A/Z→B no full-duplex), compara os bytes recebidos.")
    params = {
        "periferico": Periph("Periférico (com pino DE no Pinout)", ("UART",)),
        "modo":   Choice("Eco", ("sem eco (só TX + DE)",
                                 "eco no barramento (receptor ativo ou jumper)")),
        "baud":   Int("Baud rate", 1200, minimum=300, maximum=12_000_000),
        "bytes":  Int("Bytes", 16, minimum=1, maximum=1024),
        "padrao": Choice("Padrão", PADROES),
        "verificar_de": Bool("Conferir o pino DE", True,
                             help="Lido pelo SWD logo após cada byte: confiável até ~2400 baud"),
        "de_ativo_baixo": Bool("DE ativo em nível baixo", False),
    }

    def _run(self, pal) -> TestResult:
        if not self.p.periferico.has("DE"):
            return self._fail(f"{self.p.periferico.name}: sem pino DE no Pinout "
                              "(sinal UARTx_DE do CubeMX)")
        return super()._run(pal)

    def build(self) -> Testbench:
        p = self.p
        eco = p.modo.startswith("eco")
        self.link = UartLink(p.periferico, p.baud, rx=eco, de=True,
                             de_active_low=p.de_ativo_baixo)
        tx = UartTxDriver(self.link)
        monitors, decisions = [], []
        if p.verificar_de:
            de = GpioInputMonitor(p.periferico.pin("DE"), configure=False, raw=True, name="de")
            ativo = 0 if p.de_ativo_baixo else 1
            monitors.append(de)
            decisions.append(Expect("de", lambda o: ativo ^ (o.label == "repouso"),
                                    metric="rs485_de_divergente", label=p.periferico.name,
                                    describe=lambda v: f"DE={v}"))
        if eco:
            rx = UartRxMonitor(self.link)
            monitors.append(rx)
            decisions.append(MatchesDrive(rx.name, tx.name, metric="rs485_eco_divergente",
                                          label=p.periferico.name, describe=_hex))
        repouso = 3 * self.link.byte_s + 0.005
        return Testbench([tx], monitors, _Bytes(tx.name, _padrao(p.padrao, p.bytes), repouso),
                         decisions)

    def summary(self, trace, verdicts) -> str:
        base = f"{self.p.periferico.name} @ {self.link.real_baud:.0f} baud, {self.p.bytes} bytes"
        erros = {k: v for k, v in self.link.errors.items() if v}
        return "; ".join([base] + [v.message for v in verdicts] +
                         ([f"erros {erros}"] if erros else []))


def _hex(v) -> str:
    return "nada" if v is None else f"0x{v:02X}"
