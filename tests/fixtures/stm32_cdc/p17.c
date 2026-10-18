#include "lab.h"

volatile uint32_t g_shared;
extern void Board_IrqPolicy(void);
static void SetValue(uint32_t v) { g_shared = v; }
void Lab_Init(void) { Lab_Configure(10, 2); Board_IrqPolicy(); }
void Lab_Low(void) { SetValue(g_shared); }
void Lab_High(void) { SetValue(200); }
void Lab_Poll(void) {}

