"""Importação de pinout a partir de projetos STM32CubeMX (.ioc).

O .ioc é um arquivo texto ``chave=valor``. As chaves usadas aqui:

    Mcu.CPN / Mcu.UserName / Mcu.Family / Mcu.Package   → identificação do MCU
    ProjectManager.ProjectName                          → nome do projeto
    PD5.Signal=USART2_TX                                → função do pino
    PC4.GPIO_Label=LED1                                 → rótulo do usuário
    PB5.GPIO_ModeDefaultEXTI=GPIO_MODE_IT_FALLING       → borda da EXTI
    PB5.GPIO_PuPd=GPIO_PULLUP                           → pull-up/down
    SH.SharedAnalog_PF10.1=ADC3_INP6,IN6-Single-Ended   → sinal compartilhado
    USART2.BaudRate=9600                                → parâmetros do periférico

Pinos de infraestrutura (SWD/JTAG, osciladores — ``SYS_*``/``RCC_*``) e pinos
virtuais (``VP_*``) são ignorados: não são sinais do produto a testar.

Uso::

    ioc = parse_ioc(Path("MESA_CT.ioc").read_text(encoding="utf-8"))
    ioc.cpn          # "STM32H753ZIT6"
    ioc.pins         # {"usart2_tx": PinDef(GPIOD, 5, UART USART2 TX), ...}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.project.config import PeripheralRef, PinDef

# "PA0-WKUP", "PC14-OSC32_IN", "PH0-OSC_IN (PH0)" → porta A, pino 0
_PIN_RE = re.compile(r"^P([A-K])(\d{1,2})(?![0-9])")

# prefixo do sinal CubeMX → tipo de periférico do ProjectConfig
_TYPE_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("LPUART", "UART"),
    ("USART", "UART"),
    ("UART", "UART"),
    ("SPI", "SPI"),
    ("I2C", "I2C"),
    ("ADC", "ADC"),
    ("DAC", "DAC"),
    ("FDCAN", "CAN"),
    ("CAN", "CAN"),
    ("TIM", "TIM"),
    ("LPTIM", "TIM"),
    ("ETH", "ETH"),
)

_IGNORED_PREFIXES: tuple[str, ...] = ("SYS_", "RCC_", "DEBUG_")

_EXTI_EDGE: dict[str, str] = {
    "GPIO_MODE_IT_RISING": "RISING",
    "GPIO_MODE_IT_FALLING": "FALLING",
    "GPIO_MODE_IT_RISING_FALLING": "BOTH",
    "GPIO_MODE_EVT_RISING": "RISING",
    "GPIO_MODE_EVT_FALLING": "FALLING",
    "GPIO_MODE_EVT_RISING_FALLING": "BOTH",
}

_PULL: dict[str, str] = {"GPIO_PULLUP": "pull-up", "GPIO_PULLDOWN": "pull-down"}

# kits de avaliação da ST (board=<nome do kit> no .ioc)
_ST_KITS: tuple[str, ...] = ("NUCLEO", "DISCO", "STM32", "EVAL")


@dataclass
class IocProject:
    """Conteúdo relevante de um .ioc."""

    project_name: str = ""
    cpn:          str = ""      # "STM32H753ZIT6" — part number comercial
    user_name:    str = ""      # "STM32H753ZITx" — mesmo formato de BoardConfig.target
    family:       str = ""      # "STM32H7"
    package:      str = ""      # "LQFP144"
    board:        str = ""      # "NUCLEO-H753ZI" ou "custom" (placa própria)
    clocks:       dict = field(default_factory=dict)   # ProjectConfig.clocks
    pins:        dict[str, PinDef] = field(default_factory=dict)
    skipped:      list[str]         = field(default_factory=list)  # "PA13 (SYS_JTMS-SWDIO)"

    @property
    def target(self) -> str:
        """Nome no formato de ``BoardConfig.target`` (ex.: 'stm32h753zitx')."""
        return self.user_name.lower()

    def match_board(self, boards):
        """Placa cadastrada para este .ioc: mesmo MCU e, havendo mais de uma,
        a de mesmo nome (kit ST) ou, com ``board=custom``, a que não é kit ST."""
        same_mcu = [b for b in boards if b.target.lower() == self.target]
        key = self.board.strip().lower().replace("_", "-")
        by_name = [b for b in same_mcu if b.name.strip().lower().replace("_", "-") == key]
        if by_name:
            return by_name[0]
        if key == "custom":
            own = [b for b in same_mcu if not b.name.upper().startswith(_ST_KITS)]
            if own:
                return own[0]
        return same_mcu[0] if same_mcu else None


def parse_ioc(text: str) -> IocProject:
    """Lê o texto de um .ioc e devolve MCU + pinout como ``PinDef``."""
    kv = _parse_kv(text)
    ioc = IocProject(
        project_name = kv.get("ProjectManager.ProjectName", ""),
        cpn          = kv.get("Mcu.CPN", ""),
        user_name    = kv.get("Mcu.UserName", kv.get("Mcu.Name", "")),
        family       = kv.get("Mcu.Family", ""),
        package      = kv.get("Mcu.Package", ""),
        board        = kv.get("board", ""),
        clocks       = _clocks(kv),
    )

    found: list[tuple[str, int, str, str]] = []
    for key, signal in kv.items():
        if not key.endswith(".Signal"):
            continue
        pin_name = key[: -len(".Signal")]
        match = _PIN_RE.match(pin_name)
        if match is None:          # VP_* e afins
            continue
        if signal.startswith(_IGNORED_PREFIXES):
            ioc.skipped.append(f"{pin_name} ({signal})")
            continue
        found.append((match.group(1), int(match.group(2)), pin_name, signal))

    for port_letter, pin, pin_name, raw_signal in sorted(found):
        port = f"GPIO{port_letter}"
        signal = _resolve_shared(raw_signal, kv)
        label = kv.get(f"{pin_name}.GPIO_Label", "")
        periph = _peripheral(signal, pin_name, kv)

        details = [signal if label in ("", signal) else f"{label} — {signal}"]
        pull = _PULL.get(kv.get(f"{pin_name}.GPIO_PuPd", ""))
        if pull:
            details.append(pull)

        name = _signal_key(label, signal, periph, pin_name)
        ioc.pins[_unique(name, ioc.pins)] = PinDef(
            port        = port,
            pin         = pin,
            description = ", ".join(details) + f" [{pin_name}]",
            peripheral  = periph,
        )

    return ioc


# ── Clock ────────────────────────────────────────────────────────────────────

# chave em ProjectConfig.clocks → chaves RCC.* do .ioc (H7, F4). O CubeMX só grava
# o que difere do padrão: chave ausente = não verificada.
_CLOCK_KEYS: dict[str, tuple[str, ...]] = {
    "HSE":      ("HSE_VALUE",),
    "SYSCLK":   ("SYSCLKFreq_VALUE",),
    "CPU":      ("CpuClockFreq_Value", "HCLKFreq_Value"),
    "HCLK":     ("HCLKFreq_Value",),
    "APB1":     ("APB1Freq_Value",),
    "APB2":     ("APB2Freq_Value",),
    "APB3":     ("APB3Freq_Value",),
    "APB4":     ("APB4Freq_Value",),
    "TIM_APB1": ("Tim1OutputFreq_Value", "APB1TimFreq_Value"),
    "TIM_APB2": ("Tim2OutputFreq_Value", "APB2TimFreq_Value"),
}
_SYSCLK_SOURCE = {"PLLCLK": "PLL1", "HSE": "HSE", "HSI": "HSI", "CSI": "CSI"}


def _clocks(kv: dict[str, str]) -> dict:
    out: dict = {}
    for key, candidates in _CLOCK_KEYS.items():
        for c in candidates:
            raw = kv.get(f"RCC.{c}", "")
            try:
                out[key] = float(raw)
                break
            except ValueError:
                continue
    src = kv.get("RCC.SYSCLKSource", "").removeprefix("RCC_SYSCLKSOURCE_")
    if src in _SYSCLK_SOURCE:
        out["fonte"] = _SYSCLK_SOURCE[src]
    # Osciladores externos: modo dos pinos OSC (cristal ou clock externo = bypass)
    modes = [v for k, v in kv.items() if k.endswith(".Mode")]
    for osc in ("HSE", "LSE"):
        if f"{osc}-External-Oscillator" in modes or f"{osc}-External-Clock-Source" in modes:
            out[f"{osc}_BYPASS"] = f"{osc}-External-Clock-Source" in modes
    if "LSE_BYPASS" in out:
        out["LSE"] = float(kv.get("RCC.LSE_VALUE", "32768") or 32768)
    # Configuração do PLL1 e prescalers (H7) para o testador montar a árvore sem firmware
    pll = {k: int(kv[f"RCC.DIV{k.upper()}1"]) for k in "mnpqr" if f"RCC.DIV{k.upper()}1" in kv}
    if pll:
        out["PLL1"] = pll
        out["PLL_SRC"] = kv.get("RCC.PLLSourceVirtual", "").removeprefix("RCC_PLLSOURCE_")
        out["DIV"] = {k: _div(kv.get(f"RCC.{k}", "")) for k in
                      ("D1CPRE", "HPRE", "D1PPRE", "D2PPRE1", "D2PPRE2", "D3PPRE")}
        out["VOS"] = int(kv.get("RCC.PWR_Regulator_Voltage_Scale", "SCALE1")[-1])
        out["SUPPLY"] = kv.get("RCC.SupplySource", "PWR_LDO_SUPPLY").removeprefix("PWR_")
    return out


def _div(value: str) -> int:
    """'RCC_HCLK_DIV2' → 2; ausente (padrão do CubeMX) → 1."""
    m = re.search(r"DIV(\d+)$", value)
    return int(m.group(1)) if m else 1


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_kv(text: str) -> dict[str, str]:
    """``chave=valor`` por linha; '#' inicia comentário; desfaz escapes '\\:' '\\#'."""
    kv: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        kv[_unescape(key.strip())] = _unescape(value.strip())
    return kv


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s)


def _resolve_shared(signal: str, kv: dict[str, str]) -> str:
    """Sinal compartilhado (SharedAnalog_PF10, ADCx_IN0) → 1ª opção concreta.

    As opções vêm de ``SH.<sinal>.N``; prefere entrada positiva/simples (INP/IN)
    a entrada negativa (INN).
    """
    if f"SH.{signal}.0" not in kv:
        return signal
    options = [
        kv[f"SH.{signal}.{i}"].split(",")[0]
        for i in range(int(kv.get(f"SH.{signal}.ConfNb", "1") or 1))
        if f"SH.{signal}.{i}" in kv
    ]
    options.sort(key=lambda o: "_INN" in o)
    return options[0] if options else signal


def _peripheral(signal: str, pin_name: str, kv: dict[str, str]) -> PeripheralRef:
    if signal in ("GPIO_Output", "GPIO_Input", "GPIO_Analog"):
        return PeripheralRef("GPIO")

    if signal.startswith("GPXTI") or signal.startswith("GPIO_EXTI"):
        edge = _EXTI_EDGE.get(kv.get(f"{pin_name}.GPIO_ModeDefaultEXTI", ""), "")
        line = re.sub(r"\D", "", signal)
        return PeripheralRef("EXTI", f"EXTI{line}" if line else "", edge)

    periph_name, _, role = signal.partition("_")
    for prefix, periph_type in _TYPE_BY_PREFIX:
        suffix = periph_name[len(prefix):] if periph_name.startswith(prefix) else None
        if suffix is not None and (suffix == "" or suffix.isdigit()):
            if periph_type == "TIM" and _is_pwm(periph_name, role, kv):
                periph_type = "PWM"
            params: dict[str, object] = {}
            baud = kv.get(f"{periph_name}.BaudRate")
            if periph_type == "UART" and baud and baud.isdigit():
                params["baudrate"] = int(baud)
            return PeripheralRef(periph_type, periph_name, role, params)

    # Função sem tipo equivalente (USB, SDMMC, FMC…): mantém como GPIO,
    # o sinal original fica registrado na descrição.
    return PeripheralRef("GPIO")


def _is_pwm(tim: str, role: str, kv: dict[str, str]) -> bool:
    prefix = f"{tim}.Channel-PWM Generation"
    return any(k.startswith(prefix) and k.endswith(role) for k in kv)


def _signal_key(label: str, signal: str, periph: PeripheralRef, pin_name: str) -> str:
    """Nome semântico: rótulo do usuário > função do periférico > nome do pino."""
    if label:
        base = label
    elif periph.name and periph.role and periph.periph_type != "EXTI":
        base = f"{periph.name}_{periph.role}"
    elif periph.periph_type == "EXTI":
        base = f"{_PIN_RE.match(pin_name).group(0)}_exti"  # type: ignore[union-attr]
    else:
        base = _PIN_RE.match(pin_name).group(0)  # type: ignore[union-attr]
    return re.sub(r"[^0-9a-z]+", "_", base.lower()).strip("_") or signal.lower()


def _unique(name: str, existing: dict[str, PinDef]) -> str:
    if name not in existing:
        return name
    n = 2
    while f"{name}_{n}" in existing:
        n += 1
    return f"{name}_{n}"
