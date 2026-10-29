"""Testes de hardware: loopback USART1 e SPI1.

Conexões necessárias (NUCLEO-F446RE, conector CN9):
    USART1: D8 (PA9/TX)  ──►──  D2 (PA10/RX)
    SPI1  : D11 (PA7/MOSI) ──►──  D12 (PA6/MISO)

Execução:
    pytest tests/hardware/test_loopback.py -m hardware --stlink -v -s
"""

from __future__ import annotations

import pytest

from tests_builtin.base import TestStatus
from tests_builtin.spi_loopback import SpiLoopbackTest
from tests_builtin.usart_loopback import UsartLoopbackTest


@pytest.mark.hardware
class TestUsartLoopback:
    def test_usart1_loopback_passes(self, pal_stlink) -> None:
        result = UsartLoopbackTest().run(pal_stlink)
        print(f"\n  {result.name}: {result.status.value} — {result.message}")
        assert result.status == TestStatus.PASS, result.message

    def test_usart1_echo_value_correct(self, pal_stlink) -> None:
        result = UsartLoopbackTest().run(pal_stlink)
        assert result.measured == result.expected

    def test_usart1_second_run_passes(self, pal_stlink) -> None:
        """Garante que o restore de pinos funciona (segundo run deve passar também)."""
        UsartLoopbackTest().run(pal_stlink)
        result = UsartLoopbackTest().run(pal_stlink)
        assert result.status == TestStatus.PASS, result.message


@pytest.mark.hardware
class TestSpiLoopback:
    def test_spi1_loopback_passes(self, pal_stlink) -> None:
        result = SpiLoopbackTest().run(pal_stlink)
        print(f"\n  {result.name}: {result.status.value} — {result.message}")
        assert result.status == TestStatus.PASS, result.message

    def test_spi1_echo_value_correct(self, pal_stlink) -> None:
        result = SpiLoopbackTest().run(pal_stlink)
        assert result.measured == result.expected

    def test_spi1_second_run_passes(self, pal_stlink) -> None:
        """Garante que o restore de pinos funciona (segundo run deve passar também)."""
        SpiLoopbackTest().run(pal_stlink)
        result = SpiLoopbackTest().run(pal_stlink)
        assert result.status == TestStatus.PASS, result.message


@pytest.mark.hardware
class TestLoopbackSuiteComplete:
    def test_both_loopbacks_pass(self, pal_stlink) -> None:
        """Gate: USART1 e SPI1 ambos OK."""
        for cls in [UsartLoopbackTest, SpiLoopbackTest]:
            result = cls().run(pal_stlink)
            print(f"\n  [{result.status.value}] {result.name}: {result.message}")
            assert result.status == TestStatus.PASS, (
                f"{result.name} falhou: {result.message}"
            )
