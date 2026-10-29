"""Registro central de instrumentos — análogo ao set/get_active_board().

Fluxo:
    1. GUI carrega configs salvas: registry.load()
    2. Usuário clica "Conectar": registry.connect("dmm")
    3. Teste chama: get_instrument("dmm") → InstrumentDriver vivo
    4. Ao fechar: registry.disconnect_all(); registry.save()
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from core.instruments.config import InstrumentConfig
    from core.instruments.driver import InstrumentDriver

logger = logging.getLogger("core.instruments.registry")

_DEFAULT_PATH = Path("instruments.json")


class InstrumentRegistry:
    """Singleton que mantém configs e conexões vivas dos instrumentos."""

    _instance: InstrumentRegistry | None = None

    def __init__(self) -> None:
        self._configs:   dict[str, InstrumentConfig]  = {}
        self._drivers:   dict[str, InstrumentDriver]  = {}
        self._listeners: list[Callable[[], None]]     = []

    @classmethod
    def instance(cls) -> InstrumentRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Listeners (para GUI atualizar sem depender de Qt aqui) ──────────

    def add_listener(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in self._listeners:
            try:
                fn()
            except Exception:
                pass

    # ── Gerenciamento de configs ─────────────────────────────────────────

    def add_config(self, config: InstrumentConfig) -> None:
        self._configs[config.name] = config
        self._notify()

    def remove_config(self, name: str) -> None:
        if name in self._drivers:
            try:
                self._drivers.pop(name).disconnect()
            except Exception:
                pass
        self._configs.pop(name, None)
        self._notify()

    def configs(self) -> list[InstrumentConfig]:
        return list(self._configs.values())

    # ── Conexão ─────────────────────────────────────────────────────────

    def connect(self, name: str) -> None:
        config = self._configs.get(name)
        if config is None:
            raise KeyError(f"Instrumento '{name}' não configurado")
        driver = _make_driver(config)
        driver.connect()
        self._drivers[name] = driver
        logger.info("Instrumento conectado: %s @ %s", name, config.address)
        self._notify()

    def disconnect(self, name: str) -> None:
        driver = self._drivers.pop(name, None)
        if driver is not None:
            try:
                driver.disconnect()
            except Exception as exc:
                logger.warning("Erro ao desconectar %s: %s", name, exc)
            logger.info("Instrumento desconectado: %s", name)
        self._notify()

    def connect_all(self) -> list[tuple[str, Exception]]:
        """Conecta todos os instrumentos configurados. Retorna lista de erros."""
        errors: list[tuple[str, Exception]] = []
        for name in list(self._configs):
            if not self.is_connected(name):
                try:
                    self.connect(name)
                except Exception as exc:
                    logger.warning("Falha ao conectar %s: %s", name, exc)
                    errors.append((name, exc))
        return errors

    def disconnect_all(self) -> None:
        for name in list(self._drivers):
            try:
                self.disconnect(name)
            except Exception as exc:
                logger.warning("Falha ao desconectar %s: %s", name, exc)

    # ── Acesso ──────────────────────────────────────────────────────────

    def get(self, name: str) -> InstrumentDriver | None:
        """Retorna o driver conectado ou None."""
        return self._drivers.get(name)

    def is_connected(self, name: str) -> bool:
        drv = self._drivers.get(name)
        return drv is not None and drv.is_connected

    # ── Persistência ────────────────────────────────────────────────────

    def save(self, path: Path = _DEFAULT_PATH) -> None:
        data = [c.to_dict() for c in self._configs.values()]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.debug("Instrumentos salvos em %s", path)

    def load(self, path: Path = _DEFAULT_PATH) -> None:
        if not path.exists():
            return
        from core.instruments.config import InstrumentConfig
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for d in data:
                self.add_config(InstrumentConfig.from_dict(d))
            logger.info("Carregados %d instrumento(s) de %s", len(data), path)
        except Exception as exc:
            logger.warning("Erro ao carregar instruments.json: %s", exc)


# ── API pública (análoga a get_active_board) ────────────────────────────


def get_instrument(name: str) -> InstrumentDriver | None:
    """Retorna o driver conectado pelo nome, ou None se não disponível.

    Uso em testes::

        dmm = get_instrument("dmm")
        if dmm is None:
            return self._skip("DMM não conectado")
        v = float(dmm.query("MEAS:VOLT:DC?"))
    """
    return InstrumentRegistry.instance().get(name)


# ── Factory interna ─────────────────────────────────────────────────────


def _make_driver(config: InstrumentConfig) -> InstrumentDriver:
    from core.instruments.config import DriverType
    if config.driver_type == DriverType.VISA:
        from instruments.drivers.visa_driver import VisaDriver
        return VisaDriver(config)
    if config.driver_type == DriverType.SERIAL:
        from instruments.drivers.serial_driver import SerialDriver
        return SerialDriver(config)
    if config.driver_type == DriverType.SOCKET:
        from instruments.drivers.socket_driver import SocketDriver
        return SocketDriver(config)
    if config.driver_type == DriverType.MOCK:
        from instruments.drivers.mock_driver import MockDriver
        return MockDriver(config)
    raise ValueError(f"DriverType desconhecido: {config.driver_type}")
