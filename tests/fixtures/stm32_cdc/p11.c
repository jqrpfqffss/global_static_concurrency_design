#include "lab.h"

volatile uint32_t g_shared;
void Lab_OnTick(void) { g_shared++; }
void Lab_Init(void) { HAL_NVIC_SetPriority(SysTick_IRQn, 15, 0); Lab_Configure(10, 2); }
void Lab_Low(void) {}
void Lab_High(void) { uint32_t start = g_shared; while (g_shared == start) { __NOP(); } }
void Lab_Poll(void) {}

