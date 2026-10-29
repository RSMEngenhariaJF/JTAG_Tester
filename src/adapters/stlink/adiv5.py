"""StLinkADIv5 — adapter ADIv5 usando ST-Link via pyOCD.

Drop-in replacement para ADIv5(FT2232HTransport(...)) durante desenvolvimento.
A interface pública é idêntica à classe ADIv5: init(), halt(), resume(),
read_mem32(), write_mem32(), read_core_register(), write_core_register().

O pyOCD cuida de toda a inicialização SWD (power-up, jtag_to_swd, select AP),
liberando o desenvolvimento das camadas superiores sem depender do FT2232H.

Pré-requisito:
    pip install pyocd

Uso típico:
    with StLinkADIv5(target='stm32f446re') as adiv5:
        dpidr = adiv5.init()
        adiv5.halt()
        pc = adiv5.read_core_register(15)  # REG_PC = 15
"""

from __future__ import annotations

from typing import Any


class StLinkADIv5:
    """ADIv5 via ST-Link probe (pyOCD) — mesma interface de ADIv5.

    Parâmetros
    ----------
    target : identificador do alvo pyOCD, ex. 'stm32f446re'
    mode   : modo de conexão — 'halt' | 'attach' | 'under-reset' | 'pre-reset'
    uid    : unique-ID do probe (None → usa o primeiro ST-Link encontrado)
    """

    def __init__(
        self,
        target: str = "stm32f446retx",
        mode: str = "halt",
        uid: str | None = None,
    ) -> None:
        try:
            from pyocd.core.helpers import ConnectHelper  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "pyocd não instalado — execute: pip install pyocd"
            ) from exc

        self._ConnectHelper = ConnectHelper
        self._target_str = target
        self._mode = mode
        self._uid = uid
        self._session: Any = None
        self._target: Any = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> StLinkADIv5:
        self._open()
        return self

    def __exit__(self, *_: object) -> None:
        self._close()

    def _open(self) -> None:
        kwargs: dict[str, Any] = {
            "target_override": self._target_str,
            "connect_mode": self._mode,
            "blocking": False,
        }
        if self._uid:
            kwargs["unique_id"] = self._uid

        session = self._ConnectHelper.session_with_chosen_probe(**kwargs)
        if session is None:
            raise RuntimeError(
                "Nenhum ST-Link encontrado — conecte o cabo USB da NUCLEO."
            )
        self._session = session
        self._session.__enter__()
        self._target = self._session.target

    def _close(self) -> None:
        if self._session is not None:
            try:
                self._session.__exit__(None, None, None)
            finally:
                self._session = None
                self._target = None

    # ------------------------------------------------------------------
    # Inicialização — interface idêntica a ADIv5
    # ------------------------------------------------------------------

    def init(self) -> int:
        """Retorna o DPIDR lido via DP register 0 (ADIv5 DPIDR)."""
        assert self._target is not None
        return int(self._target.dp.read_reg(0))

    # ------------------------------------------------------------------
    # Acesso a memória
    # ------------------------------------------------------------------

    def read_mem32(self, addr: int) -> int:
        """Lê 32 bits do endereço `addr` via MEM-AP."""
        assert self._target is not None
        return int(self._target.read32(addr))

    def write_mem32(self, addr: int, value: int) -> None:
        """Escreve 32 bits no endereço `addr` via MEM-AP."""
        assert self._target is not None
        self._target.write32(addr, value)

    # ------------------------------------------------------------------
    # Controle de execução
    # ------------------------------------------------------------------

    def halt(self) -> None:
        assert self._target is not None
        self._target.halt()

    def resume(self) -> None:
        assert self._target is not None
        self._target.resume()

    def is_halted(self) -> bool:
        assert self._target is not None
        return bool(self._target.is_halted())

    def step(self) -> None:
        assert self._target is not None
        self._target.step()

    def reset_system(self) -> None:
        assert self._target is not None
        self._target.reset()

    # ------------------------------------------------------------------
    # Registradores de núcleo  (0=R0 … 12=R12, 13=SP, 14=LR, 15=PC, 16=xPSR)
    # ------------------------------------------------------------------

    def read_core_register(self, reg: int) -> int:
        """Lê registrador de núcleo pelo índice ARM DCRSR."""
        assert self._target is not None
        return int(self._target.read_core_register(reg))

    def write_core_register(self, reg: int, value: int) -> None:
        """Escreve registrador de núcleo pelo índice ARM DCRSR."""
        assert self._target is not None
        self._target.write_core_register(reg, value)
