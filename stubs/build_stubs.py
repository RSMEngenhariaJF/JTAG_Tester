"""Compila os stubs de RAM e grava os .bin em src/core/agent/bin/.

Uso (a partir da raiz do repositório):
    python stubs/build_stubs.py

Procura o arm-none-eabi-gcc no PATH, em ARM_GCC_DIR ou no STM32CubeIDE (C:/ST).
Os .bin gerados são versionados: quem só roda os testes não precisa do compilador.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "core" / "agent" / "bin"

# (nome do .bin, fonte, linker script, cpu)
STUBS = [
    ("stm32h7_usart_sweep.bin", "stm32h7/usart_sweep.c", "stm32h7/stub.ld", "cortex-m7"),
]

CFLAGS = [
    "-mthumb", "-O2", "-ffreestanding", "-nostdlib", "-fno-builtin",
    "-Wall", "-Wextra", "-Werror", "-g",
]


def find_gcc() -> Path:
    exe = "arm-none-eabi-gcc" + (".exe" if os.name == "nt" else "")
    if found := shutil.which(exe):
        return Path(found)
    if env := os.environ.get("ARM_GCC_DIR"):
        return Path(env) / exe
    pattern = f"STM32CubeIDE*/STM32CubeIDE/plugins/*gnu-tools*/tools/bin/{exe}"
    for cand in sorted(Path("C:/ST").glob(pattern)):
        return cand
    sys.exit("arm-none-eabi-gcc não encontrado — instale o STM32CubeIDE ou defina ARM_GCC_DIR")


def main() -> None:
    gcc = find_gcc()
    objcopy = gcc.with_name(gcc.name.replace("gcc", "objcopy"))
    OUT.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).resolve().parent
    for name, src, ld, cpu in STUBS:
        elf = here / Path(src).with_suffix(".elf")
        subprocess.run(
            [str(gcc), f"-mcpu={cpu}", *CFLAGS, "-T", str(here / ld),
             "-o", str(elf), str(here / src)],
            check=True,
        )
        subprocess.run([str(objcopy), "-O", "binary", str(elf), str(OUT / name)], check=True)
        data = (OUT / name).read_bytes()
        print(f"{name}: {len(data)} bytes  sha256={hashlib.sha256(data).hexdigest()[:16]}")


if __name__ == "__main__":
    main()
