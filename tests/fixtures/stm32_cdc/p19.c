#include "lab.h"

volatile uint32_t g_shared;
void Lab_Init(void) { __HAL_RCC_GPIOD_CLK_ENABLE(); Lab_Configure(10, 2); }
void Lab_Low(void) { g_shared = 1; }
void Lab_High(void) { g_shared = 0; }
void Lab_Poll(void) { uint32_t level = g_shared; GPIOD->BSRR = level ? GPIO_PIN_12 : (GPIO_PIN_12 << 16U); }

