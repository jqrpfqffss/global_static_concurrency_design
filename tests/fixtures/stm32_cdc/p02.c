#include "lab.h"

volatile uint32_t g_shared;
static void SetValue(uint32_t v) { g_shared = v; }
static void C(uint32_t v) { SetValue(v); }
static void B(uint32_t v) { C(v); }
static void A(uint32_t v) { B(v); }
void Lab_Init(void) { Lab_Configure(10, 2); }
void Lab_Low(void) { uint32_t previous = g_shared; A(previous); }
void Lab_High(void) { SetValue(200); }
void Lab_Poll(void) {}

