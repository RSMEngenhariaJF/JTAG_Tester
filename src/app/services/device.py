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

from pathlib import Path
from typing import Any, NamedTuple

from PySide6.QtCore import QObject, Signal

from core.board.config import BoardConfig
from core.pal.access import PeripheralAccessLayer
from core.svd.parser import parse

# Raiz do repositório (src/app/services/ → 3 níveis acima)
_REPO_ROOT = Path(__file__).parents[3]


class ProbeInfo(NamedTuple):
    """Informações de um probe detectado (sem abrir sessão)."""
    description: str   # "STMicroelectronics ST-Link/V2"
    unique_id:   str   # identificador único do probe

    def __str__(self) -> str:
        return self.description


class DeviceService(QObject):
    """Gerencia ciclo de vida da conexão ST-Link e exposição do PAL."""

    probe_connected    = Signal(str)   # descrição do probe (DPIDR incluído)
    probe_disconnected = Signal()
    probe_error        = Signal(str)   # mensagem de erro

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

            adiv5 = StLinkADIv5(target=board.target, mode="halt", uid=uid)
            adiv5._open()
            dpidr = adiv5.init()
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

    @staticmethod
    def list_probes() -> list[ProbeInfo]:
        """Retorna lista de ProbeInfo dos ST-Link conectados (sem abrir sessão).

        Retorna lista vazia se nenhum probe for encontrado ou se pyOCD não
        estiver instalado.
        """
        try:
            from pyocd.core.helpers import ConnectHelper  # type: ignore[import-untyped]

            probes = ConnectHelper.get_all_connected_probes(blocking=False) or []
            return [
                ProbeInfo(
                    description=f"{p.vendor_name} {p.product_name}",
                    unique_id=p.unique_id,
                )
                for p in probes
            ]
        except Exception:
            return []
