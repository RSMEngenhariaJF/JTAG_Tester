"""Base da HAL: família, clocks pelo SVD, pinos em função alternativa e espera."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger("hal.pinos")

# ── Família ───────────────────────────────────────────────────────────────────


def has_register(pal, periph: str, reg: str) -> bool:
    try:
        pal.device.peripheral(periph).register(reg)
        return True
    except KeyError:
        return False


def family(pal) -> str:
    """"H7" (RCC com AHB4ENR / D2CCIP2R) ou "F4" (RCC com AHB1ENR + PLLCFGR)."""
    if has_register(pal, "RCC", "D2CCIP2R"):
        return "H7"
    return "F4"


# ── Clocks (procurados no SVD, não em tabela) ─────────────────────────────────

def _clock_fields(name: str) -> list[str]:
    n = name.upper()
    cands = [f"{n}EN"]
    if m := re.fullmatch(r"UART(\d+)", n):          # SVD do H7 chama UART7 de USART7EN
        cands.append(f"USART{m.group(1)}EN")
    if n.startswith("FDCAN"):
        cands.append("FDCANEN")
    if n.startswith("ETH"):
        cands += ["ETH1MACEN", "ETHMACEN"]
    if n.startswith("GPIO"):
        cands.append(f"{n}EN")
    return cands


def find_clock(pal, name: str) -> tuple[str, str]:
    """(registrador, campo) RCC que habilita o clock de `name` (ex.: USART3)."""
    rcc = pal.device.peripheral("RCC")
    regs = [r for r in rcc.registers
            if r.name.endswith("ENR") and "LP" not in r.name and not r.name.startswith("C1_")]
    for cand in _clock_fields(name):
        for r in regs:
            if any(f.name.upper() == cand for f in r.fields):
                return r.name, cand
    raise LookupError(f"Bit de clock de {name} não encontrado no RCC do SVD")


def enable_clock(pal, name: str) -> None:
    reg, field = find_clock(pal, name)
    pal.modify_field("RCC", reg, field, 1)


# ── Funções alternativas (AF) ─────────────────────────────────────────────────

# AF mais comuns por família (RM0390 tabela 11 / DS12117 tabela 9). Exceções do
# datasheet podem ser informadas por pino: PeripheralRef.params["af"].
_AF = {
    "F4": [(r"USART[123]$", 7), (r"(UART[45]|USART6)$", 8), (r"SPI[12]$", 5), (r"SPI3$", 6),
           (r"SPI4$", 5), (r"I2C[123]$", 4), (r"CAN[12]$", 9), (r"ETH", 11),
           (r"TIM[12]$", 1), (r"TIM[345]$", 2), (r"TIM([89]|1[01])$", 3),
           (r"TIM1[234]$", 9)],
    "H7": [(r"USART[1236]$", 7), (r"UART[4578]$", 8), (r"SPI[1236]$", 5), (r"SPI[45]$", 5),
           (r"I2C[1234]$", 4), (r"FDCAN[12]$", 9), (r"ETH", 11),
           (r"TIM[12]$", 1), (r"TIM[345]$", 2), (r"TIM8$", 3), (r"TIM12$", 2),
           (r"TIM1[34]$", 9), (r"TIM15$", 4), (r"TIM1[67]$", 1)],
}

# Exceções que dependem da porta (DS12117 tabela 9): UART7 é AF7 em PE/PF e
# AF11 em PA/PB.
_AF_BY_PORT = {
    "H7": {("UART7", "GPIOE"): 7, ("UART7", "GPIOF"): 7,
           ("UART7", "GPIOA"): 11, ("UART7", "GPIOB"): 11},
}


def default_af(periph_name: str, fam: str, override: int | None = None,
               port: str = "") -> int:
    if override is not None:
        return int(override)
    by_port = _AF_BY_PORT.get(fam, {}).get((periph_name.upper(), port.upper()))
    if by_port is not None:
        return by_port
    for pattern, af in _AF.get(fam, []):
        if re.match(pattern, periph_name.upper()):
            return af
    raise LookupError(f"AF de {periph_name} desconhecida para {fam}: informe params['af'] no pino")


def pin_af(pal, signal, periph_name: str = "") -> int:
    """AF do sinal do Pinout no seu pino: Pinout → mapa do dispositivo → tabela.

    signal: tests_builtin.params.Signal (port, pin, role, af, periph_name).
    """
    from hal import afmap

    periph = (periph_name or signal.periph_name).upper()
    if signal.af is not None:
        return int(signal.af)
    if signal.role:
        af = afmap.lookup(pal.device.name, signal.port, signal.pin, f"{periph}_{signal.role}")
        if af is not None:
            return af
    return default_af(periph, family(pal), None, signal.port)


# ── Pinos ─────────────────────────────────────────────────────────────────────

_PIN_REGS = ("MODER", "OTYPER", "OSPEEDR", "PUPDR")


@dataclass
class PinSnapshot:
    port:  str
    pin:   int
    moder: int
    otype: int
    speed: int
    pull:  int
    af:    int
    odr:   int


def snapshot_pin(pal, port: str, pin: int) -> PinSnapshot:
    afr = "AFRH" if pin >= 8 else "AFRL"
    return PinSnapshot(
        port, pin,
        pal.read_field(port, "MODER", f"MODER{pin}"),
        pal.read_field(port, "OTYPER", f"OT{pin}"),
        pal.read_field(port, "OSPEEDR", f"OSPEEDR{pin}"),
        pal.read_field(port, "PUPDR", f"PUPDR{pin}"),
        pal.read_field(port, afr, f"{afr}{pin}"),
        pal.read_field(port, "ODR", f"ODR{pin}"),
    )


def restore_pin(pal, s: PinSnapshot) -> None:
    afr = "AFRH" if s.pin >= 8 else "AFRL"
    pal.modify_field(s.port, afr, f"{afr}{s.pin}", s.af)
    pal.modify_field(s.port, "OTYPER", f"OT{s.pin}", s.otype)
    pal.modify_field(s.port, "OSPEEDR", f"OSPEEDR{s.pin}", s.speed)
    pal.modify_field(s.port, "PUPDR", f"PUPDR{s.pin}", s.pull)
    pal.modify_field(s.port, "ODR", f"ODR{s.pin}", s.odr)
    pal.modify_field(s.port, "MODER", f"MODER{s.pin}", s.moder)
    log.debug("P%s%d restaurado (MODER=%d AF=%d)", s.port.removeprefix("GPIO"), s.pin,
              s.moder, s.af)


PULL = {"nenhum": 0, "pull-up": 1, "pull-down": 2}


def set_af(pal, port: str, pin: int, af: int, *, open_drain: bool = False,
           pull: str = "nenhum", speed: int = 2) -> None:
    """Pino em função alternativa (clock da porta incluído)."""
    enable_clock(pal, port)
    afr = "AFRH" if pin >= 8 else "AFRL"
    pal.modify_field(port, afr, f"{afr}{pin}", af)
    pal.modify_field(port, "OTYPER", f"OT{pin}", int(open_drain))
    pal.modify_field(port, "OSPEEDR", f"OSPEEDR{pin}", speed)
    pal.modify_field(port, "PUPDR", f"PUPDR{pin}", PULL[pull])
    pal.modify_field(port, "MODER", f"MODER{pin}", 0b10)
    log.debug("P%s%d em AF%d%s, pull %s", port.removeprefix("GPIO"), pin, af,
              " open-drain" if open_drain else "", pull)


def set_input(pal, port: str, pin: int, pull: str = "nenhum") -> None:
    enable_clock(pal, port)
    pal.modify_field(port, "PUPDR", f"PUPDR{pin}", PULL[pull])
    pal.modify_field(port, "MODER", f"MODER{pin}", 0b00)


def set_output(pal, port: str, pin: int, level: int | None = None) -> None:
    enable_clock(pal, port)
    if level is not None:
        pal.write_reg(port, "BSRR", 1 << (pin if level else pin + 16))
    pal.modify_field(port, "MODER", f"MODER{pin}", 0b01)


def read_pin(pal, port: str, pin: int) -> int:
    return pal.read_field(port, "IDR", f"IDR{pin}")


# ── Registradores: salvar / restaurar ─────────────────────────────────────────

def save_regs(pal, periph: str, regs: tuple[str, ...]) -> dict[str, int]:
    return {r: pal.read_reg(periph, r) for r in regs if has_register(pal, periph, r)}


def restore_regs(pal, periph: str, saved: dict[str, int]) -> None:
    for r, v in saved.items():
        pal.write_reg(periph, r, v)


# ── Clock de núcleo (kernel) no H7: HSI, conhecido e independente do firmware ─

def hsi_hz(pal) -> int:
    return 64_000_000 >> pal.read_field("RCC", "CR", "HSIDIV")


def select_hsi_kernel(pal, reg: str, field: str, code: int) -> tuple[int, int]:
    """Troca a fonte de clock do periférico para o HSI. Retorna (f_hsi, valor antigo)."""
    old = pal.read_field("RCC", reg, field)
    pal.modify_field("RCC", "CR", "HSIKERON", 1)
    pal.modify_field("RCC", "CR", "HSION", 1)
    wait(lambda: pal.read_field("RCC", "CR", "HSIRDY") == 1, 0.05, "HSI não ficou pronto")
    pal.modify_field("RCC", reg, field, code)
    return hsi_hz(pal), old


# ── Espera com timeout ────────────────────────────────────────────────────────

def wait(cond: Callable[[], bool], timeout_s: float, msg: str) -> None:
    deadline = time.perf_counter() + timeout_s
    while not cond():
        if time.perf_counter() > deadline:
            raise TimeoutError(msg)
