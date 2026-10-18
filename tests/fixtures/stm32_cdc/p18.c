#include "lab.h"

volatile uint32_t g_shared;
extern void Board_SetHook(void (*hook)(uint32_t));
static void SetValue(uint32_t v) { g_shared = v; }
void Lab_Init(void) { Board_SetHook(SetValue); }
void Lab_Low(void) {}
void Lab_High(void) {}
void Lab_Poll(void) { uint32_t prior = g_shared; SetValue(prior); }

