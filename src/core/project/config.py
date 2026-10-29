"""Configuração de projeto — pinout semântico + testes + instrumentos.

Hierarquia de abstração:
    BoardConfig    → nível MCU: registradores, periféricos disponíveis
    PeripheralRef  → qual função alternativa este pino exerce (UART TX, SPI MOSI, ADC IN0…)
    PinDef         → localização física (porta + número) + referência ao periférico
    ProjectConfig  → produto completo: mapa de sinais, testes e instrumentos

Uso em testes::

    from core.project.config import get_active_project

    proj = get_active_project()

    # GPIO simples
    led = proj.pin("led")
    GpioInstrument(led.port, pal).pin(led.pin).set()

    # UART — o periférico vem do ProjectConfig
    tx = proj.pin("uart2_tx")               # PinDef: GPIOA.2, USART2.TX
    uart = UsartInstrument(tx.peripheral.name, pal)   # "USART2"
    uart.configure(baudrate=tx.peripheral.params.get("baudrate", 115200))

    # Todos os pinos de um periférico
    for sig, pin_def in proj.pins_of_peripheral("SPI1"):
        print(sig, pin_def.peripheral.role)   # "spi1_mosi", MOSI ...
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field


# ── Tipos de periférico suportados ─────────────────────────────────────────

PERIPH_TYPES: list[str] = [
    "GPIO",
    "UART",
    "SPI",
    "I2C",
    "ADC",
    "DAC",
    "PWM",
    "TIM",
    "EXTI",
    "CAN",
]

# Funções típicas por tipo (usado como sugestão na GUI)
PERIPH_ROLES: dict[str, list[str]] = {
    "GPIO": [],
    "UART": ["TX", "RX", "CTS", "RTS", "CK"],
    "SPI":  ["MOSI", "MISO", "SCK", "NSS"],
    "I2C":  ["SDA", "SCL"],
    "ADC":  [f"IN{i}" for i in range(16)],
    "DAC":  ["OUT1", "OUT2"],
    "PWM":  ["CH1", "CH2", "CH3", "CH4", "CH1N", "CH2N", "CH3N"],
    "TIM":  ["CH1", "CH2", "CH3", "CH4", "ETR", "BKIN"],
    "EXTI": ["RISING", "FALLING", "BOTH"],
    "CAN":  ["TX", "RX"],
}


@dataclass
class PeripheralRef:
    """Referência à função alternativa deste pino no MCU.

    Exemplos:
        PeripheralRef("UART", "USART2", "TX", {"baudrate": 115200})
        PeripheralRef("SPI",  "SPI1",   "MOSI")
        PeripheralRef("ADC",  "ADC1",   "IN0",  {"resolution": 12, "vref": 3.3})
        PeripheralRef("PWM",  "TIM1",   "CH1",  {"freq_hz": 20000})
        PeripheralRef("EXTI", "",       "RISING")
    """

    periph_type: str  = "GPIO"
    name:        str  = ""        # "USART2", "SPI1", "ADC1", "TIM1"
    role:        str  = ""        # "TX", "MOSI", "IN0", "CH1", "RISING"
    params:      dict = field(default_factory=dict)

    @property
    def is_gpio(self) -> bool:
        return self.periph_type == "GPIO"

    def to_dict(self) -> dict:
        d: dict = {"type": self.periph_type}
        if self.name:   d["name"]   = self.name
        if self.role:   d["role"]   = self.role
        if self.params: d["params"] = self.params
        return d

    @classmethod
    def from_dict(cls, d: dict) -> PeripheralRef:
        return cls(
            periph_type = d.get("type", "GPIO"),
            name        = d.get("name", ""),
            role        = d.get("role", ""),
            params      = d.get("params", {}),
        )


@dataclass
class PinDef:
    """Localização física de um sinal no circuito + referência ao periférico."""

    port:        str                        # "GPIOA"
    pin:         int                        # 5
    description: str           = ""
    active_low:  bool          = False
    peripheral:  PeripheralRef = field(default_factory=PeripheralRef)

    def to_dict(self) -> dict:
        d: dict = {"port": self.port, "pin": self.pin}
        if self.description:
            d["description"] = self.description
        if self.active_low:
            d["active_low"] = True
        # só serializa peripheral se não for GPIO puro sem informação extra
        p = self.peripheral
        if p.periph_type != "GPIO" or p.name or p.role or p.params:
            d["peripheral"] = p.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> PinDef:
        periph_data = d.get("peripheral")
        return cls(
            port        = d["port"],
            pin         = int(d["pin"]),
            description = d.get("description", ""),
            active_low  = bool(d.get("active_low", False)),
            peripheral  = PeripheralRef.from_dict(periph_data) if periph_data else PeripheralRef(),
        )


@dataclass
class ProjectConfig:
    """Configuração completa de um produto testável.

    Um mesmo BoardConfig pode ser referenciado por vários ProjectConfigs,
    cada um com seu próprio pinout semântico e suite de testes associada.
    """

    name:            str
    project_code:    str
    board:           str                   # nome do BoardConfig (ex: "nucleo_f446re")
    pins:            dict[str, PinDef]    = field(default_factory=dict)
    test_paths:      list[str]            = field(default_factory=list)
    instruments:     list[str]            = field(default_factory=list)
    description:     str                  = ""
    analysis_config: str                  = ""  # filename em analysis_configs/

    # ── Acesso por sinal ─────────────────────────────────────────────────

    def pin(self, signal: str) -> PinDef:
        """Retorna a definição física de um sinal pelo nome semântico."""
        if signal not in self.pins:
            raise KeyError(
                f"Sinal '{signal}' não definido no projeto '{self.name}'. "
                f"Disponíveis: {sorted(self.pins)}"
            )
        return self.pins[signal]

    def has_pin(self, signal: str) -> bool:
        return signal in self.pins

    # ── Acesso por periférico ─────────────────────────────────────────────

    def pins_of_peripheral(self, periph_name: str) -> list[tuple[str, PinDef]]:
        """Retorna [(sinal, PinDef)] de todos os pinos do periférico.

        Exemplo::

            for sig, pin_def in proj.pins_of_peripheral("USART2"):
                print(sig, pin_def.peripheral.role)   # uart2_tx  TX
        """
        return [
            (sig, pd)
            for sig, pd in self.pins.items()
            if pd.peripheral.name == periph_name
        ]

    def pins_of_type(self, periph_type: str) -> list[tuple[str, PinDef]]:
        """Retorna [(sinal, PinDef)] de todos os pinos de um tipo.

        Exemplo::

            for sig, pd in proj.pins_of_type("ADC"):
                print(sig, pd.peripheral.name, pd.peripheral.role)
        """
        return [
            (sig, pd)
            for sig, pd in self.pins.items()
            if pd.peripheral.periph_type == periph_type
        ]

    def peripheral_names(self, periph_type: str | None = None) -> list[str]:
        """Retorna nomes únicos de periféricos, opcionalmente filtrados por tipo."""
        names: list[str] = []
        for pd in self.pins.values():
            name = pd.peripheral.name
            if name and (periph_type is None or pd.peripheral.periph_type == periph_type):
                if name not in names:
                    names.append(name)
        return names

    # ── Serialização JSON ─────────────────────────────────────────────────

    def to_dict(self) -> dict:
        d: dict = {
            "name":         self.name,
            "project_code": self.project_code,
            "board":        self.board,
            "description":  self.description,
            "pins":         {k: v.to_dict() for k, v in self.pins.items()},
            "test_paths":   self.test_paths,
            "instruments":  self.instruments,
        }
        if self.analysis_config:
            d["analysis_config"] = self.analysis_config
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ProjectConfig:
        return cls(
            name            = d["name"],
            project_code    = d["project_code"],
            board           = d["board"],
            description     = d.get("description", ""),
            pins            = {k: PinDef.from_dict(v) for k, v in d.get("pins", {}).items()},
            test_paths      = d.get("test_paths", []),
            instruments     = d.get("instruments", []),
            analysis_config = d.get("analysis_config", ""),
        )

    # ── Importação / exportação CSV ───────────────────────────────────────

    @classmethod
    def pins_from_csv(cls, text: str) -> dict[str, PinDef]:
        """Parseia CSV de pinout e retorna dicionário de PinDefs.

        Formato esperado (cabeçalhos obrigatórios: sinal, porta, pino)::

            sinal,porta,pino,tipo,periferico,funcao,descricao,ativo_baixo
            led,GPIOA,5,GPIO,,,LED verde LD2,false
            uart2_tx,GPIOA,2,UART,USART2,TX,TX do RS-485,false
            adc_vin,GPIOA,0,ADC,ADC1,IN0,Leitura de tensão,false
        """
        reader = csv.DictReader(io.StringIO(text))
        result: dict[str, PinDef] = {}
        for row in reader:
            sig  = row.get("sinal", "").strip()
            port = row.get("porta", "").strip().upper()
            pin  = row.get("pino", "0").strip()
            if not sig or not port:
                continue
            periph = PeripheralRef(
                periph_type = row.get("tipo",       "GPIO").strip().upper() or "GPIO",
                name        = row.get("periferico", "").strip().upper(),
                role        = row.get("funcao",     "").strip().upper(),
            )
            result[sig] = PinDef(
                port        = port,
                pin         = int(pin),
                description = row.get("descricao",   "").strip(),
                active_low  = row.get("ativo_baixo", "false").strip().lower() == "true",
                peripheral  = periph,
            )
        return result

    def to_csv(self) -> str:
        """Exporta o pinout atual para string CSV."""
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["sinal", "porta", "pino", "tipo", "periferico", "funcao",
                    "descricao", "ativo_baixo"])
        for sig, pd in self.pins.items():
            w.writerow([
                sig,
                pd.port,
                pd.pin,
                pd.peripheral.periph_type,
                pd.peripheral.name,
                pd.peripheral.role,
                pd.description,
                "true" if pd.active_low else "false",
            ])
        return out.getvalue()


# ── Singleton ───────────────────────────────────────────────────────────────

_active_project: ProjectConfig | None = None


def get_active_project() -> ProjectConfig | None:
    return _active_project


def set_active_project(project: ProjectConfig) -> None:
    global _active_project
    _active_project = project
