# Stubs de RAM

Programas pequenos que o host carrega na RAM do MCU via SWD e executa na
velocidade do núcleo. Servem para testes que o caminho PAL (um acesso SWD por
registrador, ~0,3–0,5 ms cada) não consegue fazer: tráfego contínuo, vazão,
BER e medição de tempo com precisão de ciclo.

O lado host fica em `src/core/agent/` (`TargetAgent`, `RingReader`). Guia
completo: seção 12 de `DOC/GUIA_CRIACAO_DE_TESTES.docx`.

## Stubs disponíveis

| Stub | MCU | O que faz | Host |
|---|---|---|---|
| `stm32h7/usart_sweep.c` | STM32H7 (testado em NUCLEO-H743ZI) | Varredura de baud do USART3 em half-duplex (eco pelo PD8, sem fio) | `core/agent/usart_sweep.py`, `tools/agent_usart_sweep.py` |

## Compilar

```
python stubs/build_stubs.py
```

Procura o `arm-none-eabi-gcc` no PATH, em `ARM_GCC_DIR` ou no STM32CubeIDE
(`C:/ST`). Grava o `.bin` em `src/core/agent/bin/` e imprime o sha256. O `.bin`
é versionado — quem só roda testes não precisa do compilador. Os `.elf` ficam
ao lado do fonte e não são versionados.

## Protocolo

1. Host: `reset_and_halt()` e configura clock/GPIO/periférico via SWD.
2. Host: `TargetAgent.load()` grava e confere o `.bin`; preenche a caixa de correio.
3. Host: `TargetAgent.start(entry, sp)` — PC, SP, xPSR (Thumb) e resume.
4. Stub: grava `MAGIC`, `STATUS = RUNNING`, executa e publica registros na fila.
5. Host: `RingReader.drain()` em laço, enquanto o núcleo não para.
6. Stub: `STATUS = DONE` e `BKPT` — o núcleo para.
7. Host: confere `MAGIC`/`STATUS` e faz `reset_system()` para o firmware voltar.

Fila circular: `head` (stub) e `tail` (host) são índices livre-correntes;
`slot = índice % size`; cheia quando `head - tail == size`. O stub grava o
registro, executa `DSB` e só então incrementa `head`.

## Regras para um stub novo

- Função de entrada na seção `.entry` (primeira no binário), `noreturn`.
- Sem variáveis globais: `.data` e `.bss` são descartados (não há startup).
- Interrupções desligadas (`cpsid i`); a pilha é a que o host passar em SP.
- Layout da caixa de correio idêntico no `.c` e no módulo Python.
- Registrar o stub em `STUBS` no `build_stubs.py`.
- Testar o lado host com alvo simulado (ver `tests/unit/test_agent.py`).

## Mapa de memória — STM32H7

| Endereço | Conteúdo |
|---|---|
| `0x24000000` | Código do stub (até 16 KiB, AXI SRAM) |
| `0x24004000` | Caixa de correio: MAGIC, STATUS, parâmetros, head/tail, passos, fila |
| `0x24010000` | `RX_BUF`: bytes recebidos, n por passo |
| `0x20020000` | Topo da pilha (DTCM) |

## Cuidados

- O firmware do produto para durante o teste e volta com reset.
- Placas cujo firmware entra em baixo consumo só aceitam `mode="under-reset"`.
- Acima de 8 Mbaud é preciso ligar o PLL. No H7, `PWR_CR3` só aceita uma
  escrita após o power-up: um valor errado pode impedir o chip de subir.
- Endereços e bits seguem o RM0433 e devem ser revisados antes de virar
  critério de aprovação.
