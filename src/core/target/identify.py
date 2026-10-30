"""Identificação automática do microcontrolador conectado ao probe.

Lê apenas registradores de identificação — não faz halt, não escreve nada:

    DPIDR          (DP reg 0)   → fabricante/versão do Debug Port
    CPUID          0xE000ED00   → núcleo ARM (Cortex-M0/M3/M4/M7/M33...)
    ROM table PIDR 0xE00FFFD0.. → fabricante do chip (código JEP106)
    DBGMCU_IDCODE  (varia)      → DEV_ID/REV_ID — família STM32

Funciona com qualquer adaptador que implemente ``read_mem32`` (StLinkADIv5
ou ADIv5 sobre FT2232H). Aceita vários leitores — um por MEM-AP — porque em
alguns chips o DBGMCU só é visível por uma AP dedicada (STM32H7: AP2).

Referências:
    IHI0031C §2.3.1  — DPIDR
    DDI0403E §B4.1.2 — CPUID (ARMv7-M) / DDI0553 (ARMv8-M)
    IHI0031C §D1     — Peripheral ID / JEP106 nos componentes CoreSight
    Manuais de referência STM32 (RMxxxx), seção "DBGMCU" — tabela DEV_ID
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol, TypeVar

_T = TypeVar("_T")

# ── Endereços fixos ARMv6-M / ARMv7-M / ARMv8-M ──────────────────────────────

CPUID_ADDR: int = 0xE000ED00
ROM_PIDR_BASE: int = 0xE00FFFD0   # PIDR4 em +0x00, PIDR0..3 em +0x10..+0x1C

# Endereços candidatos de DBGMCU_IDCODE, conforme a família STM32
_IDCODE_F_L_G4: int = 0xE0042000   # F1/F2/F3/F4/F7/L1/L4/G4/WB/WL
_IDCODE_M0: int = 0x40015800       # F0/L0/G0/C0
_IDCODE_H7: int = 0x5C001000       # H7 (visto pelo núcleo, AP0)
_IDCODE_H7_DBG: int = 0xE00E1000   # H7 (visto pelo depurador, AP2 / APB-D)
_IDCODE_M33: int = 0xE0044000      # L5/U5

# ── Tabelas de decodificação ─────────────────────────────────────────────────

# CPUID.PARTNO (bits 15:4) quando IMPLEMENTER = 0x41 (ARM)
_ARM_CORES: dict[int, str] = {
    0xC20: "Cortex-M0",
    0xC60: "Cortex-M0+",
    0xC21: "Cortex-M1",
    0xC23: "Cortex-M3",
    0xC24: "Cortex-M4",
    0xC27: "Cortex-M7",
    0xD20: "Cortex-M23",
    0xD21: "Cortex-M33",
    0xD22: "Cortex-M55",
    0xD23: "Cortex-M85",
}

# (continuation, id) JEP106 → fabricante
_JEP106: dict[tuple[int, int], str] = {
    (0, 0x20): "STMicroelectronics",
    (4, 0x3B): "ARM",
    (0, 0x15): "NXP",
    (0, 0x17): "Texas Instruments",
    (0, 0x1F): "Microchip (Atmel)",
    (2, 0x44): "Nordic Semiconductor",
    (3, 0x73): "Silicon Labs",
    (9, 0x13): "Raspberry Pi",
}

# DBGMCU_IDCODE.DEV_ID (bits 11:0) → família STM32
STM32_DEV_IDS: dict[int, str] = {
    # F0
    0x440: "STM32F030x8/F05x",
    0x442: "STM32F030xC/F09x",
    0x444: "STM32F03x",
    0x445: "STM32F04x/F070x6",
    0x448: "STM32F07x",
    # F1
    0x410: "STM32F10x (medium density)",
    0x412: "STM32F10x (low density)",
    0x414: "STM32F10x (high density)",
    0x418: "STM32F105/F107",
    0x420: "STM32F100 (value line)",
    0x428: "STM32F100 (value line, high density)",
    0x430: "STM32F10x (XL density)",
    # F2
    0x411: "STM32F2xx",
    # F3
    0x422: "STM32F302xB/C/F303xB/C",
    0x432: "STM32F37x",
    0x438: "STM32F303x6/8/F334",
    0x439: "STM32F301/F302x6/8",
    0x446: "STM32F302xD/E/F303xD/E",
    # F4
    0x413: "STM32F405/F407/F415/F417",
    0x419: "STM32F42x/F43x",
    0x421: "STM32F446",
    0x423: "STM32F401xB/C",
    0x431: "STM32F411",
    0x433: "STM32F401xD/E",
    0x434: "STM32F469/F479",
    0x441: "STM32F412",
    0x458: "STM32F410",
    0x463: "STM32F413/F423",
    # F7
    0x449: "STM32F74x/F75x",
    0x451: "STM32F76x/F77x",
    0x452: "STM32F72x/F73x",
    # L0 / L1
    0x417: "STM32L05x/L06x",
    0x425: "STM32L031/L041",
    0x447: "STM32L07x/L08x",
    0x457: "STM32L011/L021",
    0x416: "STM32L1 (cat. 1)",
    0x429: "STM32L1 (cat. 2)",
    0x427: "STM32L1 (cat. 3)",
    0x436: "STM32L1 (cat. 4)",
    0x437: "STM32L1 (cat. 5/6)",
    # L4 / L5 / U5
    0x415: "STM32L47x/L48x",
    0x435: "STM32L43x/L44x",
    0x461: "STM32L49x/L4Ax",
    0x462: "STM32L45x/L46x",
    0x464: "STM32L41x/L42x",
    0x470: "STM32L4R/L4S",
    0x471: "STM32L4P/L4Q",
    0x472: "STM32L55x/L56x",
    0x482: "STM32U575/U585",
    # G0 / G4 / C0
    0x456: "STM32G05x/G06x",
    0x460: "STM32G07x/G08x",
    0x466: "STM32G03x/G04x",
    0x467: "STM32G0Bx/G0Cx",
    0x468: "STM32G431/G441",
    0x469: "STM32G47x/G48x",
    0x479: "STM32G491/G4A1",
    0x443: "STM32C011",
    0x453: "STM32C031",
    # H7 / WB / WL
    0x450: "STM32H74x/H75x",
    0x480: "STM32H7Ax/H7Bx",
    0x483: "STM32H72x/H73x",
    0x495: "STM32WB55",
    0x497: "STM32WLE5",
}


class IMemoryRead(Protocol):
    """Interface mínima exigida para identificar o alvo."""

    def read_mem32(self, addr: int) -> int: ...


@dataclass(frozen=True)
class McuInfo:
    """Resultado da identificação do microcontrolador."""

    dpidr: int
    cpuid: int | None
    vendor: str | None          # fabricante do chip (JEP106 da ROM table)
    idcode: int | None          # DBGMCU_IDCODE bruto
    idcode_addr: int | None

    @property
    def core(self) -> str | None:
        if self.cpuid is None:
            return None
        implementer = (self.cpuid >> 24) & 0xFF
        partno = (self.cpuid >> 4) & 0xFFF
        if implementer == 0x41:
            return _ARM_CORES.get(partno, f"ARM partno 0x{partno:03X}")
        return f"implementer 0x{implementer:02X} partno 0x{partno:03X}"

    @property
    def core_revision(self) -> str | None:
        if self.cpuid is None:
            return None
        variant = (self.cpuid >> 20) & 0xF
        revision = self.cpuid & 0xF
        return f"r{variant}p{revision}"

    @property
    def dev_id(self) -> int | None:
        return None if self.idcode is None else self.idcode & 0xFFF

    @property
    def rev_id(self) -> int | None:
        return None if self.idcode is None else (self.idcode >> 16) & 0xFFFF

    @property
    def family(self) -> str | None:
        dev_id = self.dev_id
        return None if dev_id is None else STM32_DEV_IDS.get(dev_id)

    @property
    def name(self) -> str:
        """Nome mais específico disponível, ex. 'STM32F446' ou 'Cortex-M4'."""
        return self.family or self.core or "desconhecido"

    def summary(self) -> str:
        """Resumo em várias linhas para exibição na GUI/CLI."""
        lines = [f"MCU: {self.name}"]
        if self.vendor:
            lines.append(f"Fabricante: {self.vendor}")
        if self.core:
            lines.append(f"Núcleo: {self.core} {self.core_revision}")
        if self.dev_id is not None and self.rev_id is not None:
            lines.append(f"DEV_ID=0x{self.dev_id:03X}  REV_ID=0x{self.rev_id:04X}")
        lines.append(f"DPIDR=0x{self.dpidr:08X}")
        return "\n".join(lines)


def identify(mem: IMemoryRead | Sequence[IMemoryRead], dpidr: int) -> McuInfo:
    """Identifica o MCU lendo apenas registradores de ID (sem halt).

    ``mem`` pode ser um leitor ou uma lista de leitores (um por MEM-AP);
    cada registrador é procurado em todos até achar um valor válido.
    Leituras que falham (endereço inexistente, núcleo inacessível) são
    ignoradas — o resultado traz o que foi possível descobrir.
    """
    mems = list(mem) if isinstance(mem, Sequence) else [mem]
    cpuid = _first(_read_cpuid(m) for m in mems)
    vendor = _first(_read_rom_vendor(m) for m in mems)
    idcode, idcode_addr = _first(_read_idcode(m, cpuid) for m in mems) or (None, None)
    return McuInfo(
        dpidr=dpidr,
        cpuid=cpuid,
        vendor=vendor,
        idcode=idcode,
        idcode_addr=idcode_addr,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _first(values: Iterable[_T | None]) -> _T | None:
    return next((v for v in values if v is not None), None)


def _try_read(mem: IMemoryRead, addr: int) -> int | None:
    try:
        return mem.read_mem32(addr) & 0xFFFFFFFF
    except Exception:
        return None


def _read_cpuid(mem: IMemoryRead) -> int | None:
    """CPUID só é aceito se o implementer for ARM (todo Cortex-M é 0x41)."""
    cpuid = _try_read(mem, CPUID_ADDR)
    if cpuid is None or (cpuid >> 24) != 0x41:
        return None
    return cpuid


def _read_rom_vendor(mem: IMemoryRead) -> str | None:
    pidr4 = _try_read(mem, ROM_PIDR_BASE)
    pidr1 = _try_read(mem, ROM_PIDR_BASE + 0x14)
    pidr2 = _try_read(mem, ROM_PIDR_BASE + 0x18)
    if pidr4 is None or pidr1 is None or pidr2 is None:
        return None
    if not pidr2 & 0x08:   # bit JEDEC: sem ele o campo não é JEP106
        return None
    jep_id = ((pidr2 & 0x07) << 4) | ((pidr1 >> 4) & 0x0F)
    jep_cont = pidr4 & 0x0F
    return _JEP106.get((jep_cont, jep_id), f"JEP106 {jep_cont}:0x{jep_id:02X}")


def _idcode_candidates(cpuid: int | None) -> list[int]:
    partno = None if cpuid is None else (cpuid >> 4) & 0xFFF
    if partno in (0xC20, 0xC60):              # M0/M0+ → F0/L0/G0/C0
        return [_IDCODE_M0, _IDCODE_F_L_G4]
    if partno == 0xC27:                       # M7 → H7 ou F7
        return [_IDCODE_H7_DBG, _IDCODE_H7, _IDCODE_F_L_G4]
    if partno == 0xD21:                       # M33 → L5/U5
        return [_IDCODE_M33, _IDCODE_F_L_G4]
    return [_IDCODE_F_L_G4, _IDCODE_M0, _IDCODE_H7_DBG, _IDCODE_H7, _IDCODE_M33]


def _read_idcode(mem: IMemoryRead, cpuid: int | None) -> tuple[int, int] | None:
    """Procura DBGMCU_IDCODE nos endereços candidatos; aceita o 1º DEV_ID conhecido."""
    for addr in _idcode_candidates(cpuid):
        value = _try_read(mem, addr)
        if value is not None and (value & 0xFFF) in STM32_DEV_IDS:
            return value, addr
    return None
