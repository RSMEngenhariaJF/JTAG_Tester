"""DeviceService — gerencia a conexão com o probe ST-Link.

A partir do Sprint 16 o serviço recebe um ``BoardConfig`` em ``connect()``,
que determina qual SVD carregar e qual target string passar ao pyOCD.
Isso permite trocar de placa sem alterar nenhum código de teste.

Ciclo de vida::

    svc = DeviceService()
    svc.probe_connected.connect(on_connected)
    svc.probe_error.connect(on_error)
    svc.connect(board)              # abre sessão pyOCD
    pal = svc.pal                   # PeripheralAccessLayer pronto
    svc.disconnect()                # fecha sessão
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, NamedTuple

from PySide6.QtCore import QObject, Signal

from core.board.config import BoardConfig
from core.pal.access import PeripheralAccessLayer
from core.svd.parser import parse
from core.target import McuInfo, identify

# Raiz do repositório (src/app/services/ → 3 níveis acima)
_REPO_ROOT = Path(__file__).parents[3]
logger = logging.getLogger("app.services.device")


PROBE_STLINK  = "stlink"
PROBE_FT2232H = "ft2232h"


class ProbeInfo(NamedTuple):
    """Informações de um probe detectado (sem abrir sessão)."""
    description: str   # "STMicroelectronics ST-Link/V2"
    unique_id:   str   # identificador único do probe (URL pyftdi no FT2232H)
    kind:        str = PROBE_STLINK

    def __str__(self) -> str:
        return self.description


class DeviceService(QObject):
    """Gerencia ciclo de vida da conexão ST-Link e exposição do PAL."""

    probe_connected    = Signal(str)   # descrição do probe (DPIDR incluído)
    probe_disconnected = Signal()
    probe_error        = Signal(str)   # mensagem de erro
    mcu_identified     = Signal(object)  # McuInfo

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._adiv5: Any = None
        self._pal: PeripheralAccessLayer | None = None

    # ------------------------------------------------------------------
    # Estado público
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._adiv5 is not None

    @property
    def pal(self) -> PeripheralAccessLayer | None:
        return self._pal

    # ------------------------------------------------------------------
    # Ações
    # ------------------------------------------------------------------

    def connect(
        self,
        board: BoardConfig,
        uid: str | None = None,
    ) -> None:
        """Abre sessão ST-Link e inicializa o PAL para a placa fornecida.

        É idempotente: se já conectado, retorna sem fazer nada.
        Emite ``probe_connected(descricao)`` em sucesso ou ``probe_error(msg)``
        em falha.

        Parâmetros
        ----------
        board : configuração da placa-alvo (determina SVD e target pyOCD)
        uid   : unique_id do probe; None → usa o primeiro ST-Link encontrado
        """
        if self._adiv5 is not None:
            return

        try:
            from adapters.stlink.adiv5 import StLinkADIv5  # import tardio — pyOCD opcional

            svd_path = _REPO_ROOT / board.svd_path
            svd = parse(svd_path)

            target = board.pyocd_target or board.target
            adiv5 = StLinkADIv5(target=target, mode=board.connect_mode, uid=uid)
            # No H7 a descoberta da ROM table às vezes falha logo após a sessão
            # anterior ("Invalid coresight component"); uma 2ª tentativa resolve.
            attempts = 3 if board.connect_mode == "under-reset" else 1
            for attempt in range(1, attempts + 1):
                try:
                    adiv5._open()
                    break
                except Exception as exc:
                    adiv5._close()
                    if attempt == attempts:
                        raise
                    logger.warning("Conexão falhou (tentativa %d/%d): %s — repetindo",
                                   attempt, attempts, exc)
                    time.sleep(0.3)
            dpidr = adiv5.init()
            if board.resume_after_connect and adiv5.is_halted():
                adiv5.resume()
            self._adiv5 = adiv5
            self._pal = PeripheralAccessLayer(adiv5, svd)
            self.probe_connected.emit(
                f"ST-Link  DPIDR=0x{dpidr:08X}  alvo={board.target}"
            )
        except Exception as exc:
            self.probe_error.emit(str(exc))

    def disconnect(self) -> None:
        """Fecha a sessão com o probe e limpa o estado.

        É idempotente: se não conectado, não faz nada.
        Sempre emite ``probe_disconnected`` ao final.
        """
        if self._adiv5 is None:
            return
        try:
            self._adiv5._close()
        finally:
            self._adiv5 = None
            self._pal = None
            self.probe_disconnected.emit()

    def identify(self, probe: ProbeInfo | None = None) -> McuInfo | None:
        """Identifica o microcontrolador ligado ao probe (sem halt).

        Se já houver sessão aberta, usa-a. Caso contrário abre uma sessão
        temporária genérica — não depende da placa do projeto — e a fecha
        ao final. Emite ``mcu_identified(McuInfo)`` ou ``probe_error(msg)``.

        Parâmetros
        ----------
        probe : probe a usar; None → primeiro ST-Link encontrado
        """
        try:
            if self._adiv5 is not None:
                info = identify(self._adiv5, self._adiv5.init())
            elif probe is not None and probe.kind == PROBE_FT2232H:
                info = self._identify_ft2232h(probe.unique_id)
            else:
                info = self._identify_stlink(probe.unique_id if probe else None)
        except Exception as exc:
            self.probe_error.emit(f"Falha ao identificar MCU: {exc}")
            return None
        self.mcu_identified.emit(info)
        return info

    @staticmethod
    def _identify_stlink(uid: str | None) -> McuInfo:
        from adapters.stlink.probe_reader import StLinkApScanner  # import tardio — pyOCD

        # Leitura direta das MEM-APs: funciona mesmo com o núcleo inacessível
        with StLinkApScanner(uid=uid) as scan:
            return identify(scan.mem_aps, scan.dpidr)

    @staticmethod
    def _identify_ft2232h(url: str) -> McuInfo:
        from adapters.ft2232h import FT2232HTransport  # import tardio — pyftdi opcional
        from core.adiv5 import ADIv5
        from core.swd.protocol import SWDProtocol

        with FT2232HTransport(url=url) as transport:
            adiv5 = ADIv5(SWDProtocol(transport))
            return identify(adiv5, adiv5.init())

    @staticmethod
    def list_probes() -> list[ProbeInfo]:
        """Retorna ST-Link e FT2232H conectados (sem abrir sessão).

        Retorna lista vazia se nenhum probe for encontrado ou se pyOCD /
        pyftdi não estiverem instalados.
        """
        probes: list[ProbeInfo] = []
        try:
            from pyocd.core.helpers import ConnectHelper  # type: ignore[import-untyped]

            stlinks = ConnectHelper.get_all_connected_probes(blocking=False) or []
            probes += [
                ProbeInfo(
                    description=f"{p.vendor_name} {p.product_name}",
                    unique_id=p.unique_id,
                )
                for p in stlinks
            ]
        except Exception:
            pass

        try:
            from adapters.ft2232h.detector import list_devices

            probes += [
                ProbeInfo(
                    description=f"FT2232H {d.description} ({d.serial})",
                    unique_id=d.url,
                    kind=PROBE_FT2232H,
                )
                for d in list_devices()
            ]
        except Exception:
            pass
        return probes
