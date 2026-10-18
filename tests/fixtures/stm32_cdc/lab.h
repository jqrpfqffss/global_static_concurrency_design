#ifndef ECRA_CDC_LAB_H
#define ECRA_CDC_LAB_H
#include "stm32f4xx_hal.h"
#include <stdint.h>
#include <string.h>
void Lab_Init(void);
void Lab_Poll(void);
void Lab_Low(void);
void Lab_High(void);
void Lab_OnTick(void);
void Lab_Configure(uint32_t low_priority, uint32_t high_priority);
void Lab_DmaConfigure(void);
void Lab_DmaStart(volatile uint32_t *source, volatile uint32_t *destination);
#endif
