"""PAL — Peripheral Access Layer.

Une o SvdDevice (endereços e campos) com qualquer adaptador que implemente
IMemoryAccess (leitura/escrita de 32 bits), tipicamente StLinkADIv5.

Exemplo::

    pal = PeripheralAccessLayer(adiv5, svd_device)
    idr = pal.read_reg("GPIOA", "IDR")
    led = pal.read_field("GPIOA", "IDR", "IDR5")
    pal.modify_field("GPIOA", "MODER", "MODER5", 0b01)   # PA5 → output
    pal.write_reg("GPIOA", "BSRR", 1 << 5)               # set PA5
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.svd.model import SvdDevice


@runtime_checkable
class IMemoryAccess(Protocol):
    """Interface mínima que o PAL exige do adaptador de debug."""

    def read_mem32(self, addr: int) -> int: ...
    def write_mem32(self, addr: int, value: int) -> None: ...


class PeripheralAccessLayer:
    """Acesso de alto nível a periféricos via SVD + adaptador de memória.

    Parâmetros
    ----------
    mem    : qualquer objeto com read_mem32 / write_mem32 (ex. StLinkADIv5)
    device : SvdDevice gerado pelo parser SVD do dispositivo alvo
    """

    def __init__(self, mem: IMemoryAccess, device: SvdDevice) -> None:
        self._mem = mem
        self._device = device

    # ------------------------------------------------------------------
    # Acesso bruto a registradores (32 bits)
    # ------------------------------------------------------------------

    def read_reg(self, peripheral: str, register: str) -> int:
        """Lê 32 bits de um registrador SVD pelo nome."""
        addr = self._device.peripheral(peripheral).address_of(register)
        return self._mem.read_mem32(addr)

    def write_reg(self, peripheral: str, register: str, value: int) -> None:
        """Escreve 32 bits em um registrador SVD pelo nome."""
        addr = self._device.peripheral(peripheral).address_of(register)
        self._mem.write_mem32(addr, value & 0xFFFFFFFF)

    # ------------------------------------------------------------------
    # Acesso a campos de bits
    # ------------------------------------------------------------------

    def read_field(self, peripheral: str, register: str, field: str) -> int:
        """Extrai e retorna o valor de um campo de bits."""
        reg = self._device.peripheral(peripheral).register(register)
        raw = self.read_reg(peripheral, register)
        return reg.field(field).extract(raw)

    def modify_field(
        self,
        peripheral: str,
        register: str,
        field: str,
        new_value: int,
    ) -> None:
        """Altera apenas os bits de um campo preservando os demais (RMW)."""
        reg = self._device.peripheral(peripheral).register(register)
        f = reg.field(field)
        current = self.read_reg(peripheral, register)
        updated = (current & ~f.mask) | ((new_value << f.bit_offset) & f.mask)
        self.write_reg(peripheral, register, updated)

    # ------------------------------------------------------------------
    # Utilitários
    # ------------------------------------------------------------------

    def address_of(self, peripheral: str, register: str) -> int:
        """Endereço absoluto de um registrador SVD."""
        return self._device.peripheral(peripheral).address_of(register)

    @property
    def device(self) -> SvdDevice:
        return self._device

    @property
    def mem(self) -> IMemoryAccess:
        return self._mem
