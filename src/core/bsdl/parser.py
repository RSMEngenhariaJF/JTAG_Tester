"""Parser BSDL (Boundary Scan Description Language) — IEEE Std 1149.1.

Extrai via regex as seções relevantes do BSDL sem implementar um parser VHDL
completo, pois o BSDL é um subconjunto fixo e bem estruturado de VHDL.

Limitações conhecidas (fora do escopo):
  - Não suporta `derivedFrom` nem herança entre entidades BSDL
  - Não suporta `register_mnemonics` / enumerações de campos
  - PIN_MAP com múltiplos pacotes (generic) — usa o primeiro encontrado
"""

from __future__ import annotations

import re
from pathlib import Path

from core.bsdl.model import BsdlCell, BsdlDevice, BsdlInstruction


def parse(path: str | Path) -> BsdlDevice:
    """Lê um arquivo BSDL e retorna um BsdlDevice."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    flat = _flatten(text)
    return _build_device(flat)


# ---------------------------------------------------------------------------
# Pré-processamento
# ---------------------------------------------------------------------------


def _flatten(text: str) -> str:
    """Remove comentários VHDL (--), une linhas e junta strings com &."""
    lines = []
    for line in text.splitlines():
        idx = line.find("--")
        lines.append(line[:idx] if idx >= 0 else line)
    joined = " ".join(lines)
    joined = re.sub(r"\s+", " ", joined)
    # "abc" & "def"  →  "abcdef"
    joined = re.sub(r'"\s*&\s*"', "", joined)
    return joined


# ---------------------------------------------------------------------------
# Extratores de atributos
# ---------------------------------------------------------------------------


def _attr_str(flat: str, name: str) -> str | None:
    """Extrai o valor string de `attribute NAME of X : entity is "VALUE";`."""
    pat = rf'attribute\s+{re.escape(name)}\s+of\s+\w+\s*:\s*entity\s+is\s+"([^"]+)"'
    m = re.search(pat, flat, re.IGNORECASE)
    return m.group(1) if m else None


def _attr_int(flat: str, name: str) -> int | None:
    """Extrai o valor inteiro de `attribute NAME of X : entity is N;`."""
    pat = rf'attribute\s+{re.escape(name)}\s+of\s+\w+\s*:\s*entity\s+is\s+(\d+)'
    m = re.search(pat, flat, re.IGNORECASE)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Parsers de seções
# ---------------------------------------------------------------------------


def _parse_entity_name(flat: str) -> str:
    m = re.search(r'\bentity\s+(\w+)\s+is\b', flat, re.IGNORECASE)
    return m.group(1) if m else ""


def _parse_instructions(opcode_str: str) -> list[BsdlInstruction]:
    """Parseia 'NAME (bits), NAME (bits), ...' em lista de BsdlInstruction."""
    instrs: list[BsdlInstruction] = []
    for m in re.finditer(r'(\w+)\s*\(\s*([01X]+)\s*\)', opcode_str):
        instrs.append(BsdlInstruction(name=m.group(1).upper(), opcode=m.group(2)))
    return instrs


# Regex para uma célula BSR:
# N  (BC_type, port, function, safe [, ccell, disval, rslt])
_CELL_RE = re.compile(
    r'(\d+)\s*\(\s*'              # número da célula
    r'(\w+)\s*,\s*'               # tipo (BC_0, BC_1, BC_4...)
    r'([\w*]+)\s*,\s*'            # porta ou *
    r'(\w+)\s*,\s*'               # função
    r'([01X])\s*'                 # safe value
    r'(?:,\s*(\d+)\s*,\s*([01])\s*,\s*([01Z]))?\s*\)',  # ccell, disval, rslt (opcional)
    re.IGNORECASE,
)


def _parse_cells(boundary_str: str) -> list[BsdlCell]:
    cells: list[BsdlCell] = []
    for m in _CELL_RE.finditer(boundary_str):
        cells.append(BsdlCell(
            num=int(m.group(1)),
            cell_type=m.group(2),
            port=m.group(3),
            function=m.group(4).lower(),
            safe=m.group(5).upper(),
            ccell=int(m.group(6)) if m.group(6) is not None else None,
            disval=int(m.group(7)) if m.group(7) is not None else None,
            rslt=m.group(8).upper() if m.group(8) is not None else None,
        ))
    # Ordena do número mais alto (próximo ao TDI) para o mais baixo (próximo ao TDO)
    cells.sort(key=lambda c: c.num, reverse=True)
    return cells


def _parse_pin_map(flat: str) -> dict[str, list[str]]:
    """Extrai o mapa porta → pino(s) da primeira constante PIN_MAP_STRING."""
    m = re.search(
        r'constant\s+\w+\s*:\s*PIN_MAP_STRING\s*:=\s*"([^"]+)"',
        flat,
        re.IGNORECASE,
    )
    if not m:
        return {}

    result: dict[str, list[str]] = {}
    for item in re.finditer(r'(\w+)\s*:\s*(\([^)]+\)|\d+)', m.group(1)):
        port = item.group(1).upper()
        raw = item.group(2).strip()
        if raw.startswith("("):
            pins = [p.strip() for p in raw.strip("()").split(",")]
        else:
            pins = [raw]
        result[port] = pins
    return result


# ---------------------------------------------------------------------------
# Construção do dispositivo
# ---------------------------------------------------------------------------


def _build_device(flat: str) -> BsdlDevice:
    entity_name = _parse_entity_name(flat)
    ir_length = _attr_int(flat, "INSTRUCTION_LENGTH") or 0

    opcode_str = _attr_str(flat, "INSTRUCTION_OPCODE") or ""
    instructions = tuple(_parse_instructions(opcode_str))

    idcode_raw = _attr_str(flat, "IDCODE_REGISTER") or ""
    # Remove espaços dentro do padrão (o flatten pode ter deixado)
    idcode_pattern = re.sub(r"\s+", "", idcode_raw).upper()

    boundary_length = _attr_int(flat, "BOUNDARY_LENGTH") or 0

    boundary_str = _attr_str(flat, "BOUNDARY_REGISTER") or ""
    cells = tuple(_parse_cells(boundary_str))

    pin_map = _parse_pin_map(flat)

    return BsdlDevice(
        entity_name=entity_name,
        ir_length=ir_length,
        instructions=instructions,
        idcode_pattern=idcode_pattern,
        boundary_length=boundary_length,
        cells=cells,
        pin_map=pin_map,
    )
