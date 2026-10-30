"""HAL de bancada — acesso a periféricos do MCU via PAL (SWD), independente de família.

Cada módulo escolhe a implementação pela geração do periférico, detectada no SVD:

    uart  — USART v1 (F1/F2/F4: SR/DR) e v2 (F7/H7/G0/L4: ISR/TDR/RDR)
    spi   — SPI v1 (F4: CR1/SR/DR) e v2 (H7: CFG1/CFG2/TXDR/RXDR)
    i2c   — I2C v1 (F4: SR1/SR2/CCR) e v2 (F7/H7/G0: TIMINGR/ISR)
    exti  — EXTI simples (F4: IMR/PR) e com núcleo (H7: CPUIMR1/CPUPR1)
    can   — bxCAN (F4) e FDCAN (H7), modo loopback interno
    eth   — MAC Ethernet: leitura de registradores do PHY por MDIO

Regras comuns: o bloco salva os registradores que altera e os restaura no fim;
clocks de periférico ligados pelo teste ficam ligados (inofensivo e evita
derrubar um periférico que o firmware usa).

Os bits e endereços seguem os manuais de referência (RM0390 F446, RM0433 H7) e
precisam de validação em bancada antes de virar critério de aprovação.
"""
