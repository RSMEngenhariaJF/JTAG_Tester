"""Exemplo — I2C: Scan de dispositivos no barramento I2C1.

Varre endereços 0x08–0x77 e reporta quais responderam ACK.
Útil para confirmar que sensores/EEPROMs estão presentes e energizados.

Conexão sugerida (NUCLEO-F446RE, conector CN10):
    PB8 (D15 = I2C1_SCL)
    PB9 (D14 = I2C1_SDA)

ATENÇÃO: requer resistores de pull-up (4k7 Ω) em SDA e SCL.
Este teste usa os registradores I2C diretamente via PAL — não usa HAL.
"""

from __future__ import annotations

from tests_builtin.base import BuiltinTest, TestResult

# Endereços 7-bit a varrer
_SCAN_START = 0x08
_SCAN_END   = 0x77
_AF_I2C1    = 4    # AF4 para I2C1 no STM32F4


def _i2c1_init(pal, f_pclk1: int = 16_000_000) -> None:
    """Configura I2C1 a 100 kHz em modo standard."""
    # Desabilita I2C para configurar
    pal.modify_field("I2C1", "CR1", "PE", 0)

    freq_mhz = f_pclk1 // 1_000_000
    pal.modify_field("I2C1", "CR2",  "FREQ",  freq_mhz)
    pal.modify_field("I2C1", "CCR",  "CCR",   freq_mhz * 5)   # 100 kHz Sm
    pal.modify_field("I2C1", "TRISE","TRISE", freq_mhz + 1)

    pal.modify_field("I2C1", "CR1", "PE", 1)


def _i2c1_probe(pal, addr7: int) -> bool:
    """Envia START + endereço e retorna True se ACK."""
    import time
    # START
    pal.modify_field("I2C1", "CR1", "START", 1)
    t = time.perf_counter()
    while not pal.read_field("I2C1", "SR1", "SB"):
        if time.perf_counter() - t > 0.01:
            return False

    # Endereço + W (bit 0 = 0)
    pal.write_reg("I2C1", "DR", (addr7 << 1) & 0xFE)
    t = time.perf_counter()
    while True:
        sr1 = pal.read_reg("I2C1", "SR1")
        if sr1 & (1 << 1):   # ADDR
            _ = pal.read_reg("I2C1", "SR2")  # limpa ADDR
            pal.modify_field("I2C1", "CR1", "STOP", 1)
            return True
        if sr1 & (1 << 10):  # AF (NACK)
            pal.modify_field("I2C1", "CR1", "STOP", 1)
            pal.modify_field("I2C1", "SR1", "AF", 0)
            return False
        if time.perf_counter() - t > 0.01:
            pal.modify_field("I2C1", "CR1", "STOP", 1)
            return False


class I2cScanTest(BuiltinTest):
    name        = "I2C1 Bus Scan"
    description = (
        "Varre endereços I2C 0x08–0x77 e lista dispositivos presentes. "
        "Requer pull-ups em PB8 (SCL) e PB9 (SDA)."
    )

    def _run(self, pal) -> TestResult:
        # Habilita clocks
        pal.modify_field("RCC", "AHB1ENR",  "GPIOBEN", 1)
        pal.modify_field("RCC", "APB1ENR",  "I2C1EN",  1)

        # Salva e configura PB8 (SCL) e PB9 (SDA) como AF4 open-drain
        saved = {}
        for pin in [8, 9]:
            saved[f"MODER{pin}"] = pal.read_field("GPIOB", "MODER", f"MODER{pin}")
            saved[f"AFRH{pin}"]  = pal.read_field("GPIOB", "AFRH",  f"AFRH{pin}")
            saved[f"OTYPER{pin}"]= pal.read_field("GPIOB", "OTYPER",f"OT{pin}")
            saved[f"PUPDR{pin}"] = pal.read_field("GPIOB", "PUPDR", f"PUPDR{pin}")
            pal.modify_field("GPIOB", "MODER",  f"MODER{pin}",  0b10)  # AF
            pal.modify_field("GPIOB", "AFRH",   f"AFRH{pin}",   _AF_I2C1)
            pal.modify_field("GPIOB", "OTYPER", f"OT{pin}",      1)    # open-drain
            pal.modify_field("GPIOB", "PUPDR",  f"PUPDR{pin}",   0b01) # pull-up

        try:
            _i2c1_init(pal)
            found: list[int] = []
            for addr in range(_SCAN_START, _SCAN_END + 1):
                if _i2c1_probe(pal, addr):
                    found.append(addr)

            if found:
                addrs = ", ".join(f"0x{a:02X}" for a in found)
                return self._pass(
                    f"{len(found)} dispositivo(s) encontrado(s): {addrs}",
                    measured=found,
                )
            return self._pass(
                "Nenhum dispositivo I2C encontrado (barramento vazio).",
                measured=[],
            )
        finally:
            pal.modify_field("I2C1", "CR1", "PE", 0)
            for pin in [8, 9]:
                pal.modify_field("GPIOB", "MODER",  f"MODER{pin}",  saved[f"MODER{pin}"])
                pal.modify_field("GPIOB", "AFRH",   f"AFRH{pin}",   saved[f"AFRH{pin}"])
                pal.modify_field("GPIOB", "OTYPER", f"OT{pin}",      saved[f"OTYPER{pin}"])
                pal.modify_field("GPIOB", "PUPDR",  f"PUPDR{pin}",   saved[f"PUPDR{pin}"])
            pal.modify_field("RCC", "APB1ENR", "I2C1EN", 0)
