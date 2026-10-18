#include "fixture.h"
volatile uint32_t g_value, g_other;
void SetValue(uint32_t value) { g_value = value; }
void LOW_IRQHandler(void) { SetValue(g_other); }
void HIGH_IRQHandler(void) { SetValue(200U); }
int main(void) { return 0; }
