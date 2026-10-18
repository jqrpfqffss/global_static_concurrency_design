#include "lab.h"

volatile struct Descriptor { uint32_t length, inverse; } g_shared = {8, ~8U};
volatile uint32_t observed;
void Lab_Init(void) { Lab_Configure(10, 2); }
void Lab_Low(void) { g_shared.length = 16; g_shared.inverse = ~16U; }
void Lab_High(void) { if (g_shared.length != ~g_shared.inverse) observed++; }
void Lab_Poll(void) {}

