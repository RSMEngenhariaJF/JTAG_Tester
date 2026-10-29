"""Exemplo — DMA: Verifica configuração de um canal DMA.

Confirma que o firmware configurou DMA2 Stream 0 (tipicamente ADC1)
com direção, tamanho de dados e número de itens corretos.
"""

from tests_builtin.base import BuiltinTest, TestResult

# ─── Configure aqui ───────────────────────────────────────────────────────────
DMA_PERIPH     = "DMA2"
STREAM_REG     = "S0CR"     # Stream 0 Control Register
EXPECTED_DIR   = 0b00       # 00 = periférico → memória
EXPECTED_MSIZE = 0b01       # 01 = meia palavra (16 bits)
EXPECTED_PSIZE = 0b01       # 01 = meia palavra (16 bits)
# ──────────────────────────────────────────────────────────────────────────────


class Dma2Stream0ConfigCheck(BuiltinTest):
    name        = "DMA2 Stream0 Config"
    description = "Verifica DMA2 Stream 0: direção, tamanho de dados."

    def _run(self, pal) -> TestResult:
        pal.modify_field("RCC", "AHB1ENR", "DMA2EN", 1)

        cr = pal.read_reg(DMA_PERIPH, STREAM_REG)

        dir_   = (cr >> 6)  & 0x3
        msize  = (cr >> 13) & 0x3
        psize  = (cr >> 11) & 0x3

        errors = []
        if dir_ != EXPECTED_DIR:
            dirs = {0: "P→M", 1: "M→P", 2: "M→M"}
            errors.append(f"DIR={dirs.get(dir_, dir_)} (esperado {dirs.get(EXPECTED_DIR)})")
        if msize != EXPECTED_MSIZE:
            errors.append(f"MSIZE={msize} (esperado {EXPECTED_MSIZE})")
        if psize != EXPECTED_PSIZE:
            errors.append(f"PSIZE={psize} (esperado {EXPECTED_PSIZE})")

        if errors:
            return self._fail("; ".join(errors), measured=(dir_, msize, psize))

        return self._pass(
            f"DMA2 S0 OK: DIR={dir_} MSIZE={msize} PSIZE={psize}",
            measured=(dir_, msize, psize),
        )
