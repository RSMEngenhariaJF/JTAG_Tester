"""Testes unitários do InstrumentRegistry com MockDriver (sem hardware real)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.instruments.config import DriverType, InstrumentConfig
from core.instruments.registry import InstrumentRegistry, get_instrument
from instruments.drivers.mock_driver import MockDriver


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fresh_registry():
    """Reseta o singleton antes de cada teste para evitar contaminação."""
    InstrumentRegistry._instance = None
    yield
    registry = InstrumentRegistry.instance()
    registry.disconnect_all()
    InstrumentRegistry._instance = None


def _mock_config(name: str = "dmm", **params) -> InstrumentConfig:
    return InstrumentConfig(
        name        = name,
        driver_type = DriverType.MOCK,
        address     = "mock://local",
        description = f"Simulado {name}",
        params      = params,
    )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_instance_is_same_object(self) -> None:
        a = InstrumentRegistry.instance()
        b = InstrumentRegistry.instance()
        assert a is b

    def test_fresh_registry_has_no_configs(self) -> None:
        assert InstrumentRegistry.instance().configs() == []


# ---------------------------------------------------------------------------
# add / remove config
# ---------------------------------------------------------------------------


class TestConfigManagement:
    def test_add_config_appears_in_list(self) -> None:
        reg = InstrumentRegistry.instance()
        cfg = _mock_config("dmm")
        reg.add_config(cfg)
        assert cfg in reg.configs()

    def test_add_duplicate_overwrites(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        reg.add_config(_mock_config("dmm"))
        assert len([c for c in reg.configs() if c.name == "dmm"]) == 1

    def test_remove_config_not_in_list(self) -> None:
        reg = InstrumentRegistry.instance()
        cfg = _mock_config("dmm")
        reg.add_config(cfg)
        reg.remove_config("dmm")
        assert cfg not in reg.configs()

    def test_remove_nonexistent_does_not_raise(self) -> None:
        InstrumentRegistry.instance().remove_config("nao_existe")

    def test_multiple_configs(self) -> None:
        reg = InstrumentRegistry.instance()
        for name in ("dmm", "osc", "fonte"):
            reg.add_config(_mock_config(name))
        names = [c.name for c in reg.configs()]
        assert set(names) == {"dmm", "osc", "fonte"}


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------


class TestConnection:
    def test_connect_sets_is_connected(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        reg.connect("dmm")
        assert reg.is_connected("dmm")

    def test_disconnect_clears_is_connected(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        reg.connect("dmm")
        reg.disconnect("dmm")
        assert not reg.is_connected("dmm")

    def test_connect_unknown_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            InstrumentRegistry.instance().connect("nao_existe")

    def test_driver_accessible_after_connect(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        reg.connect("dmm")
        drv = reg.get("dmm")
        assert drv is not None
        assert isinstance(drv, MockDriver)

    def test_driver_none_before_connect(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        assert reg.get("dmm") is None

    def test_driver_none_after_disconnect(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        reg.connect("dmm")
        reg.disconnect("dmm")
        assert reg.get("dmm") is None


# ---------------------------------------------------------------------------
# connect_all / disconnect_all
# ---------------------------------------------------------------------------


class TestBulkOperations:
    def test_connect_all_connects_all_configs(self) -> None:
        reg = InstrumentRegistry.instance()
        for name in ("dmm", "osc"):
            reg.add_config(_mock_config(name))
        errors = reg.connect_all()
        assert errors == []
        assert reg.is_connected("dmm")
        assert reg.is_connected("osc")

    def test_connect_all_returns_errors_list(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(
            InstrumentConfig("bad", DriverType.MOCK, "addr",
                             params={"__force_connect_error": True})
        )
        # MockDriver não usa __force_connect_error; connect_all deve passar
        errors = reg.connect_all()
        assert isinstance(errors, list)

    def test_disconnect_all_disconnects_everything(self) -> None:
        reg = InstrumentRegistry.instance()
        for name in ("dmm", "osc", "fonte"):
            reg.add_config(_mock_config(name))
        reg.connect_all()
        reg.disconnect_all()
        for name in ("dmm", "osc", "fonte"):
            assert not reg.is_connected(name)


# ---------------------------------------------------------------------------
# get_instrument() — API de alto nível
# ---------------------------------------------------------------------------


class TestGetInstrument:
    def test_returns_driver_when_connected(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        reg.connect("dmm")
        drv = get_instrument("dmm")
        assert drv is not None

    def test_returns_none_when_not_connected(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        assert get_instrument("dmm") is None

    def test_returns_none_when_not_configured(self) -> None:
        assert get_instrument("nao_existe") is None

    def test_query_via_get_instrument(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm", responses={"MEAS:VOLT:DC?": "3.300"}))
        reg.connect("dmm")
        drv = get_instrument("dmm")
        assert drv is not None
        assert drv.query("MEAS:VOLT:DC?") == "3.300"


# ---------------------------------------------------------------------------
# MockDriver — comportamento interno
# ---------------------------------------------------------------------------


class TestMockDriver:
    def test_default_response_is_zero(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        reg.connect("dmm")
        drv = reg.get("dmm")
        assert drv.query("QUALQUER?") == "0.000"

    def test_configured_response_returned(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm", responses={"*IDN?": "RIGOL,DM3058,1.0"}))
        reg.connect("dmm")
        drv = reg.get("dmm")
        assert drv.query("*IDN?") == "RIGOL,DM3058,1.0"

    def test_log_records_queries(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        reg.connect("dmm")
        drv: MockDriver = reg.get("dmm")
        drv.query("MEAS:VOLT?")
        drv.query("MEAS:CURR?")
        cmds = [entry[0] for entry in drv.log]
        assert cmds == ["MEAS:VOLT?", "MEAS:CURR?"]

    def test_set_response_overrides(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        reg.connect("dmm")
        drv: MockDriver = reg.get("dmm")
        drv.set_response("VOLT?", "5.000")
        assert drv.query("VOLT?") == "5.000"


# ---------------------------------------------------------------------------
# Listeners (GUI callbacks)
# ---------------------------------------------------------------------------


class TestListeners:
    def test_listener_called_on_add_config(self) -> None:
        reg = InstrumentRegistry.instance()
        calls: list[int] = []
        reg.add_listener(lambda: calls.append(1))
        reg.add_config(_mock_config("dmm"))
        assert len(calls) == 1

    def test_listener_called_on_connect(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        calls: list[int] = []
        reg.add_listener(lambda: calls.append(1))
        reg.connect("dmm")
        assert len(calls) == 1

    def test_listener_called_on_disconnect(self) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        reg.connect("dmm")
        calls: list[int] = []
        reg.add_listener(lambda: calls.append(1))
        reg.disconnect("dmm")
        assert len(calls) == 1

    def test_faulty_listener_does_not_crash(self) -> None:
        reg = InstrumentRegistry.instance()

        def bad():
            raise RuntimeError("falhou")

        reg.add_listener(bad)
        reg.add_config(_mock_config("dmm"))  # deve não lançar


# ---------------------------------------------------------------------------
# Persistência JSON
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_save_creates_json_file(self, tmp_path: Path) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        dest = tmp_path / "instr.json"
        reg.save(dest)
        assert dest.exists()

    def test_saved_json_is_valid(self, tmp_path: Path) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        dest = tmp_path / "instr.json"
        reg.save(dest)
        data = json.loads(dest.read_text())
        assert isinstance(data, list)
        assert data[0]["name"] == "dmm"

    def test_load_restores_configs(self, tmp_path: Path) -> None:
        reg = InstrumentRegistry.instance()
        reg.add_config(_mock_config("dmm"))
        reg.add_config(_mock_config("osc"))
        dest = tmp_path / "instr.json"
        reg.save(dest)

        # Novo registry (simula reinício)
        InstrumentRegistry._instance = None
        reg2 = InstrumentRegistry.instance()
        reg2.load(dest)
        names = {c.name for c in reg2.configs()}
        assert names == {"dmm", "osc"}

    def test_load_nonexistent_does_not_raise(self, tmp_path: Path) -> None:
        InstrumentRegistry.instance().load(tmp_path / "nao_existe.json")

    def test_round_trip_preserves_params(self, tmp_path: Path) -> None:
        reg = InstrumentRegistry.instance()
        cfg = InstrumentConfig(
            name        = "dmm",
            driver_type = DriverType.MOCK,
            address     = "mock://x",
            description = "Test",
            params      = {"baudrate": 9600, "timeout": 2.5},
        )
        reg.add_config(cfg)
        dest = tmp_path / "i.json"
        reg.save(dest)

        InstrumentRegistry._instance = None
        reg2 = InstrumentRegistry.instance()
        reg2.load(dest)
        loaded = reg2.configs()[0]
        assert loaded.params == {"baudrate": 9600, "timeout": 2.5}
