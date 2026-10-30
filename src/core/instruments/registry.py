"""Registro central de instrumentos — análogo ao set/get_active_board().

Fluxo:
    1. GUI carrega configs salvas: registry.load()
    2. Usuário clica "Conectar": registry.connect("dmm")
    3. Teste chama: get_instrument("dmm") → InstrumentDriver vivo
       ou get_oscilloscope("osc") → classe por função (core.instruments.roles)
    4. Relatório: registry.trace_records() → identificação + calibração
    5. Ao fechar: registry.disconnect_all(); registry.save()
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from core.instruments.traceability import (
    CalibrationExpiredError,
    CalibrationStatus,
    InstrumentIdentity,
    TraceRecord,
    calibration_status,
    parse_due,
)

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
        self._identities: dict[str, InstrumentIdentity | None] = {}
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
        self._identities.pop(name, None)
        self._notify()

    def configs(self) -> list[InstrumentConfig]:
        return list(self._configs.values())

    # ── Conexão ─────────────────────────────────────────────────────────

    def connect(self, name: str) -> None:
        config = self._configs.get(name)
        if config is None:
            raise KeyError(f"Instrumento '{name}' não configurado")
        status = self.calibration(name)
        if status == CalibrationStatus.EXPIRED and config.params.get("block_if_expired"):
            raise CalibrationExpiredError(
                f"Calibração de '{name}' vencida em {config.params.get('calibration_due')}"
            )
        driver = _make_driver(config)
        driver.connect()
        self._drivers[name] = driver
        try:
            self._identities[name] = InstrumentIdentity.parse(driver.identify())
        except Exception as exc:
            logger.warning("Sem resposta a *IDN? de %s: %s", name, exc)
            self._identities[name] = None
        logger.info("Instrumento conectado: %s @ %s — %s", name, config.address,
                    self._identities[name] or "identificação indisponível")
        if status in (CalibrationStatus.EXPIRED, CalibrationStatus.DUE_SOON):
            logger.warning("Calibração de %s: %s (%s)", name, status.value,
                           config.params.get("calibration_due"))
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

    def config(self, name: str) -> InstrumentConfig | None:
        return self._configs.get(name)

    # ── Rastreabilidade ─────────────────────────────────────────────────

    def identity(self, name: str) -> InstrumentIdentity | None:
        """Identificação lida por *IDN? na última conexão (None se não houve)."""
        return self._identities.get(name)

    def calibration(self, name: str) -> CalibrationStatus:
        config = self._configs.get(name)
        if config is None:
            return CalibrationStatus.UNKNOWN
        return calibration_status(parse_due(config.params.get("calibration_due")))

    def trace_records(self) -> list[TraceRecord]:
        """Instrumentos conectados nesta sessão, para o relatório."""
        out: list[TraceRecord] = []
        for name in self._identities:
            config = self._configs.get(name)
            if config is None:
                continue
            due = parse_due(config.params.get("calibration_due"))
            out.append(TraceRecord(
                name=name, address=config.address, identity=self._identities[name],
                asset_id=str(config.params.get("asset_id", "")),
                calibration_due=due, status=calibration_status(due),
            ))
        return out

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
