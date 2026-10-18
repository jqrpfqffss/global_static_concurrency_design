#include "fixture.h"
volatile struct State { uint32_t a, b; } g_state;
void SetA(uint32_t value) { g_state.a = value; }
void Forward(uint32_t value) { SetA(value); }
void LOW_IRQHandler(void) { Forward(g_state.a); }
void HIGH_IRQHandler(void) { SetA(200U); }
int main(void) { return 0; }
