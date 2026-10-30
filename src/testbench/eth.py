"""Driver e monitor de tráfego Ethernet (MAC + DMA do H7, hal.eth_dma).

O driver prepara pinos RMII/MII (do Pinout), PHY (MDIO, loopback opcional) e o
DMA; cada valor aplicado é um tamanho de quadro, transmitido em lotes. O
monitor resume o último tamanho: enviados, recebidos, erros e taxa (PTP).
"""

from __future__ import annotations

import time

from hal.clock import clock_tree
from hal.common import pin_af, restore_pin, set_af, snapshot_pin
from hal.eth import EthMdio
from hal.eth_dma import PREAMBLE_IFG, BatchResult, EthTraffic
from testbench.core import Driver, Monitor

BMCR_LOOPBACK, BMCR_SPEED100, BMCR_AN, BMCR_FD = 1 << 14, 1 << 13, 1 << 12, 1 << 8
MODO_PHY, MODO_MAC = "phy", "mac"


class EthTrafficDriver(Driver):
    def __init__(self, periph, *, mode: str = MODO_PHY, speed100: bool = True,
                 phy_addr: int | None = None, frames: int = 128, batches: int = 1,
                 check_data: bool = True, hse_hz: float = 0.0, ram_base: int = 0,
                 ram_size: int = 0, name: str = "eth") -> None:
        self.periph, self.mode, self.speed100 = periph, mode, speed100
        self.phy_addr, self.frames, self.batches = phy_addr, frames, batches
        self.check_data, self.hse_hz = check_data, hse_hz
        self.ram_base, self.ram_size, self.name = ram_base, ram_size, name
        self.results: dict[int, list[BatchResult]] = {}
        self.last_size: int | None = None
        self.phy_info: dict = {}
        self.clock_source = ""
        self._snaps: list = []
        self._bmcr: int | None = None
        self.mdio: EthMdio | None = None
        self.traffic: EthTraffic | None = None

    @property
    def line_rate(self) -> float:
        return 100e6 if self.speed100 else 10e6

    def setup(self, pal) -> None:
        rmii = not (self.periph.has("RX_CLK") or self.periph.has("TX_CLK"))
        for s in self.periph.pins.values():
            self._snaps.append(snapshot_pin(pal, s.port, s.pin))
            set_af(pal, s.port, s.pin, pin_af(pal, s, self.periph.name), speed=3)
        self.mdio = EthMdio(pal, rmii=rmii)
        self.mdio.setup()
        if self.phy_addr is None:                       # procura o PHY (0 a 31)
            for addr in range(32):
                info = self.mdio.identify(addr)
                if info["id1"] not in (0x0000, 0xFFFF):
                    self.phy_addr, self.phy_info = addr, info
                    break
            else:
                raise RuntimeError("nenhum PHY respondeu no MDIO (endereços 0 a 31)")
        else:
            self.phy_info = self.mdio.identify(self.phy_addr)
        tree = clock_tree(pal, self.hse_hz)
        self.clock_source = tree.source if tree.source != "PLL1" else f"PLL1 ← {tree.pll_src}"
        self.traffic = EthTraffic(pal, self.ram_base, self.ram_size)
        self.traffic.setup(rmii=rmii, speed100=self.speed100, full_duplex=True,
                           mac_loopback=self.mode == MODO_MAC, hclk_hz=tree.hclk)
        self._bmcr = self.mdio.read(self.phy_addr, 0)
        if self.mode == MODO_PHY:
            speed = BMCR_SPEED100 if self.speed100 else 0
            self.mdio.write(self.phy_addr, 0, BMCR_LOOPBACK | speed | BMCR_FD)
            time.sleep(0.05)

    def apply(self, pal, size: int) -> None:
        self.last_size = size
        self.results[size] = [self.traffic.run_batch(size, self.frames,
                                                     check_data=self.check_data)
                              for _ in range(self.batches)]

    def teardown(self, pal) -> None:
        try:
            if self.mdio is not None and self._bmcr is not None:
                self.mdio.write(self.phy_addr, 0, self._bmcr)    # devolve o PHY (autoneg)
                if self.phy_info.get("link") and self.mode == MODO_PHY:
                    # havia link antes: espera renegociar (~2-3 s) para o próximo teste
                    deadline = time.perf_counter() + 4.0
                    while time.perf_counter() < deadline and \
                            not self.mdio.identify(self.phy_addr)["link"]:
                        time.sleep(0.1)
            if self.traffic is not None:
                self.traffic.restore()
            if self.mdio is not None:
                self.mdio.restore()
        finally:
            for snap in reversed(self._snaps):
                restore_pin(pal, snap)
            self._snaps = []


class EthTrafficMonitor(Monitor):
    """Resumo do último tamanho aplicado pelo driver (soma dos lotes)."""

    def __init__(self, driver: EthTrafficDriver, name: str = "eth_stats") -> None:
        self.driver, self.name = driver, name

    def sample(self, pal) -> dict | None:
        d = self.driver
        if d.last_size is None:
            return None
        rs = d.results[d.last_size]
        sent = sum(r.sent for r in rs)
        errors = sum(r.errors for r in rs)
        rates = [r.line_mbps() for r in rs if r.line_mbps()]
        data = [r.data_mbps() for r in rs if r.data_mbps()]
        fps = [r.fps for r in rs if r.fps]
        line = sum(rates) / len(rates) if rates else None
        return {
            "tamanho": d.last_size, "enviados": sent,
            "recebidos": sum(r.received for r in rs), "erros": errors,
            "erros_crc": sum(r.crc_errors for r in rs),
            "erros_dados": sum(r.data_errors for r in rs),
            "perdidos": sum(r.lost for r in rs), "comparados": sum(r.checked for r in rs),
            "fer": errors / sent if sent else 1.0,
            "bits": sent * d.last_size * 8,
            "mbps_fio": line, "mbps_dados": sum(data) / len(data) if data else None,
            "quadros_s": sum(fps) / len(fps) if fps else None,
            "utilizacao_pct": line * 1e6 / d.line_rate * 100 if line else None,
            "teorico_quadros_s": d.line_rate / ((d.last_size + PREAMBLE_IFG) * 8),
            "notas": sorted({n for r in rs for n in r.notes}),
        }
