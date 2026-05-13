"""Fixtures para testes de hardware — requerem FT2232H conectado.

Para executar:
    pytest tests/hardware/ -m hardware --hw-url ftdi://ftdi:2232h/1

Sem a flag --hw-url, todos os testes de hardware são pulados automaticamente.
"""

from __future__ import annotations

import pytest


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


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "hardware: testes que requerem FT2232H físico conectado",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    hw_url = config.getoption("--hw-url")
    if hw_url:
        return  # hardware disponível, não pular

    skip_hw = pytest.mark.skip(reason="FT2232H não conectado — use --hw-url ftdi://ftdi:2232h/1")
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
