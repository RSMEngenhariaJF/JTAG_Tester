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

# STM32H7: DBGMCU pelo AP2 (APB de debug), acessível mesmo com o núcleo dormindo
_H7_DBGMCU_CR_AP2 = 0xE00E1004
_H7_DBGMCU_DEBUG_LP = 0x3F | 0x7 << 20       # debug em sleep/stop/standby + clocks D1/D2/D3


def _h7_debug_in_low_power(probe: Any, session: Any) -> None:
    """Liga o debug em sleep/stop/standby (DBGMCU_CR) antes da sessão do pyOCD.

    Feito direto no ST-Link (AP2) porque, com o firmware dormindo, o AP0 não
    responde e a descoberta do pyOCD falha. Sem efeito se já estiver ligado.
    """
    from pyocd.probe.debug_probe import DebugProbe  # type: ignore[import-untyped]

    probe.session = session
    probe.open()
    try:
        probe.connect(DebugProbe.Protocol.SWD)
        probe.read_dp(0x0)                          # DPIDR (sai do reset da linha)
        probe.write_dp(0x4, 0x50000000)             # CDBGPWRUPREQ | CSYSPWRUPREQ
        link = probe._link
        link.open_ap(2)
        raw = link.read_mem32(_H7_DBGMCU_CR_AP2, 4, 2, 0)
        cr = int.from_bytes(bytes(raw), "little")
        if cr & _H7_DBGMCU_DEBUG_LP != _H7_DBGMCU_DEBUG_LP:
            new = cr | _H7_DBGMCU_DEBUG_LP
            link.write_mem32(_H7_DBGMCU_CR_AP2, list(new.to_bytes(4, "little")), 2, 0)
    finally:
        probe.disconnect()
        probe.close()


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

    @property
    def _is_h7(self) -> bool:
        return self._target_str.lower().startswith("stm32h7")

    def _open(self) -> None:
        # STM32H7 com firmware em baixo consumo (WFI/stop): o núcleo fica sem clock
        # e o AP0 devolve lixo ("Invalid coresight component", "No cores were
        # discovered"). O modo 'halt'/'under-reset' do pyOCD reseta o chip e tenta
        # configurar o DBGMCU pelo AP0 — o firmware volta a dormir antes. Solução:
        # DBGMCU pelo AP2 (sempre acessível) e sessão em 'attach'; o halt vem depois.
        mode = "attach" if self._is_h7 else self._mode
        kwargs: dict[str, Any] = {
            "target_override": self._target_str,
            "connect_mode": mode,
            "blocking": False,
        }
        if self._uid:
            kwargs["unique_id"] = self._uid

        session = self._ConnectHelper.session_with_chosen_probe(**kwargs)
        if session is None:
            raise RuntimeError(
                "Nenhum ST-Link encontrado — conecte o cabo USB da placa."
            )
        if self._is_h7:
            _h7_debug_in_low_power(session.probe, session)
        self._session = session
        self._session.__enter__()
        self._target = self._session.target
        if self._is_h7 and self._mode in ("halt", "under-reset"):
            self._target.halt()

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

    def read_block32(self, addr: int, count: int) -> list[int]:
        """Lê `count` palavras de 32 bits a partir de `addr` (transferência em bloco)."""
        assert self._target is not None
        return [int(w) for w in self._target.read_memory_block32(addr, count)]

    def write_block32(self, addr: int, words: list[int]) -> None:
        """Escreve palavras de 32 bits a partir de `addr` (transferência em bloco)."""
        assert self._target is not None
        self._target.write_memory_block32(addr, list(words))

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

    def reset_and_halt(self) -> None:
        """Reseta o chip e para o núcleo no vetor de reset (clocks no estado padrão)."""
        assert self._target is not None
        self._target.reset_and_halt()

    def reconnect(self) -> None:
        """Fecha e reabre a sessão com o mesmo alvo e modo (o objeto continua válido).

        No STM32H7, depois de reset_and_halt() + resume() o acesso ao barramento
        deixa de responder quando o firmware volta a rodar (leituras repetem o
        último valor). Reabrir a sessão — no modo "under-reset" — refaz a
        configuração de debug e restaura o acesso.
        """
        self._close()
        self._open()

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
