"""Ethernet: caminho de dados MAC + MTL + DMA (MAC v2 do STM32H7) para teste de tráfego.

Sem firmware: o testador monta tudo pela SWD. Os descritores e os buffers ficam
na SRAM que o DMA do Ethernet enxerga (AXI SRAM no H7). Cada lote:

    1. grava um anel de N descritores de TX (todos apontando para K buffers com
       padrões diferentes) e um anel de N+1 descritores de RX (um buffer cada);
    2. liga MAC/DMA e escreve o tail pointer de TX — o DMA transmite sozinho,
       quadro atrás de quadro, sem depender da velocidade do SWD;
    3. espera o último descritor de TX ser devolvido e lê:
       - marcas de tempo PTP do 1º e do último quadro (TDES0/TDES1) → taxa real;
       - descritores de RX (erros de CRC, tamanho) e contadores MMC;
       - os buffers recebidos, comparados byte a byte com o enviado.

Referências: RM0433 §58 (Ethernet), descritores em §58.10, PTP em §58.9.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from hal.common import has_register, wait

log = logging.getLogger("hal.eth")

MAC, MTL, DMA = "Ethernet_MAC", "Ethernet_MTL", "Ethernet_DMA"

# Descritores (normal, formato de leitura / write-back)
TDES2_TTSE, TDES2_IOC = 1 << 30, 1 << 31
TDES3_OWN, TDES3_FD, TDES3_LD = 1 << 31, 1 << 29, 1 << 28
TDES3_TTSS, TDES3_ES = 1 << 17, 1 << 15
RDES3_OWN, RDES3_BUF1V = 1 << 31, 1 << 24
RDES3_ES, RDES3_CE, RDES3_LD, RDES3_FD = 1 << 15, 1 << 24, 1 << 28, 1 << 29

ETHERTYPE = 0x88B5                   # IEEE 802 "local experimental"
MAC_ADDR = bytes((0x02, 0x00, 0x00, 0x48, 0x42, 0x52))   # administrado localmente
PREAMBLE_IFG = 20                    # preâmbulo + SFD (8) + intervalo entre quadros (12)


def frame_bytes(size: int, pattern: int) -> bytes:
    """Quadro de `size` bytes no fio (FCS incluída): dst, src, ethertype, carga."""
    payload_len = size - 4 - 14
    seed = (pattern * 0x9E3779B1 + 1) & 0xFFFFFFFF
    payload = bytearray()
    while len(payload) < payload_len:            # xorshift32: padrão reprodutível
        seed ^= seed << 13 & 0xFFFFFFFF
        seed ^= seed >> 17
        seed ^= seed << 5 & 0xFFFFFFFF
        payload += seed.to_bytes(4, "little")
    return MAC_ADDR + MAC_ADDR + ETHERTYPE.to_bytes(2, "big") + bytes(payload[:payload_len])


def _words(data: bytes) -> list[int]:
    data = data + b"\0" * (-len(data) % 4)
    return [int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data), 4)]


def _align(x: int, a: int) -> int:
    return (x + a - 1) // a * a


@dataclass
class BatchResult:
    size:        int
    sent:        int                     # descritores de TX devolvidos sem erro
    received:    int                     # descritores de RX completos sem erro
    rx_errors:   int                     # descritores de RX com erro (CRC, tamanho...)
    crc_errors:  int                     # contador MMC
    data_errors: int                     # quadros recebidos com conteúdo diferente
    checked:     int                     # quadros comparados byte a byte
    lost:        int                     # enviados que não chegaram
    duration_s:  float | None            # 1º → último quadro pelo PTP (None = sem PTP)
    host_s:      float                   # tempo pelo PC (inclui latência SWD)
    dma_status:  int = 0
    notes:       list[str] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return self.rx_errors + self.data_errors + self.lost

    @property
    def fer(self) -> float:
        return self.errors / self.sent if self.sent else 1.0

    @property
    def fps(self) -> float | None:
        if self.duration_s and self.sent > 1:
            return (self.sent - 1) / self.duration_s
        return None

    def line_mbps(self) -> float | None:
        """Ocupação do fio (quadro + preâmbulo + IFG), em Mbit/s."""
        fps = self.fps
        return fps * (self.size + PREAMBLE_IFG) * 8 / 1e6 if fps else None

    def data_mbps(self) -> float | None:
        """Bits de quadro por segundo (sem preâmbulo/IFG), em Mbit/s."""
        fps = self.fps
        return fps * self.size * 8 / 1e6 if fps else None


class EthTraffic:
    """Uso::

        t = EthTraffic(pal, ram_base=0x24008000, ram_size=0x70000)
        t.setup(rmii=True, speed100=True, mac_loopback=False, hclk_hz=64e6)
        r = t.run_batch(1518, 128)
        t.restore()
    """

    def __init__(self, pal, ram_base: int, ram_size: int) -> None:
        if not has_register(pal, MAC, "MACMDIOAR"):
            raise LookupError("teste de tráfego Ethernet implementado para o MAC v2 (STM32H7)")
        self.pal, self.ram_base, self.ram_size = pal, ram_base, ram_size
        self._clk_old: dict[str, int] | None = None
        self._epis_old: int | None = None
        self.ptp = False
        self.speed100 = True

    # ── Memória do alvo ───────────────────────────────────────────────────

    def _wblock(self, addr: int, words: list[int]) -> None:
        mem = self.pal.mem
        if hasattr(mem, "write_block32"):
            mem.write_block32(addr, words)
        else:
            for i, w in enumerate(words):
                mem.write_mem32(addr + 4 * i, w)

    def _rblock(self, addr: int, count: int) -> list[int]:
        mem = self.pal.mem
        if hasattr(mem, "read_block32"):
            return list(mem.read_block32(addr, count))
        return [mem.read_mem32(addr + 4 * i) for i in range(count)]

    # ── Preparação ────────────────────────────────────────────────────────

    def setup(self, *, rmii: bool = True, speed100: bool = True, full_duplex: bool = True,
              mac_loopback: bool = False, hclk_hz: float = 0.0) -> None:
        p = self.pal
        self.speed100 = speed100
        self._clk_old = {f: p.read_field("RCC", "AHB1ENR", f)
                         for f in ("ETH1MACEN", "ETH1TXEN", "ETH1RXEN")}
        # Interface RMII/MII escolhida com o MAC em reset (RM0433 §58.4.4)
        p.modify_field("RCC", "APB4ENR", "SYSCFGEN", 1)
        self._epis_old = p.read_field("SYSCFG", "PMCR", "EPIS")
        p.modify_field("RCC", "AHB1RSTR", "ETH1MACRST", 1)
        p.modify_field("SYSCFG", "PMCR", "EPIS", 0b100 if rmii else 0b000)
        for f in self._clk_old:
            p.modify_field("RCC", "AHB1ENR", f, 1)
        p.modify_field("RCC", "AHB1RSTR", "ETH1MACRST", 0)

        p.modify_field(DMA, "DMAMR", "SWR", 1)
        wait(lambda: not p.read_field(DMA, "DMAMR", "SWR"), 0.2,
             "reset do DMA do Ethernet não terminou: falta o clock do PHY "
             "(REF_CLK 50 MHz no RMII) — PHY alimentado? cristal do PHY? trilha REF_CLK?")
        p.write_reg(DMA, "DMASBMR", 1 << 12 | 1)                 # AAL + rajada fixa
        p.write_reg(DMA, "DMACCR", 0)                             # descritores contíguos
        p.write_reg(MTL, "MTLTxQOMR", 7 << 16 | 0b10 << 2 | 1 << 1)   # 2 KB, ligada, TSF
        p.write_reg(MTL, "MTLRxQOMR", 7 << 20 | 1 << 5)           # 2 KB, RSF
        p.write_reg(MAC, "MACPFR", 1 << 31 | 1)                   # recebe tudo
        p.write_reg(MAC, "MACA0HR", 1 << 31 | int.from_bytes(MAC_ADDR[4:], "little"))
        p.write_reg(MAC, "MACA0LR", int.from_bytes(MAC_ADDR[:4], "little"))
        self.maccr = (1 << 14 if speed100 else 0) | (1 << 13 if full_duplex else 0) \
            | (1 << 12 if mac_loopback else 0)
        p.write_reg(MAC, "MACCR", self.maccr)
        self.ptp = self._ptp_start(hclk_hz)
        log.info("ETH: %s, %s, %s duplex%s, PTP %s (HCLK %.6g Hz), SRAM 0x%08X+%d KB",
                 "RMII" if rmii else "MII", "100 Mbit/s" if speed100 else "10 Mbit/s",
                 "full" if full_duplex else "half", ", loopback no MAC" if mac_loopback else "",
                 "ligado" if self.ptp else "desligado", hclk_hz, self.ram_base,
                 self.ram_size // 1024)

    def _ptp_start(self, hclk_hz: float) -> bool:
        """Relógio PTP a 50 MHz efetivos (20 ns) por correção fina sobre o HCLK."""
        p = self.pal
        if hclk_hz <= 50e6:
            return False
        p.write_reg(MAC, "MACTSCR", 1 | 1 << 1 | 1 << 9)          # TSENA, fino, rollover em ns
        p.write_reg(MAC, "MACSSIR", 20 << 16)
        p.write_reg(MAC, "MACTSAR", round(2**32 * 50e6 / hclk_hz) & 0xFFFFFFFF)
        p.modify_field(MAC, "MACTSCR", "TSADDREG", 1)
        wait(lambda: not p.read_field(MAC, "MACTSCR", "TSADDREG"), 0.05, "PTP: addend")
        p.write_reg(MAC, "MACSTSUR", 0)
        p.write_reg(MAC, "MACSTNUR", 0)
        p.modify_field(MAC, "MACTSCR", "TSINIT", 1)
        wait(lambda: not p.read_field(MAC, "MACTSCR", "TSINIT"), 0.05, "PTP: inicialização")
        return True

    # ── Lote ──────────────────────────────────────────────────────────────

    def layout(self, size: int, count: int, patterns: int) -> dict[str, int]:
        stride = _align(size, 64)
        tx_d = _align(self.ram_base, 64)
        rx_d = tx_d + _align((count + 1) * 16, 64)
        tx_b = rx_d + _align((count + 1) * 16, 64)
        rx_b = tx_b + patterns * stride
        end = rx_b + (count + 1) * stride
        if end - self.ram_base > self.ram_size:
            raise ValueError(f"{count} quadros de {size} B não cabem na SRAM reservada "
                             f"({self.ram_size // 1024} KB): reduza 'Quadros por lote'")
        return {"tx_d": tx_d, "rx_d": rx_d, "tx_b": tx_b, "rx_b": rx_b, "stride": stride}

    def run_batch(self, size: int, count: int, *, check_data: bool = True,
                  expect_rx: bool = True, patterns: int = 4,
                  timeout_s: float = 2.0) -> BatchResult:
        if not 64 <= size <= 1518:
            raise ValueError("tamanho de quadro entre 64 e 1518 bytes")
        p = self.pal
        patterns = max(1, min(patterns, count))
        lay = self.layout(size, count, patterns)
        tx_d, rx_d, tx_b, rx_b, stride = (lay[k] for k in ("tx_d", "rx_d", "tx_b", "rx_b",
                                                           "stride"))
        flen = size - 4                                   # o MAC acrescenta a FCS
        frames = [frame_bytes(size, k) for k in range(patterns)]
        for k, fr in enumerate(frames):
            self._wblock(tx_b + k * stride, _words(fr))

        # Para tudo e limpa contadores antes de montar os anéis
        p.write_reg(MAC, "MACCR", self.maccr)
        p.modify_field(DMA, "DMACTxCR", "ST", 0)
        p.modify_field(DMA, "DMACRxCR", "SR", 0)
        p.write_reg(DMA, "DMACSR", 0xFFFFFFFF)
        p.modify_field(MAC, "MMC_CONTROL", "CNTRST", 1)

        txd = []
        for i in range(count):
            ts = TDES2_TTSE if i in (0, count - 1) and self.ptp else 0
            txd += [tx_b + (i % patterns) * stride, 0, flen | ts,
                    TDES3_OWN | TDES3_FD | TDES3_LD | flen]
        txd += [0, 0, 0, 0]                               # descritor extra = tail (vazio)
        self._wblock(tx_d, txd)
        rxd = []
        for i in range(count + 1):
            rxd += [rx_b + i * stride, 0, 0, RDES3_OWN | RDES3_BUF1V]
        self._wblock(rx_d, rxd)

        p.write_reg(DMA, "DMACTxDLAR", tx_d)
        p.write_reg(DMA, "DMACTxRLR", count)              # anel com count+1 descritores
        p.write_reg(DMA, "DMACRxDLAR", rx_d)
        p.write_reg(DMA, "DMACRxRLR", count)
        p.write_reg(DMA, "DMACRxCR", 32 << 16 | stride << 1 | 1)          # RXPBL, RBSZ, SR
        p.write_reg(DMA, "DMACRxDTPR", rx_d + count * 16)
        p.write_reg(DMA, "DMACTxCR", 32 << 16 | 1 << 4 | 1)               # TXPBL, OSF, ST
        p.write_reg(MAC, "MACCR", self.maccr | 0b11)                       # TE + RE

        t0 = time.perf_counter()
        p.write_reg(DMA, "DMACTxDTPR", tx_d + count * 16)                  # dispara o TX
        last = tx_d + (count - 1) * 16 + 12
        try:
            wait(lambda: not p.mem.read_mem32(last) & TDES3_OWN, timeout_s,
                 "a transmissão não terminou (DMA parado: clock do PHY? link/loopback?)")
        except TimeoutError as exc:
            note = str(exc)
        else:
            note = ""
        if expect_rx:                                      # o último quadro ainda chegando
            time.sleep(0.002 + (size + PREAMBLE_IFG) * 8 / (100e6 if self.speed100 else 10e6))
        host_s = time.perf_counter() - t0
        p.write_reg(MAC, "MACCR", self.maccr)
        dma_status = p.read_reg(DMA, "DMACSR")

        txw = self._rblock(tx_d, count * 4)
        sent = sum(1 for i in range(count)
                   if not txw[4 * i + 3] & (TDES3_OWN | TDES3_ES))
        duration = None
        if self.ptp:
            ts = [(txw[4 * i + 1] + txw[4 * i] * 1e-9) if txw[4 * i + 3] & TDES3_TTSS else None
                  for i in (0, count - 1)]
            if None not in ts and count > 1:
                duration = ts[1] - ts[0]
        rxw = self._rblock(rx_d, (count + 1) * 4)
        done = [i for i in range(count + 1) if not rxw[4 * i + 3] & RDES3_OWN]
        bad = [i for i in done if rxw[4 * i + 3] & (RDES3_ES | RDES3_CE)
               or rxw[4 * i + 3] & 0x7FFF != size]
        good = [i for i in done if i not in bad]
        data_errors = 0
        checked = 0
        if check_data and expect_rx:
            # Compara com o padrão esperado na ordem; se não bater (ex.: um quadro
            # perdido desalinhou a sequência), aceita qualquer um dos padrões enviados.
            for n, i in enumerate(good):
                words = self._rblock(rx_b + i * stride, _align(flen, 4) // 4)
                got = b"".join(w.to_bytes(4, "little") for w in words)[:flen]
                if got != frames[n % patterns] and got not in frames:
                    data_errors += 1
                checked += 1
        crc = p.read_reg(MAC, "RX_CRC_ERROR_PACKETS")
        res = BatchResult(size, sent, len(good) if expect_rx else 0, len(bad) if expect_rx else 0,
                          crc if expect_rx else 0, data_errors, checked,
                          max(0, sent - len(done)) if expect_rx else 0,
                          duration, host_s, dma_status)
        if note:
            res.notes.append(note)
        if dma_status & (1 << 12):
            res.notes.append("erro fatal de barramento no DMA (FBE): SRAM inacessível ao DMA?")
        p.modify_field(DMA, "DMACTxCR", "ST", 0)
        p.modify_field(DMA, "DMACRxCR", "SR", 0)
        log.info("ETH lote %d B x%d: TX %d, RX ok %d, erros RX %d, CRC %d, dados %d/%d, "
                 "perdidos %d, PTP %s s, DMACSR 0x%X%s", size, count, res.sent, res.received,
                 res.rx_errors, res.crc_errors, res.data_errors, res.checked, res.lost,
                 f"{duration:.6f}" if duration else "-", dma_status,
                 f" | {'; '.join(res.notes)}" if res.notes else "")
        return res

    # ── Restauração ───────────────────────────────────────────────────────

    def restore(self) -> None:
        p = self.pal
        if self._clk_old is None:
            return
        p.write_reg(MAC, "MACCR", 0)
        p.modify_field(DMA, "DMACTxCR", "ST", 0)
        p.modify_field(DMA, "DMACRxCR", "SR", 0)
        p.write_reg(MAC, "MACTSCR", 0)
        p.modify_field("RCC", "AHB1RSTR", "ETH1MACRST", 1)     # MAC volta ao reset
        p.modify_field("RCC", "AHB1RSTR", "ETH1MACRST", 0)
        for f, v in self._clk_old.items():
            p.modify_field("RCC", "AHB1ENR", f, v)
        if self._epis_old is not None:
            p.modify_field("SYSCFG", "PMCR", "EPIS", self._epis_old)
        self._clk_old = self._epis_old = None
