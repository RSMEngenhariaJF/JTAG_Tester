"""StLinkApScanner — leitura de baixo nível via ST-Link, sem sessão de alvo.

Usado para identificar o MCU mesmo quando o núcleo não responde (low-power,
travado, proteção). Não faz descoberta de núcleo nem halt: só lê o DPIDR,
enumera as Access Ports e expõe um leitor de memória por MEM-AP.

Exemplo (STM32H7 — DBGMCU só é visível pela AP2 / APB-D)::

    with StLinkApScanner() as scan:
        dpidr = scan.dpidr
        for ap in scan.mem_aps:
            ap.read_mem32(0xE00E1000)
"""

from __future__ import annotations

from typing import Any

_DP_CTRL_STAT: int = 0x04
_PWRUP_REQ: int = 0x50000000   # CSYSPWRUPREQ | CDBGPWRUPREQ (IHI0031C §2.3.2)
_AP_IDR: int = 0xFC
_AP_IDR_CLASS_MEM: int = 0x8   # IDR[16:13] = 0b1000 → MEM-AP
_MAX_APS: int = 8


class _ApMemReader:
    """Leitor de 32 bits ligado a uma MEM-AP específica."""

    def __init__(self, ap_num: int, mem: Any) -> None:
        self.ap_num = ap_num
        self._mem = mem

    def read_mem32(self, addr: int) -> int:
        return int(self._mem.read32(addr))


class StLinkApScanner:
    """Abre o ST-Link em SWD e enumera as MEM-APs (somente leitura).

    Parâmetros
    ----------
    uid : unique-ID do probe (None → primeiro ST-Link encontrado)
    """

    def __init__(self, uid: str | None = None) -> None:
        try:
            from pyocd.core.helpers import ConnectHelper  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError("pyocd não instalado — execute: pip install pyocd") from exc
        self._ConnectHelper = ConnectHelper
        self._uid = uid
        self._probe: Any = None
        self.dpidr: int = 0
        self.mem_aps: list[_ApMemReader] = []

    def __enter__(self) -> StLinkApScanner:
        from pyocd.core.session import Session  # type: ignore[import-untyped]
        from pyocd.coresight.ap import APv1Address  # type: ignore[import-untyped]
        from pyocd.probe.debug_probe import DebugProbe  # type: ignore[import-untyped]

        probes = self._ConnectHelper.get_all_connected_probes(
            blocking=False, unique_id=self._uid
        ) or []
        if not probes:
            raise RuntimeError("Nenhum ST-Link encontrado — verifique o cabo USB.")
        probe = probes[0]

        # O StlinkProbe exige uma Session associada; ela não é aberta
        # (open() faria a descoberta de núcleo, que é o que queremos evitar).
        Session(probe, target_override="cortex_m")
        probe.open()
        self._probe = probe
        try:
            probe.connect(DebugProbe.Protocol.SWD)
            self.dpidr = int(probe.read_dp(0))
            probe.write_dp(_DP_CTRL_STAT, _PWRUP_REQ)
            for n in range(_MAX_APS):
                try:
                    idr = int(probe.read_ap((n << 24) | _AP_IDR))
                except Exception:
                    break
                if idr == 0:
                    break
                if (idr >> 13) & 0xF == _AP_IDR_CLASS_MEM:
                    mem = probe.get_memory_interface_for_ap(APv1Address(n))
                    self.mem_aps.append(_ApMemReader(n, mem))
        except Exception:
            self._close()
            raise
        return self

    def __exit__(self, *_: object) -> None:
        self._close()

    def _close(self) -> None:
        if self._probe is None:
            return
        try:
            self._probe.disconnect()
        finally:
            self._probe.close()
            self._probe = None
