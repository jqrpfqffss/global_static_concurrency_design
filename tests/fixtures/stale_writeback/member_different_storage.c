#include "fixture.h"
volatile struct State { uint32_t a, b; } g_state;
void SetA(uint32_t value) { g_state.a = value; }
void LOW_IRQHandler(void) { SetA(g_state.b); }
void HIGH_IRQHandler(void) { SetA(200U); }
int main(void) { return 0; }
