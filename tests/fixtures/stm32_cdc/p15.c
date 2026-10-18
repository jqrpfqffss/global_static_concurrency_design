#include "lab.h"

volatile uint32_t g_shared;
static void SetValue(uint32_t v) { g_shared = v; }
void Lab_Init(void) { Lab_Configure(10, 2); }
void Lab_Low(void) {
 uint32_t mask = __get_BASEPRI(); __set_BASEPRI(0x10); __DSB(); __ISB();
 uint32_t v = g_shared; SetValue(v); __set_BASEPRI(mask);
}
void Lab_High(void) { SetValue(200); }
void Lab_Poll(void) {}

