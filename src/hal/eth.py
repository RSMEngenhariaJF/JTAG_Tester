"""Ethernet: leitura de registradores do PHY pelo MDIO do MAC (não envia quadros).

Valida MAC com clock, pinos MDC/MDIO, alimentação e endereço do PHY, e lê o
estado do link (registrador 1, bit 2). Funciona com o firmware rodando: o MDIO
é compartilhado, então leituras simultâneas do firmware podem colidir (raro).
"""

from __future__ import annotations

from hal.common import enable_clock, has_register, wait

PHY_BCR, PHY_BSR, PHY_ID1, PHY_ID2 = 0, 1, 2, 3
BSR_LINK = 1 << 2
BSR_AUTONEG_DONE = 1 << 5


def _mac_periph(pal) -> str:
    for name in pal.device.peripheral_names():
        if "MAC" in name.upper() and "ETH" in name.upper():
            return name
    raise LookupError("Este MCU não tem MAC Ethernet no SVD")


class EthMdio:
    def __init__(self, pal, *, rmii: bool = True) -> None:
        """rmii: interface com o PHY (RMII ou MII), escolhida pelos pinos do Pinout."""
        self.pal = pal
        self.rmii = rmii
        self.mac = _mac_periph(pal)
        self.v2 = has_register(pal, self.mac, "MACMDIOAR")          # H7
        self._pmcr_old: int | None = None

    def setup(self) -> None:
        p = self.pal
        if self.v2:
            reg, field = "AHB1ENR", "ETH1MACEN"
            if not p.read_field("RCC", reg, field):
                # Interface (RMII/MII) precisa ser escolhida antes de ligar o clock do MAC
                from hal.common import enable_clock as _en
                _en(p, "SYSCFG")
                self._pmcr_old = p.read_field("SYSCFG", "PMCR", "EPIS")
                p.modify_field("SYSCFG", "PMCR", "EPIS", 0b100 if self.rmii else 0b000)
            p.modify_field("RCC", reg, field, 1)
        else:
            enable_clock(p, "ETHMAC")

    def read(self, phy: int, reg: int, timeout_s: float = 0.05) -> int:
        p = self.pal
        if self.v2:
            # CR=0101: HCLK/124 (MDC ≤ 2,5 MHz até 300 MHz); GOC=11 leitura; MB=1
            p.write_reg(self.mac, "MACMDIOAR",
                        (phy & 31) << 21 | (reg & 31) << 16 | 0b0101 << 8 | 0b11 << 2 | 1)
            wait(lambda: not p.read_reg(self.mac, "MACMDIOAR") & 1, timeout_s,
                 "MDIO ocupado (MB não desceu)")
            return p.read_reg(self.mac, "MACMDIODR") & 0xFFFF
        p.write_reg(self.mac, "MACMIIAR", (phy & 31) << 11 | (reg & 31) << 6 | 0b100 << 2 | 1)
        wait(lambda: not p.read_reg(self.mac, "MACMIIAR") & 1, timeout_s,
             "MDIO ocupado (MB não desceu)")
        return p.read_reg(self.mac, "MACMIIDR") & 0xFFFF

    def write(self, phy: int, reg: int, value: int, timeout_s: float = 0.05) -> None:
        p = self.pal
        if self.v2:
            p.write_reg(self.mac, "MACMDIODR", value & 0xFFFF)
            # GOC=01 escrita
            p.write_reg(self.mac, "MACMDIOAR",
                        (phy & 31) << 21 | (reg & 31) << 16 | 0b0101 << 8 | 0b01 << 2 | 1)
            wait(lambda: not p.read_reg(self.mac, "MACMDIOAR") & 1, timeout_s,
                 "MDIO ocupado (MB não desceu)")
            return
        p.write_reg(self.mac, "MACMIIDR", value & 0xFFFF)
        p.write_reg(self.mac, "MACMIIAR",
                    (phy & 31) << 11 | (reg & 31) << 6 | 0b100 << 2 | 1 << 1 | 1)
        wait(lambda: not p.read_reg(self.mac, "MACMIIAR") & 1, timeout_s,
             "MDIO ocupado (MB não desceu)")

    def identify(self, phy: int) -> dict:
        id1, id2 = self.read(phy, PHY_ID1), self.read(phy, PHY_ID2)
        bsr = self.read(phy, PHY_BSR)
        bsr = self.read(phy, PHY_BSR)            # bit de link é "latched low": 2ª leitura
        oui = (id1 << 6) | (id2 >> 10)
        return {"id1": id1, "id2": id2, "oui": oui, "model": id2 >> 4 & 0x3F,
                "rev": id2 & 0xF, "bsr": bsr, "link": bool(bsr & BSR_LINK),
                "autoneg_done": bool(bsr & BSR_AUTONEG_DONE)}

    def restore(self) -> None:
        if self._pmcr_old is not None:
            self.pal.modify_field("RCC", "AHB1ENR", "ETH1MACEN", 0)
            self.pal.modify_field("SYSCFG", "PMCR", "EPIS", self._pmcr_old)
            self._pmcr_old = None
