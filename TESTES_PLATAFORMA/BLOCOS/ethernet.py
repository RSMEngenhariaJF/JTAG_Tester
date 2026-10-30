"""Bloco de Ethernet — taxa, tamanhos de quadro e taxa de erro (tráfego real pelo DMA).

Bancada modular (src/testbench):

    estímulo  um passo por tamanho de quadro (ex.: 64, 128, ..., 1518 B)
    driver    EthTrafficDriver   — pinos do Pinout, PHY pelo MDIO (loopback),
                                   MAC/DMA transmitindo N quadros por lote
    monitor   EthTrafficMonitor  — enviados, recebidos, erros (CRC, conteúdo,
                                   perdidos) e a taxa medida pelo PTP
    decisão   _Trafego           — taxa de quadros com erro ≤ limite e ocupação
                                   do fio ≥ limite, por tamanho

Modos:
  * loopback no PHY — o quadro sai do MAC, passa pelas trilhas RMII (TXD0/1,
    TX_EN), entra no PHY e volta (RXD0/1, CRS_DV) com o REF_CLK do PHY. Valida
    trilhas, PHY e MAC/DMA. O PHY não transmite no cabo durante o loopback.
  * loopback no MAC — só MAC + DMA (sem trilhas); separa defeito interno de
    defeito de placa.

A taxa vem das marcas de tempo PTP do 1º e do último quadro (hardware), não do
SWD; o relógio PTP deriva do HCLK, então a exatidão é a da fonte de clock
(HSI ~1 %; cristal/PLL ~ppm). Sem erros, a taxa de erro de bit fica abaixo de
3/(bits enviados) com 95 % de confiança (regra de 3).
"""

from core.analysis.metrics import Measurement
from testbench import ComposedTest, Decision, Step, Stimulus, Testbench, Trace, Verdict
from testbench.clock import expected_hz
from testbench.eth import MODO_MAC, MODO_PHY, EthTrafficDriver, EthTrafficMonitor
from tests_builtin.params import Bool, Choice, Float, Int, Periph, Text

# AXI SRAM do H7 (512 KB): os primeiros 32 KB ficam para laços/pilha de outros testes
_RAM_OFFSET, _RAM_SIZE = 0x8000, 0x70000
MODOS = {"loopback no PHY (trilhas RMII + PHY)": MODO_PHY,
         "loopback no MAC (MAC + DMA)": MODO_MAC}


def _label(size: int) -> str:
    return f"{size} B"


class _Tamanhos(Stimulus):
    def __init__(self, driver: str, sizes: list[int]) -> None:
        self.driver, self.sizes = driver, sizes

    def steps(self):
        for size in self.sizes:
            yield Step({self.driver: size}, 0.0, _label(size))


class _Trafego(Decision):
    """Por tamanho: quadros com erro (FER) e ocupação do fio."""

    def __init__(self, monitor: str, size: int, fer_max: float, util_min: float) -> None:
        self.monitor, self.size, self.fer_max, self.util_min = monitor, size, fer_max, util_min
        self.name = f"trafego_{size}"

    def evaluate(self, trace: Trace) -> Verdict:
        obs = [o.observed.get(self.monitor) for o in trace.observations
               if o.label == _label(self.size)]
        s = obs[-1] if obs else None
        if not s:
            return Verdict(False, f"{_label(self.size)}: nenhuma amostra")
        tag = f"{self.size}B"
        bound = 3 / s["bits"] if s["bits"] else None
        ms = [Measurement(f"eth_fer_{tag}", s["fer"], "", limit_max=self.fer_max,
                          description=f"{s['erros']} de {s['enviados']} quadros com erro "
                                      f"(CRC {s['erros_crc']}, conteúdo {s['erros_dados']}, "
                                      f"perdidos {s['perdidos']})")]
        if bound and s["erros"] == 0:
            ms.append(Measurement(f"eth_ber_max_{tag}", bound, "",
                                  description="limite superior da taxa de erro de bit "
                                              "(95 %, nenhum erro em "
                                              f"{s['bits']:.3g} bits)"))
        if s["mbps_fio"] is not None:
            ms.append(Measurement(f"eth_ocupacao_pct_{tag}", s["utilizacao_pct"], "%",
                                  limit_min=self.util_min, nominal=100.0,
                                  description="ocupação do fio (quadro + preâmbulo + IFG) "
                                              "medida pelo PTP"))
            ms.append(Measurement(f"eth_taxa_mbps_{tag}", s["mbps_dados"], "Mbit/s",
                                  description=f"{s['quadros_s']:.0f} quadros/s "
                                              f"(teórico {s['teorico_quadros_s']:.0f})"))
        ok = all(m.within_limits is not False for m in ms) and s["enviados"] > 0
        taxa = f", {s['mbps_fio']:.2f} Mbit/s no fio" if s["mbps_fio"] else ", taxa sem PTP"
        msg = (f"{_label(self.size)}: {s['recebidos']}/{s['enviados']} ok, "
               f"{s['erros']} erro(s){taxa}")
        if s["notas"]:
            msg += f" ({'; '.join(s['notas'])})"
        return Verdict(ok, msg, ms)


class EthernetTrafego(ComposedTest):
    name        = "Ethernet — Taxa, tamanhos de quadro e erros"
    category    = "Ethernet"
    description = ("Transmite lotes de quadros pelo DMA do MAC, em loopback no PHY ou no "
                   "MAC, para cada tamanho; mede a taxa pelo PTP e conta quadros com erro "
                   "(CRC, conteúdo, perdidos).")
    params = {
        "periferico": Periph("Interface", ("ETH",)),
        "modo":       Choice("Loopback", tuple(MODOS)),
        "velocidade": Choice("Velocidade", ("100 Mbit/s", "10 Mbit/s")),
        "tamanhos":   Text("Tamanhos de quadro (bytes)", "64, 128, 256, 512, 1024, 1518",
                           "entre 64 e 1518, separados por vírgula"),
        "quadros":    Int("Quadros por lote", 128, minimum=2, maximum=256),
        "lotes":      Int("Lotes por tamanho", 1, minimum=1, maximum=100,
                          help="Mais lotes = mais quadros para a estatística de erro"),
        "verificar_dados": Bool("Comparar o conteúdo byte a byte", True),
        "fer_max":    Float("Taxa máxima de quadros com erro", 0.0, minimum=0.0, maximum=1.0),
        "ocupacao_min": Float("Ocupação mínima do fio (%)", 95.0, minimum=0.0, maximum=100.0),
        "varrer":     Bool("Procurar o PHY (0 a 31)", True),
        "endereco":   Int("Endereço do PHY", 0, minimum=0, maximum=31),
    }

    def _tamanhos(self) -> list[int]:
        return [int(x) for x in self.p.tamanhos.replace(";", ",").split(",") if x.strip()]

    def _run(self, pal):
        try:
            sizes = self._tamanhos()
        except ValueError:
            return self._fail(f"Tamanhos inválidos: '{self.p.tamanhos}'")
        fora = [s for s in sizes if not 64 <= s <= 1518]
        if not sizes or fora:
            return self._fail("Tamanhos de quadro devem ficar entre 64 e 1518 bytes"
                              + (f" (fora: {fora})" if fora else ""))
        return super()._run(pal)

    def build(self) -> Testbench:
        from core.board.config import get_active_board

        p = self.p
        board = get_active_board()
        self.drv = EthTrafficDriver(
            p.periferico, mode=MODOS[p.modo], speed100=p.velocidade.startswith("100"),
            phy_addr=None if p.varrer else p.endereco, frames=p.quadros, batches=p.lotes,
            check_data=p.verificar_dados, hse_hz=expected_hz(0, "HSE") or 25e6,
            ram_base=board.sram_base + _RAM_OFFSET, ram_size=_RAM_SIZE)
        mon = EthTrafficMonitor(self.drv)
        sizes = self._tamanhos()
        return Testbench([self.drv], [mon], _Tamanhos(self.drv.name, sizes),
                         [_Trafego(mon.name, s, p.fer_max, p.ocupacao_min) for s in sizes])

    def summary(self, trace, verdicts) -> str:
        d = self.drv
        info = d.phy_info
        cab = (f"PHY {info.get('id1', 0):04X}:{info.get('id2', 0):04X} no endereço "
               f"{d.phy_addr}, {self.p.modo.split(' (')[0]}, {self.p.velocidade}, "
               f"PTP no HCLK ({d.clock_source})") if info else ""
        falhas = [v.message for v in verdicts if v.ok is False]
        corpo = "; ".join(v.message for v in verdicts)
        return ("FALHAS: " + "; ".join(falhas) + " | " if falhas else "") + \
            (f"{cab} | " if cab else "") + corpo
