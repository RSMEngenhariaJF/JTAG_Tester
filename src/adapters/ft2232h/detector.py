"""Detector de dispositivos FT2232H conectados via USB.

Uso rápido:
    python -m adapters.ft2232h.detector
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FT2232HDevice:
    url: str
    description: str
    serial: str


def list_devices() -> list[FT2232HDevice]:
    """Retorna lista de FT2232H encontrados. Retorna [] se pyftdi não instalado."""
    try:
        from pyftdi.usbtools import UsbTools
    except ImportError:
        return []

    devices: list[FT2232HDevice] = []
    try:
        # Enumera todos os dispositivos FTDI com PID 0x6010 (FT2232H)
        raw = UsbTools.find_all([(0x0403, 0x6010)])
        for vid, pid, _bus, _addr, serial, _idx, desc in raw:
            url = f"ftdi://0x{vid:04x}:0x{pid:04x}:{serial}/1"
            devices.append(FT2232HDevice(url=url, description=desc, serial=serial))
    except Exception:
        pass
    return devices


def print_devices() -> None:
    devs = list_devices()
    if not devs:
        print("Nenhum FT2232H encontrado (verifique driver libusb e conexão USB).")
        return
    for i, d in enumerate(devs, 1):
        print(f"  [{i}] {d.description!r}  serial={d.serial!r}  url={d.url}")


if __name__ == "__main__":
    print("FT2232H detectados:")
    print_devices()
