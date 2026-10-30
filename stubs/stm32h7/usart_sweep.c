/*
 * usart_sweep.c — stub de RAM para STM32H7: varredura de baud rate do USART.
 *
 * Carregado pelo host (core/agent) em 0x24000000 (AXI SRAM) e executado com o
 * núcleo saído de reset (HSI 64 MHz, sem cache, sem interrupções).
 *
 * O host configura clock, GPIO e USART (CR3.HDSEL = half-duplex) via SWD e
 * preenche a caixa de correio. Para cada passo o stub programa o BRR, transmite
 * N bytes de um padrão pseudoaleatório, lê o próprio eco pelo pino TX, grava os
 * bytes recebidos em RX_BUF e publica um registro na fila circular. O host
 * esvazia a fila enquanto o stub roda. No fim: STATUS = DONE e BKPT (núcleo para).
 *
 * O layout da caixa de correio deve ser idêntico ao de src/core/agent/usart_sweep.py.
 */

#include <stdint.h>

#define REG(a)      (*(volatile uint32_t *)(a))
#define MBOX        ((volatile uint32_t *)0x24004000u)
#define RX_BUF      ((volatile uint8_t *)0x24010000u)

/* Caixa de correio (índices de palavra) */
enum {
    M_MAGIC = 0, M_STATUS, M_NSTEPS, M_NBYTES, M_USART, M_HEAD, M_TAIL, M_RBSIZE,
};
#define STEPS_OFF   16u     /* 3 palavras por passo: brr, cr1_extra, timeout_ciclos */
#define RB_OFF      128u    /* fila: RBSIZE registros de 8 palavras */
#define REC_WORDS   8u

#define MAGIC       0x53545542u     /* "STUB" */
#define ST_RUNNING  1u
#define ST_DONE     2u

/* USART (RM0433) */
#define CR1     0x00u
#define BRR     0x0Cu
#define ISR     0x1Cu
#define ICR     0x20u
#define RDR     0x24u
#define TDR     0x28u
#define CR1_UE      (1u << 0)
#define CR1_RE      (1u << 2)
#define CR1_TE      (1u << 3)
#define CR1_FIFOEN  (1u << 29)
#define ISR_FE      (1u << 1)
#define ISR_NE      (1u << 2)
#define ISR_ORE     (1u << 3)
#define ISR_RXFNE   (1u << 5)
#define ISR_TXFNF   (1u << 7)
#define ISR_TEACK   (1u << 21)
#define ISR_REACK   (1u << 22)
#define ICR_ALL     0x5Fu

/* DWT — contador de ciclos */
#define DEMCR       REG(0xE000EDFCu)
#define DWT_CTRL    REG(0xE0001000u)
#define DWT_CYCCNT  REG(0xE0001004u)
#define DWT_LAR     REG(0xE0001FB0u)

#define WINDOW      8u      /* bytes em trânsito: não estoura a FIFO de RX (16) */

static inline uint8_t pattern(uint32_t i)
{
    return (uint8_t)((i * 2654435761u) >> 24);
}

__attribute__((noreturn, section(".entry")))
void stub_entry(void)
{
    __asm volatile ("cpsid i");

    DEMCR |= 1u << 24;              /* TRCENA */
    DWT_LAR = 0xC5ACCE55u;          /* destrava o DWT (Cortex-M7) */
    DWT_CYCCNT = 0;
    DWT_CTRL |= 1u;                 /* CYCCNTENA */

    const uint32_t u      = MBOX[M_USART];
    const uint32_t n      = MBOX[M_NBYTES];
    const uint32_t nsteps = MBOX[M_NSTEPS];
    const uint32_t rbsize = MBOX[M_RBSIZE];

    MBOX[M_MAGIC]  = MAGIC;
    MBOX[M_STATUS] = ST_RUNNING;

    for (uint32_t s = 0; s < nsteps; s++) {
        const uint32_t brr  = MBOX[STEPS_OFF + 3u * s];
        const uint32_t cr1x = MBOX[STEPS_OFF + 3u * s + 1u];
        const uint32_t tmo  = MBOX[STEPS_OFF + 3u * s + 2u];
        volatile uint8_t *rxbuf = RX_BUF + s * n;

        REG(u + CR1) = 0;
        REG(u + BRR) = brr;
        REG(u + ICR) = ICR_ALL;
        REG(u + CR1) = cr1x | CR1_FIFOEN | CR1_TE | CR1_RE | CR1_UE;

        uint32_t t0 = DWT_CYCCNT;
        while ((REG(u + ISR) & (ISR_TEACK | ISR_REACK)) != (ISR_TEACK | ISR_REACK)) {
            if (DWT_CYCCNT - t0 > tmo) break;
        }
        while (REG(u + ISR) & ISR_RXFNE) (void)REG(u + RDR);   /* descarta lixo */
        REG(u + ICR) = ICR_ALL;

        uint32_t tx = 0, rx = 0, err = 0, ore = 0, fe = 0, ne = 0;
        t0 = DWT_CYCCNT;
        while (rx < n) {
            const uint32_t isr = REG(u + ISR);
            if (isr & ISR_RXFNE) {
                if (isr & (ISR_FE | ISR_NE | ISR_ORE)) {
                    fe  += (isr & ISR_FE)  ? 1u : 0u;
                    ne  += (isr & ISR_NE)  ? 1u : 0u;
                    ore += (isr & ISR_ORE) ? 1u : 0u;
                    REG(u + ICR) = isr & (ISR_FE | ISR_NE | ISR_ORE);
                }
                const uint8_t b = (uint8_t)REG(u + RDR);
                rxbuf[rx] = b;
                if (b != pattern(rx)) err++;
                rx++;
            } else if (tx < n && (isr & ISR_TXFNF) && (tx - rx) < WINDOW) {
                REG(u + TDR) = pattern(tx);
                tx++;
            }
            if (DWT_CYCCNT - t0 > tmo) break;
        }
        const uint32_t cycles = DWT_CYCCNT - t0;
        REG(u + CR1) = 0;

        /* Publica o registro; espera o host liberar espaço se a fila estiver cheia */
        while (MBOX[M_HEAD] - MBOX[M_TAIL] >= rbsize) { }
        volatile uint32_t *rec = &MBOX[RB_OFF + (MBOX[M_HEAD] % rbsize) * REC_WORDS];
        rec[0] = s;
        rec[1] = brr;
        rec[2] = tx;
        rec[3] = rx;
        rec[4] = err;
        rec[5] = ore;
        rec[6] = (fe << 16) | (ne & 0xFFFFu);
        rec[7] = cycles;
        __asm volatile ("dsb" ::: "memory");
        MBOX[M_HEAD] = MBOX[M_HEAD] + 1u;
    }

    MBOX[M_STATUS] = ST_DONE;
    __asm volatile ("dsb" ::: "memory");
    for (;;) {
        __asm volatile ("bkpt #0");
    }
}
