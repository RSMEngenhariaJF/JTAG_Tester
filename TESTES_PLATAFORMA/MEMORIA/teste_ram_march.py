"""Exemplo — MEMÓRIA: March-C- (teste clássico de integridade de RAM).

Executa um padrão March-C- em uma região de SRAM para detectar:
    - Stuck-at faults  (bit preso em 0 ou 1)
    - Transition faults (bit que não muda)
    - Coupling faults   (um bit afetando outro)

A região testada é calculada automaticamente a partir do sram_base
do BoardConfig (últimos SIZE_WORDS × 4 bytes da SRAM, antes do limite).

ATENÇÃO: a região testada NÃO pode coincidir com stack/heap do firmware.
         Use sempre uma área segura acima do uso esperado do firmware.
"""

from __future__ import annotations

from tests_builtin.base import BuiltinTest, TestResult

# ─── Configure o tamanho da região a testar ───────────────────────────────────
SIZE_WORDS  = 256    # 256 × 4 bytes = 1 KB
OFFSET_KB   = 124   # início em sram_base + OFFSET_KB × 1024
# Ex. STM32F446 (128 KB SRAM): offset 124 KB → últimos 4 KB livres
# ─────────────────────────────────────────────────────────────────────────────


class MarchCMinusTest(BuiltinTest):
    name        = "RAM March-C-"
    description = (
        f"March-C- em {SIZE_WORDS * 4} bytes a {OFFSET_KB} KB do sram_base. "
        "Detecta stuck-at, transition e coupling faults."
    )

    def _run(self, pal) -> TestResult:
        # Endereço base vem do BoardConfig — portável entre chips
        from core.board.config import get_active_board
        cfg        = get_active_board()
        start_addr = cfg.sram_base + OFFSET_KB * 1024

        mem   = pal.mem
        addrs = [start_addr + i * 4 for i in range(SIZE_WORDS)]

        # Salva conteúdo original
        original = [mem.read_mem32(a) for a in addrs]

        try:
            errors: list[str] = []

            def check(addr: int, expected: int, phase: str) -> None:
                got = mem.read_mem32(addr)
                if got != expected:
                    errors.append(
                        f"{phase} @ 0x{addr:08X}: "
                        f"esperado 0x{expected:08X} lido 0x{got:08X}"
                    )

            W0 = 0x0000_0000
            W1 = 0xFFFF_FFFF

            # M0: escreve 0 em ordem crescente
            for a in addrs:
                mem.write_mem32(a, W0)

            # M1: lê 0, escreve 1 (crescente)
            for a in addrs:
                check(a, W0, "M1r")
                mem.write_mem32(a, W1)

            # M2: lê 1, escreve 0 (crescente)
            for a in addrs:
                check(a, W1, "M2r")
                mem.write_mem32(a, W0)

            # M3: lê 0, escreve 1 (decrescente)
            for a in reversed(addrs):
                check(a, W0, "M3r")
                mem.write_mem32(a, W1)

            # M4: lê 1, escreve 0 (decrescente)
            for a in reversed(addrs):
                check(a, W1, "M4r")
                mem.write_mem32(a, W0)

            # M5: lê 0 (crescente) — verificação final
            for a in addrs:
                check(a, W0, "M5r")

            if not errors:
                return self._pass(
                    f"March-C- OK em {SIZE_WORDS * 4} bytes "
                    f"@ 0x{start_addr:08X}",
                    measured=0, expected=0,
                )
            return self._fail(
                f"{len(errors)} erro(s): {errors[0]}"
                + (f" (+{len(errors) - 1} mais)" if len(errors) > 1 else ""),
                measured=len(errors), expected=0,
            )

        finally:
            for a, v in zip(addrs, original):
                mem.write_mem32(a, v)
