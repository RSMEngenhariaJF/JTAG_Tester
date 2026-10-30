"""Conexão do ST-Link a STM32H7 com firmware em baixo consumo (adapters/stlink/adiv5.py).

O firmware que dorme (WFI/stop) desliga o clock do núcleo e o AP0 para de
responder. O adaptador liga o debug em baixo consumo pelo AP2 antes da sessão,
abre a sessão em 'attach' e para o núcleo depois. Aqui a sonda e a sessão do
pyOCD são simuladas.

Execução:
    pytest tests/unit/test_stlink_h7_connect.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from adapters.stlink import adiv5 as mod


class FakeLink:
    def __init__(self, cr: int) -> None:
        self.mem = {mod._H7_DBGMCU_CR_AP2: cr}
        self.writes: list[tuple[int, int, int]] = []

    def open_ap(self, ap: int) -> None:
        pass

    def read_mem32(self, addr, size, ap, csw):
        assert ap == 2
        return list(self.mem[addr].to_bytes(4, "little"))

    def write_mem32(self, addr, data, ap, csw):
        value = int.from_bytes(bytes(data), "little")
        self.writes.append((addr, value, ap))
        self.mem[addr] = value


def _session(cr: int):
    probe = MagicMock()
    probe._link = FakeLink(cr)
    target = MagicMock()
    session = MagicMock()
    session.probe, session.target = probe, target
    return session


@pytest.fixture
def helper(monkeypatch):
    calls: dict = {}

    def fake(**kwargs):
        calls.update(kwargs)
        return calls["session"]

    return calls, SimpleNamespace(session_with_chosen_probe=fake)


@pytest.mark.parametrize("mode", ["halt", "under-reset"])
def test_h7_sets_dbgmcu_via_ap2_attaches_and_halts(helper, mode) -> None:
    calls, fake_helper = helper
    calls["session"] = s = _session(0x0070003C)          # sono sem debug (lido na placa CT)
    a = mod.StLinkADIv5(target="stm32h743xx", mode=mode)
    a._ConnectHelper = fake_helper
    a._open()
    assert calls["connect_mode"] == "attach"              # sem o reset do pyOCD
    assert s.probe._link.writes == [(mod._H7_DBGMCU_CR_AP2, 0x0070003F, 2)]
    s.probe.disconnect.assert_called_once()
    s.target.halt.assert_called_once()


def test_h7_attach_mode_does_not_halt_and_skips_write_if_set(helper) -> None:
    calls, fake_helper = helper
    calls["session"] = s = _session(0x0070003F)
    a = mod.StLinkADIv5(target="stm32h743xx", mode="attach")
    a._ConnectHelper = fake_helper
    a._open()
    assert s.probe._link.writes == []
    s.target.halt.assert_not_called()


def test_other_families_keep_pyocd_mode(helper) -> None:
    calls, fake_helper = helper
    calls["session"] = s = _session(0)
    a = mod.StLinkADIv5(target="stm32f446retx", mode="halt")
    a._ConnectHelper = fake_helper
    a._open()
    assert calls["connect_mode"] == "halt"
    s.probe.open.assert_not_called()
