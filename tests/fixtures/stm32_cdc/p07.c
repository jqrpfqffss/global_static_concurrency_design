#include "lab.h"

volatile uint32_t g_shared;
static void SetValue(uint32_t v) { g_shared = v; }
static void (*const publish)(uint32_t) = SetValue;
static void Dispatch(uint32_t v) { publish(v); }
void Lab_Init(void) { Lab_Configure(10, 2); }
void Lab_Low(void) { Dispatch(g_shared); }
void Lab_High(void) { Dispatch(200); }
void Lab_Poll(void) {}

