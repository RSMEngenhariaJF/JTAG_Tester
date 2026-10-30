"""Gera devices/<chip>/af.json (pino + sinal → AF) a partir do banco do STM32CubeMX.

O banco do CubeMX (db/mcu) é da ST e fica na instalação de cada máquina; este
script só extrai os números de AF (os mesmos da tabela "Alternate function" do
datasheet) para o mapa que a HAL consulta (src/hal/afmap.py).

Uso:
    python tools/gerar_af.py STM32H753ZITx devices/stm32h753
    python tools/gerar_af.py STM32F446RETx devices/stm32f446 --cubemx "D:/ST/STM32CubeMX"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_CUBEMX = Path("C:/Program Files/STMicroelectronics/STM32Cube/STM32CubeMX")
_NS = {"m": "http://dummy.com"}          # namespace usado nos XML do CubeMX
_AF_RE = re.compile(r"GPIO_AF(\d+)_")


def _strip_ns(root: ET.Element) -> None:
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def mcu_file(db: Path, mcu: str) -> Path:
    """db/mcu/<mcu>.xml; o CubeMX agrupa variantes: STM32F446RETx → STM32F446R(C-E)Tx.xml."""
    exact = db / "mcu" / f"{mcu}.xml"
    if exact.is_file():
        return exact
    for path in (db / "mcu").glob("STM32*.xml"):
        pattern = re.sub(r"\(([^)]*)\)", lambda m: "[" + m.group(1).replace("-", "") + "]",
                         path.stem)
        if re.fullmatch(pattern, mcu, re.IGNORECASE):
            return path
    raise FileNotFoundError(f"{mcu}: MCU não encontrado em {db / 'mcu'}")


def gpio_modes_file(db: Path, mcu: str) -> Path:
    root = ET.parse(mcu_file(db, mcu)).getroot()
    _strip_ns(root)
    for ip in root.iter("IP"):
        if ip.get("Name") == "GPIO":
            return db / "mcu" / "IP" / f"GPIO-{ip.get('Version')}_Modes.xml"
    raise LookupError(f"{mcu}: IP GPIO não encontrado no banco do CubeMX")


def extract(modes_file: Path) -> dict[str, dict[str, int]]:
    root = ET.parse(modes_file).getroot()
    _strip_ns(root)
    pins: dict[str, dict[str, int]] = {}
    for gp in root.iter("GPIO_Pin"):
        name = re.match(r"P[A-K]\d+", gp.get("Name", ""))
        if not name:
            continue
        for sig in gp.iter("PinSignal"):
            for val in sig.iter("PossibleValue"):
                m = _AF_RE.match(val.text or "")
                if m:
                    pins.setdefault(name.group(0), {})[sig.get("Name")] = int(m.group(1))
                    break
    return pins


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mcu", help="nome do MCU no CubeMX (Mcu.UserName do .ioc), ex. STM32H753ZITx")
    ap.add_argument("saida", type=Path, help="pasta do dispositivo, ex. devices/stm32h753")
    ap.add_argument("--cubemx", type=Path, default=DEFAULT_CUBEMX,
                    help="pasta de instalação do STM32CubeMX")
    a = ap.parse_args(argv)
    modes = gpio_modes_file(a.cubemx / "db", a.mcu)
    pins = extract(modes)
    if not pins:
        print(f"Nenhuma AF encontrada em {modes}", file=sys.stderr)
        return 1
    a.saida.mkdir(parents=True, exist_ok=True)
    out = a.saida / "af.json"
    out.write_text(json.dumps({"mcu": a.mcu, "origem": modes.name, "pins": pins},
                              indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"{out}: {len(pins)} pinos, {sum(map(len, pins.values()))} sinais com AF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
