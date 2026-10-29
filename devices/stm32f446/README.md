# Arquivos de dispositivo — STM32F446RE (LQFP64)

Esta pasta contém os arquivos de descrição fornecidos pela STMicroelectronics
para o microcontrolador STM32F446RE. Eles **não são gerados pelo projeto** —
devem ser baixados diretamente da ST e colocados aqui.

---

## Arquivos esperados

| Arquivo | Tipo | Usado em |
|---|---|---|
| `STM32F446.svd` | CMSIS-SVD | Camada de periféricos (Sprint 06) |
| `STM32F446_LQFP64.bsd` | BSDL | Boundary Scan — TAP de boundary scan (Sprint 07) |
| `CortexMx.bsd` | BSDL | Boundary Scan — TAP do Cortex debug (Sprint 07) |

---

## Onde baixar

### SVD (`STM32F446.svd`)

**Opção 1 — ST (oficial):**
1. Acesse **st.com** e pesquise "STM32F446RE"
2. Na página do produto, vá em *Design Resources*
3. Baixe o pacote CMSIS-SVD (ou procure por "SVD" na página)

**Opção 2 — repositório cmsis-svd (mais rápido):**
- GitHub: `posimore/cmsis-svd`
- Pasta: `data/STMicro/`
- Arquivo: `STM32F446.svd` (ou `STM32F446x.svd`)

### BSDL (`STM32F446_LQFP64.bsd` + `CortexMx.bsd`)

**Opção 1 — ST (oficial):**
1. Mesma página do produto no st.com
2. *Design Resources* → *BSDL*

**Opção 2 — pacote STM32CubeF4:**
1. Baixe o STM32CubeF4 da ST
2. Os arquivos `.bsd` ficam em `Utilities/PC_Software/` ou pasta similar

---

## Como verificar antes de usar

### SVD
Abra o arquivo e confirme que o elemento raiz contém `STM32F446`.

### BSDL — campos obrigatórios a conferir

```
INSTRUCTION_LENGTH  ... is 5;      -- registrador de instrução de 5 bits
COMPONENT_CONFORMANCE ... is "STD_1149_1_2001";
```

O `BOUNDARY_LENGTH` varia por encapsulamento — para LQFP64 anote o valor
e guarde aqui para referência na suíte de testes.

> **Nota sobre o CortexMx.bsd:** O STM32F4 expõe duas TAPs em série
> (boundary scan + Cortex debug). Ambos os arquivos `.bsd` devem ser
> carregados ao configurar a cadeia JTAG — declarar apenas um quebra
> a contagem total de células.

---

## Informações do dispositivo

| Campo | Valor |
|---|---|
| Família | STM32F4 |
| Core | Cortex-M4 (ARMv7E-M) |
| Package | LQFP64 |
| Flash | 512 KB @ 0x0800_0000 |
| SRAM | 128 KB @ 0x2000_0000 |
| Tensão de operação | **3,3 V** (VDD 1,7 V – 3,6 V) |
| DPIDR esperado | `0x2BA01477` |
