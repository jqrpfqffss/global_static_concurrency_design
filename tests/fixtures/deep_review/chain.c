#include "fixture.h"
volatile uint32_t g_value;
void Setter(uint32_t v) { g_value = v; }
void FunctionB(uint32_t v) { Setter(v); }
void FunctionA(uint32_t v) { FunctionB(v); }
void LOW_IRQHandler(void) { uint32_t old = g_value; FunctionA(old); }
void HIGH_IRQHandler(void) { Setter(200U); }
int main(void)
{
    HAL_NVIC_SetPriorityGrouping(3);
    HAL_NVIC_SetPriority(LOW_IRQn, 3, 0);
    HAL_NVIC_SetPriority(HIGH_IRQn, 1, 0);
    return 0;
}
