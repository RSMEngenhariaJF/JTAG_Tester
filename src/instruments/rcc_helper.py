"""Helpers para leitura do RCC (Reset and Clock Control) do STM32F446.

Lê registradores via PAL para determinar as frequências reais de barramento,
sem depender de nomes de campo do SVD (que variam entre versões).
"""

from __future__ import annotations


_AHB_DIV:  dict[int, int] = {8: 2, 9: 4, 10: 8, 11: 16, 12: 64, 13: 128, 14: 256, 15: 512}
_APB_DIV:  dict[int, int] = {4: 2, 5: 4, 6: 8,  7: 16}


def detect_sysclk(pal) -> int:
    """Retorna a frequência SYSCLK real em Hz lendo RCC_CR e RCC_CFGR/PLLCFGR."""
    cfgr = pal.read_reg("RCC", "CFGR")
    sws  = (cfgr >> 2) & 0x3   # bits [3:2] — System Clock Switch Status

    if sws == 0:          # HSI
        return 16_000_000
    if sws == 1:          # HSE — NUCLEO-F446RE tem 8 MHz na placa
        return 8_000_000

    # sws == 2 ou 3: PLL (sws==3 é PLL_R, apenas F446)
    pllcfgr  = pal.read_reg("RCC", "PLLCFGR")
    pllm     = pllcfgr & 0x3F           # bits [5:0]
    plln     = (pllcfgr >> 6) & 0x1FF   # bits [14:6]
    pllp_enc = (pllcfgr >> 16) & 0x3    # bits [17:16]  0→/2, 1→/4, 2→/6, 3→/8
    pllsrc   = (pllcfgr >> 22) & 0x1    # 0=HSI, 1=HSE

    f_in  = 8_000_000 if pllsrc else 16_000_000
    f_vco = f_in * plln // pllm
    pllp  = 2 * (pllp_enc + 1)
    return f_vco // pllp


def detect_hclk(pal) -> int:
    """Retorna a frequência HCLK (AHB) real em Hz."""
    sysclk = detect_sysclk(pal)
    cfgr   = pal.read_reg("RCC", "CFGR")
    hpre   = (cfgr >> 4) & 0xF    # bits [7:4]
    return sysclk // _AHB_DIV.get(hpre, 1)


def detect_pclk1(pal) -> int:
    """Retorna a frequência PCLK1 (APB1) real em Hz."""
    hclk  = detect_hclk(pal)
    cfgr  = pal.read_reg("RCC", "CFGR")
    ppre1 = (cfgr >> 10) & 0x7   # bits [12:10]
    return hclk // _APB_DIV.get(ppre1, 1)


def detect_pclk2(pal) -> int:
    """Retorna a frequência PCLK2 (APB2) real em Hz.

    USART1, USART6, SPI1, SPI4 são clocked por PCLK2.
    """
    hclk  = detect_hclk(pal)
    cfgr  = pal.read_reg("RCC", "CFGR")
    ppre2 = (cfgr >> 13) & 0x7   # bits [15:13]
    return hclk // _APB_DIV.get(ppre2, 1)
