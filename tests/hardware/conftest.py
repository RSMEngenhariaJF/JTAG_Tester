"""Fixtures para testes de hardware.

FT2232H:
    pytest tests/hardware/ -m hardware --hw-url ftdi://ftdi:2232h/1

ST-Link (NUCLEO on-board):
    pytest tests/hardware/ -m hardware --stlink

Sem nenhuma das flags, os testes de hardware são pulados automaticamente.
"""

from __future__ import annotations

import pytest

# Garante que o libusb-1.0.dll do libusb_package seja encontrado pelo pyftdi.
# No Windows sem admin, pyftdi.usbtools.UsbTools._load_backend() não encontra a DLL;
# patcheamos o método para retornar o backend via libusb_package.find_library.
try:
    import libusb_package  # type: ignore[import-untyped]
    import pyftdi.usbtools  # type: ignore[import-untyped]
    import usb.backend.libusb1  # type: ignore[import-untyped]

    _be = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
    if _be is not None:
        pyftdi.usbtools.UsbTools._load_backend = staticmethod(lambda: _be)  # type: ignore[assignment]
except Exception:
    pass  # libusb_package não instalado — deixa o sistema resolver


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--hw-url",
        default=None,
        metavar="URL",
        help="URL pyftdi do FT2232H, ex. ftdi://ftdi:2232h/1",
    )
    parser.addoption(
        "--hw-freq",
        default=1_000_000,
        type=float,
        metavar="HZ",
        help="Frequência SWDCLK em Hz (padrão: 1 000 000)",
    )
    parser.addoption(
        "--stlink",
        action="store_true",
        default=False,
        help="Usa ST-Link on-board (NUCLEO) em vez do FT2232H",
    )
    parser.addoption(
        "--stlink-target",
        default="stm32f446retx",
        metavar="TARGET",
        help="Identificador do alvo pyOCD (padrão: stm32f446retx)",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "hardware: testes que requerem hardware real (FT2232H ou ST-Link)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    hw_url = config.getoption("--hw-url")
    stlink = config.getoption("--stlink")
    if hw_url or stlink:
        return  # hardware disponível, não pular

    skip_hw = pytest.mark.skip(
        reason="Hardware não conectado — use --hw-url ou --stlink"
    )
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip_hw)


@pytest.fixture(scope="session")
def hw_url(request: pytest.FixtureRequest) -> str:
    url = request.config.getoption("--hw-url")
    if not url:
        pytest.skip("FT2232H não conectado — use --hw-url")
    return str(url)


@pytest.fixture(scope="session")
def hw_freq(request: pytest.FixtureRequest) -> float:
    return float(request.config.getoption("--hw-freq"))


@pytest.fixture(scope="session")
def ft2232h_transport(hw_url: str, hw_freq: float):  # type: ignore[no-untyped-def]
    """Transport conectado ao FT2232H real. Escopo session para não reabrir a USB."""
    from adapters.ft2232h.transport import FT2232HTransport

    with FT2232HTransport(url=hw_url, frequency=hw_freq) as t:
        yield t


@pytest.fixture(scope="session")
def hw_adiv5(ft2232h_transport):  # type: ignore[no-untyped-def]
    """ADIv5 inicializado sobre o FT2232H real."""
    from core.adiv5.adiv5 import ADIv5
    from core.swd.protocol import SWDProtocol

    proto = SWDProtocol(ft2232h_transport)
    adiv5 = ADIv5(proto)
    dpidr = adiv5.init()
    print(f"\n  DPIDR = 0x{dpidr:08X}")
    return adiv5


# ------------------------------------------------------------------
# Fixtures ST-Link (pyOCD)
# ------------------------------------------------------------------


@pytest.fixture(scope="session")
def stlink_adiv5(request: pytest.FixtureRequest):  # type: ignore[no-untyped-def]
    """StLinkADIv5 conectado ao ST-Link on-board da NUCLEO.

    Requer --stlink na linha de comando.
    """
    if not request.config.getoption("--stlink"):
        pytest.skip("ST-Link não habilitado — use --stlink")

    from adapters.stlink.adiv5 import StLinkADIv5

    target = request.config.getoption("--stlink-target")
    adiv5 = StLinkADIv5(target=target, mode="halt")
    adiv5._open()
    dpidr = adiv5.init()
    print(f"\n  [ST-Link] DPIDR = 0x{dpidr:08X}")
    yield adiv5
    adiv5._close()


@pytest.fixture(scope="session")
def pal_stlink(stlink_adiv5):  # type: ignore[no-untyped-def]
    """PAL sobre ST-Link + SVD do STM32F446."""
    from pathlib import Path

    from core.pal.access import PeripheralAccessLayer
    from core.svd.parser import parse

    svd_path = Path(__file__).parents[2] / "devices" / "stm32f446" / "STM32F446.svd"
    device = parse(svd_path)
    return PeripheralAccessLayer(stlink_adiv5, device)
