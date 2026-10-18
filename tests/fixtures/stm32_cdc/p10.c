#include "lab.h"

volatile uint32_t g_shared;
volatile uint32_t copied, observed;
void Lab_Init(void) { Lab_DmaConfigure(); }
void Lab_Low(void) {}
void Lab_High(void) {}
void Lab_Poll(void) {
 if (!(DMA2_Stream0->CR & DMA_SxCR_EN)) {
  if (DMA2->LISR & DMA_LISR_TCIF0) { if (copied != 0x12345678U) observed++; }
  g_shared = 0x12345678U; Lab_DmaStart(&g_shared, &copied);
  uint32_t mask = __get_PRIMASK(); __disable_irq();
  g_shared = 0; __set_PRIMASK(mask);
 }
}

