"""CAN em loopback interno (sem transceptor/fio): FDCAN (H7) e bxCAN (F4).

O controlador transmite um quadro e o recebe de volta internamente; valida
clock, configuração de bit timing, RAM de mensagens/filtros e o caminho TX→RX.
Se o periférico estiver em uso pelo firmware (fora do modo de inicialização), o
teste recusa para não derrubar a comunicação do produto.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from hal.common import enable_clock, has_register, wait

log = logging.getLogger("hal.can")


class CanInUseError(RuntimeError):
    """O firmware está usando o controlador CAN."""


@dataclass
class Frame:
    std_id: int
    data: bytes


# ── FDCAN (H7) ────────────────────────────────────────────────────────────────

SRAMCAN = 0x4000AC00
CCCR_INIT, CCCR_CCE, CCCR_MON, CCCR_TEST = 1 << 0, 1 << 1, 1 << 5, 1 << 7
TEST_LBCK = 1 << 4
# Área da RAM de mensagens usada pelo teste (em palavras de 32 bits): fim da RAM
# (2560 palavras), longe do início onde o CubeMX costuma alocar.
_RX_WORD, _TX_WORD = 2400, 2440
_REGS_FD = ("FDCAN_CCCR", "FDCAN_TEST", "FDCAN_NBTP", "FDCAN_GFC", "FDCAN_SIDFC",
            "FDCAN_RXF0C", "FDCAN_RXESC", "FDCAN_TXBC", "FDCAN_TXESC")


def nbtp_for(f_ck: int, bitrate: int) -> tuple[int, int]:
    """(valor NBTP, bitrate real): 16 quanta por bit, ponto de amostra 87,5 %."""
    brp = max(1, round(f_ck / (bitrate * 16)))
    real = f_ck / (brp * 16)
    # 1 (sync) + 13 (TSEG1) + 2 (TSEG2) = 16 tq; NSJW=1 (campos gravados com -1)
    return (1 << 25) | (brp - 1) << 16 | (13 - 1) << 8 | (2 - 1), real


class FdcanLoopback:
    """Clock do núcleo do FDCAN = HSE (frequência do projeto). Sem firmware, o HSE é
    ligado aqui (bypass conforme o projeto) e desligado no restore()."""

    def __init__(self, pal, name: str = "FDCAN1", *, hse_hz: float = 0.0,
                 hse_bypass: bool = False) -> None:
        self.pal = pal
        self.name = name
        self.hse_hz, self.hse_bypass = hse_hz, hse_bypass
        self._hse_started = False
        self._saved: dict[str, int] = {}
        self._ram: dict[int, int] = {}
        self._kernel_old: int | None = None

    def setup(self, bitrate: int = 500_000) -> float:
        p = self.pal
        enable_clock(p, self.name)
        cccr = p.read_reg(self.name, "FDCAN_CCCR")
        if not cccr & CCCR_INIT:
            raise CanInUseError(f"{self.name} em operação (CCCR.INIT=0): firmware usando o CAN")
        if not self.hse_hz:
            raise RuntimeError("frequência do HSE desconhecida: importe o .ioc no projeto ou "
                               "informe o HSE no teste")
        if not p.read_field("RCC", "CR", "HSERDY"):
            p.modify_field("RCC", "CR", "HSEBYP", int(self.hse_bypass))
            p.modify_field("RCC", "CR", "HSEON", 1)
            self._hse_started = True
            wait(lambda: p.read_field("RCC", "CR", "HSERDY"), 0.1,
                 "HSE não ficou pronto (HSERDY=0): cristal ou trilhas OSC_IN/OSC_OUT")
        self._kernel_old = p.read_field("RCC", "D2CCIP1R", "FDCANSEL")
        p.modify_field("RCC", "D2CCIP1R", "FDCANSEL", 0b00)          # hse_ck
        f_ck = self.hse_hz

        self._saved = {r: p.read_reg(self.name, r) for r in _REGS_FD}
        for w in list(range(_RX_WORD, _RX_WORD + 8)) + list(range(_TX_WORD, _TX_WORD + 4)):
            self._ram[w] = p.mem.read_mem32(SRAMCAN + 4 * w)

        p.write_reg(self.name, "FDCAN_CCCR", CCCR_INIT)
        wait(lambda: p.read_reg(self.name, "FDCAN_CCCR") & CCCR_INIT, 0.1, "INIT não entrou")
        # Um passo por escrita: CCE libera a configuração; TEST só é aceito com CCE=1
        p.write_reg(self.name, "FDCAN_CCCR", CCCR_INIT | CCCR_CCE)
        p.write_reg(self.name, "FDCAN_CCCR", CCCR_INIT | CCCR_CCE | CCCR_TEST | CCCR_MON)
        p.write_reg(self.name, "FDCAN_TEST", TEST_LBCK)
        if not p.read_reg(self.name, "FDCAN_TEST") & TEST_LBCK:
            raise RuntimeError(f"{self.name}: loopback interno (TEST.LBCK) não foi aceito")
        nbtp, real = nbtp_for(f_ck, bitrate)
        p.write_reg(self.name, "FDCAN_NBTP", nbtp)
        p.write_reg(self.name, "FDCAN_SIDFC", 0)                     # sem filtros
        p.write_reg(self.name, "FDCAN_GFC", 0)                       # aceita tudo na FIFO0
        p.write_reg(self.name, "FDCAN_RXF0C", 2 << 16 | _RX_WORD << 2)
        p.write_reg(self.name, "FDCAN_RXESC", 0)                     # 8 bytes de dados
        p.write_reg(self.name, "FDCAN_TXBC", 1 << 16 | _TX_WORD << 2)
        p.write_reg(self.name, "FDCAN_TXESC", 0)
        # Sai de INIT mantendo TEST (loopback) e MON; CCE é limpo pelo hardware
        p.write_reg(self.name, "FDCAN_CCCR", CCCR_TEST | CCCR_MON)
        wait(lambda: not p.read_reg(self.name, "FDCAN_CCCR") & CCCR_INIT, 0.1, "INIT não saiu")
        log.info("%s: loopback interno, %.0f bit/s (pedido %d), clock HSE %.6g Hz%s",
                 self.name, real, bitrate, f_ck, " (ligado pelo teste)" if self._hse_started
                 else "")
        return real

    def send_receive(self, frame: Frame, timeout_s: float = 0.1) -> Frame:
        p = self.pal
        data = frame.data.ljust(8, b"\0")
        p.mem.write_mem32(SRAMCAN + 4 * _TX_WORD, (frame.std_id & 0x7FF) << 18)
        p.mem.write_mem32(SRAMCAN + 4 * (_TX_WORD + 1), len(frame.data) << 16)
        p.mem.write_mem32(SRAMCAN + 4 * (_TX_WORD + 2), int.from_bytes(data[:4], "little"))
        p.mem.write_mem32(SRAMCAN + 4 * (_TX_WORD + 3), int.from_bytes(data[4:], "little"))
        p.write_reg(self.name, "FDCAN_TXBAR", 1)
        wait(lambda: p.read_reg(self.name, "FDCAN_TXBTO") & 1, timeout_s,
             "transmissão não concluiu (bit timing/clock?)")
        wait(lambda: p.read_reg(self.name, "FDCAN_RXF0S") & 0x7F, timeout_s,
             "quadro não voltou na FIFO 0")
        idx = p.read_reg(self.name, "FDCAN_RXF0S") >> 8 & 0x3F
        base = SRAMCAN + 4 * (_RX_WORD + 4 * idx)
        r0, r1 = p.mem.read_mem32(base), p.mem.read_mem32(base + 4)
        raw = (p.mem.read_mem32(base + 8).to_bytes(4, "little")
               + p.mem.read_mem32(base + 12).to_bytes(4, "little"))
        p.write_reg(self.name, "FDCAN_RXF0A", idx)
        dlc = r1 >> 16 & 0xF
        return Frame(r0 >> 18 & 0x7FF, raw[:min(dlc, 8)])

    def error_counters(self) -> tuple[int, int]:
        ecr = self.pal.read_reg(self.name, "FDCAN_ECR")
        return ecr & 0xFF, ecr >> 8 & 0x7F

    def restore(self) -> None:
        p = self.pal
        if self._saved:
            p.write_reg(self.name, "FDCAN_CCCR", CCCR_INIT)
            wait(lambda: p.read_reg(self.name, "FDCAN_CCCR") & CCCR_INIT, 0.1, "INIT não entrou")
            p.write_reg(self.name, "FDCAN_CCCR", CCCR_INIT | CCCR_CCE)
            for r, v in self._saved.items():
                if r != "FDCAN_CCCR":
                    p.write_reg(self.name, r, v)
            p.write_reg(self.name, "FDCAN_CCCR", self._saved["FDCAN_CCCR"] | CCCR_INIT)
            self._saved = {}
        for w, v in self._ram.items():
            p.mem.write_mem32(SRAMCAN + 4 * w, v)
        self._ram = {}
        if self._kernel_old is not None:
            p.modify_field("RCC", "D2CCIP1R", "FDCANSEL", self._kernel_old)
            self._kernel_old = None
        if self._hse_started:
            p.modify_field("RCC", "CR", "HSEON", 0)
            self._hse_started = False


# ── bxCAN (F4) ────────────────────────────────────────────────────────────────

MCR_INRQ, MSR_INAK = 1 << 0, 1 << 0
BTR_LBKM, BTR_SILM = 1 << 30, 1 << 31
TSR_RQCP0, TSR_TXOK0 = 1 << 0, 1 << 1


class BxcanLoopback:
    """bxCAN em LBKM+SILM (loopback silencioso). Filtro 0 aceita tudo na FIFO 0."""

    def __init__(self, pal, name: str = "CAN1") -> None:
        self.pal = pal
        self.name = name
        self._saved: dict[str, int] = {}

    def setup(self, bitrate: int = 500_000) -> float:
        from instruments.rcc_helper import detect_pclk1

        p = self.pal
        enable_clock(p, self.name)
        if not p.read_reg(self.name, "MSR") & MSR_INAK and not p.read_reg(self.name, "MCR") & 2:
            raise CanInUseError(f"{self.name} em operação (MSR.INAK=0): firmware usando o CAN")
        self._saved = {r: p.read_reg(self.name, r) for r in
                       ("MCR", "BTR", "FMR", "FA1R", "FS1R", "FFA1R", "F0R1", "F0R2")}
        p.write_reg(self.name, "MCR", MCR_INRQ)                 # sai do sleep, entra em init
        wait(lambda: p.read_reg(self.name, "MSR") & MSR_INAK, 0.1, "INAK não subiu")
        f = detect_pclk1(p)
        brp = max(1, round(f / (bitrate * 16)))
        p.write_reg(self.name, "BTR", BTR_LBKM | BTR_SILM | (1 - 1) << 24 | (2 - 1) << 20
                    | (13 - 1) << 16 | (brp - 1))
        p.write_reg(self.name, "FMR", 1)                        # FINIT
        p.write_reg(self.name, "FS1R", p.read_reg(self.name, "FS1R") | 1)    # 32 bits
        p.write_reg(self.name, "FFA1R", p.read_reg(self.name, "FFA1R") & ~1)  # FIFO 0
        p.write_reg(self.name, "F0R1", 0)
        p.write_reg(self.name, "F0R2", 0)                       # máscara 0: aceita tudo
        p.write_reg(self.name, "FA1R", p.read_reg(self.name, "FA1R") | 1)
        p.write_reg(self.name, "FMR", 0)
        p.write_reg(self.name, "MCR", 0)                        # modo normal (loopback)
        wait(lambda: not p.read_reg(self.name, "MSR") & MSR_INAK, 0.1, "INAK não desceu")
        return f / (brp * 16)

    def send_receive(self, frame: Frame, timeout_s: float = 0.1) -> Frame:
        p = self.pal
        data = frame.data.ljust(8, b"\0")
        p.write_reg(self.name, "TDT0R", len(frame.data))
        p.write_reg(self.name, "TDL0R", int.from_bytes(data[:4], "little"))
        p.write_reg(self.name, "TDH0R", int.from_bytes(data[4:], "little"))
        p.write_reg(self.name, "TI0R", (frame.std_id & 0x7FF) << 21 | 1)     # TXRQ
        wait(lambda: p.read_reg(self.name, "TSR") & TSR_RQCP0, timeout_s, "TX não concluiu")
        wait(lambda: p.read_reg(self.name, "RF0R") & 3, timeout_s, "quadro não voltou")
        rid = p.read_reg(self.name, "RI0R") >> 21
        dlc = p.read_reg(self.name, "RDT0R") & 0xF
        raw = (p.read_reg(self.name, "RDL0R").to_bytes(4, "little")
               + p.read_reg(self.name, "RDH0R").to_bytes(4, "little"))
        p.write_reg(self.name, "RF0R", 1 << 5)                  # RFOM0
        return Frame(rid & 0x7FF, raw[:min(dlc, 8)])

    def error_counters(self) -> tuple[int, int]:
        esr = self.pal.read_reg(self.name, "ESR")
        return esr >> 16 & 0xFF, esr >> 24 & 0xFF

    def restore(self) -> None:
        p = self.pal
        if not self._saved:
            return
        p.write_reg(self.name, "MCR", MCR_INRQ)
        time.sleep(0.005)
        p.write_reg(self.name, "FMR", 1)
        for r in ("FA1R", "FS1R", "FFA1R", "F0R1", "F0R2"):
            p.write_reg(self.name, r, self._saved[r])
        p.write_reg(self.name, "FMR", self._saved["FMR"])
        p.write_reg(self.name, "BTR", self._saved["BTR"])
        p.write_reg(self.name, "MCR", self._saved["MCR"])
        self._saved = {}


def can_for(pal, name: str, *, hse_hz: float = 0.0, hse_bypass: bool = False):
    """Driver certo pelo SVD: FDCANx (H7, clock = HSE) ou CANx (F4, clock = APB1)."""
    if has_register(pal, name, "FDCAN_CCCR"):
        return FdcanLoopback(pal, name, hse_hz=hse_hz, hse_bypass=hse_bypass)
    if has_register(pal, name, "MCR"):
        return BxcanLoopback(pal, name)
    raise LookupError(f"{name} não é um controlador CAN conhecido neste SVD")
