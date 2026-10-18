#include "lab.h"

volatile uint32_t g_shared;
volatile uint32_t copied, observed;
void Lab_Init(void) { Lab_DmaConfigure(); }
void Lab_Low(void) {}
void Lab_High(void) {}
void Lab_Poll(void) {
 while (DMA2_Stream0->CR & DMA_SxCR_EN) {}
 g_shared = 0x12345678U; Lab_DmaStart(&g_shared, &copied);
 while (!(DMA2->LISR & (DMA_LISR_TCIF0 | DMA_LISR_TEIF0))) {}
 while (DMA2_Stream0->CR & DMA_SxCR_EN) {}
 __DSB(); if ((DMA2->LISR & DMA_LISR_TCIF0) && copied != 0x12345678U) observed++;
 g_shared = 0;
}

