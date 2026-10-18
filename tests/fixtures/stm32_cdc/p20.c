#include "lab.h"

volatile struct Receiver { uint8_t *buffer; uint32_t capacity; } g_shared;
uint8_t storage[8];
void Lab_Init(void) {
 Lab_Configure(10, 2); NVIC_SetPendingIRQ(TIM7_IRQn);
 g_shared.buffer = storage; g_shared.capacity = sizeof(storage);
}
void Lab_Low(void) {}
void Lab_High(void) { if (0U < g_shared.capacity - 1U) g_shared.buffer[0] = 0x55; }
void Lab_Poll(void) {}

