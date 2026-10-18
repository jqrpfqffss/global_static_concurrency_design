#include "lab.h"

volatile uint32_t g_shared = 4;
uint8_t payload[32], output[8];
void Lab_Init(void) { Lab_Configure(10, 2); }
void Lab_Low(void) { if (g_shared <= sizeof(output)) memcpy(output, payload, g_shared); }
void Lab_High(void) { g_shared = 32; }
void Lab_Poll(void) {}

