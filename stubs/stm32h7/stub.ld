/* Stub de RAM STM32H7 — código em AXI SRAM, sem .data/.bss (sem startup). */
MEMORY
{
    CODE (rwx) : ORIGIN = 0x24000000, LENGTH = 16K   /* caixa de correio em 0x24004000 */
}

ENTRY(stub_entry)

SECTIONS
{
    .text :
    {
        KEEP(*(.entry))
        *(.text*)
        *(.rodata*)
    } > CODE

    /DISCARD/ : { *(.data*) *(.bss*) *(.ARM.*) *(.comment) }
}

ASSERT(SIZEOF(.text) <= 0x4000, "stub maior que 16 KiB: invade a caixa de correio")
