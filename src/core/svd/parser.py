"""Parser CMSIS-SVD — converte XML em SvdDevice.

Suporta:
  - Herança de atributos device → peripheral → register (size, access, resetValue)
  - derivedFrom em periféricos (copia registradores do periférico base)
  - Fields com bitOffset + bitWidth

Não suporta (fora do escopo desta sprint):
  - dim / dimIndex / dimIncrement (arrays de registradores)
  - derivedFrom em registradores ou campos
  - enumeratedValues expandidos

Referência: CMSIS-SVD Schema 1.1
"""

from __future__ import annotations

from pathlib import Path
from xml.etree.ElementTree import Element, parse as xml_parse

from core.svd.model import SvdDevice, SvdField, SvdPeripheral, SvdRegister


def parse(path: str | Path) -> SvdDevice:
    """Faz o parse de um arquivo CMSIS-SVD e retorna um SvdDevice."""
    tree = xml_parse(str(path))
    root = tree.getroot()
    return _parse_device(root)


# ---------------------------------------------------------------------------
# Internos
# ---------------------------------------------------------------------------


def _text(el: Element, tag: str, default: str = "") -> str:
    child = el.find(tag)
    return child.text.strip() if child is not None and child.text else default


def _int(el: Element, tag: str, default: int = 0) -> int:
    raw = _text(el, tag)
    if not raw:
        return default
    # SVD usa 0x... (hex), 0b... (bin) ou decimal com possíveis zeros à esquerda
    lo = raw.lower()
    if lo.startswith("0x"):
        return int(raw, 16)
    if lo.startswith("0b"):
        return int(raw, 2)
    return int(raw, 10)


def _parse_device(root: Element) -> SvdDevice:
    # Defaults globais que se propagam para periféricos e registradores
    dev_defaults = _DeviceDefaults(
        size=_int(root, "size", 32),
        access=_text(root, "access", "read-write"),
        reset_value=_int(root, "resetValue", 0),
    )

    # --- 1ª passagem: parse de periféricos sem derivedFrom ---
    raw_peripherals: dict[str, Element] = {}
    parsed_by_name: dict[str, SvdPeripheral] = {}
    deferred: list[Element] = []

    periph_els = root.find("peripherals")
    if periph_els is None:
        periph_els_list: list[Element] = []
    else:
        periph_els_list = list(periph_els)

    for p_el in periph_els_list:
        name = _text(p_el, "name")
        raw_peripherals[name] = p_el
        if p_el.get("derivedFrom") is None:
            parsed_by_name[name] = _parse_peripheral(p_el, dev_defaults)
        else:
            deferred.append(p_el)

    # --- 2ª passagem: resolve derivedFrom ---
    # Itera até não haver mais periféricos a resolver (suporta cadeia de herança)
    max_iter = len(deferred) + 1
    for _ in range(max_iter):
        still_deferred = []
        for p_el in deferred:
            base_name = p_el.get("derivedFrom", "")
            if base_name in parsed_by_name:
                parsed_by_name[_text(p_el, "name")] = _parse_derived_peripheral(
                    p_el, parsed_by_name[base_name]
                )
            else:
                still_deferred.append(p_el)
        deferred = still_deferred
        if not deferred:
            break

    if deferred:
        unresolved = [_text(e, "name") for e in deferred]
        raise ValueError(f"derivedFrom não resolvido para: {unresolved}")

    # Mantém a ordem original do arquivo SVD
    ordered = [parsed_by_name[_text(e, "name")] for e in periph_els_list]

    return SvdDevice(
        name=_text(root, "name"),
        version=_text(root, "version"),
        description=_text(root, "description"),
        address_unit_bits=_int(root, "addressUnitBits", 8),
        width=_int(root, "width", 32),
        peripherals=tuple(ordered),
    )


class _DeviceDefaults:
    __slots__ = ("size", "access", "reset_value")

    def __init__(self, size: int, access: str, reset_value: int) -> None:
        self.size = size
        self.access = access
        self.reset_value = reset_value


def _parse_peripheral(p_el: Element, dev: _DeviceDefaults) -> SvdPeripheral:
    p_size = _int(p_el, "size", dev.size)
    p_access = _text(p_el, "access", dev.access)
    p_reset = _int(p_el, "resetValue", dev.reset_value)

    regs: list[SvdRegister] = []
    regs_el = p_el.find("registers")
    if regs_el is not None:
        for r_el in regs_el:
            if r_el.tag != "register":
                continue
            regs.append(_parse_register(r_el, p_size, p_access, p_reset))

    return SvdPeripheral(
        name=_text(p_el, "name"),
        description=_text(p_el, "description"),
        base_address=_int(p_el, "baseAddress"),
        group_name=_text(p_el, "groupName"),
        registers=tuple(regs),
    )


def _parse_derived_peripheral(p_el: Element, base: SvdPeripheral) -> SvdPeripheral:
    """Cria um periférico que herda os registradores do `base`, sobrepondo name e baseAddress."""
    return SvdPeripheral(
        name=_text(p_el, "name", base.name),
        description=_text(p_el, "description") or base.description,
        base_address=_int(p_el, "baseAddress", base.base_address),
        group_name=_text(p_el, "groupName") or base.group_name,
        registers=base.registers,  # herda todos os registradores
    )


def _parse_register(
    r_el: Element,
    p_size: int,
    p_access: str,
    p_reset: int,
) -> SvdRegister:
    reg_access = _text(r_el, "access", p_access)

    fields: list[SvdField] = []
    fields_el = r_el.find("fields")
    if fields_el is not None:
        for f_el in fields_el:
            if f_el.tag != "field":
                continue
            fields.append(_parse_field(f_el, reg_access))

    return SvdRegister(
        name=_text(r_el, "name"),
        description=_text(r_el, "description"),
        address_offset=_int(r_el, "addressOffset"),
        size=_int(r_el, "size", p_size),
        access=reg_access,
        reset_value=_int(r_el, "resetValue", p_reset),
        fields=tuple(fields),
    )


def _parse_field(f_el: Element, reg_access: str) -> SvdField:
    # bitOffset + bitWidth é o formato deste SVD (alternativa: bitRange "[n:m]")
    bit_offset = _int(f_el, "bitOffset")
    bit_width = _int(f_el, "bitWidth", 1)

    # fallback para <bitRange>[msb:lsb]</bitRange>
    bit_range_el = f_el.find("bitRange")
    if bit_range_el is not None and bit_range_el.text:
        raw = bit_range_el.text.strip().strip("[]")
        msb_s, lsb_s = raw.split(":")
        msb, lsb = int(msb_s), int(lsb_s)
        bit_offset = lsb
        bit_width = msb - lsb + 1

    return SvdField(
        name=_text(f_el, "name"),
        description=_text(f_el, "description"),
        bit_offset=bit_offset,
        bit_width=bit_width,
        access=_text(f_el, "access", reg_access),
    )
