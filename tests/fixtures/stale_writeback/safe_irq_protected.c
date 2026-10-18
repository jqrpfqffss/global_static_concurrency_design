#include "fixture.h"
volatile uint32_t g_value;
void SetValue(uint32_t value) { g_value = value; }
void LOW_IRQHandler(void)
{
    __disable_irq();
    SetValue(g_value);
    __enable_irq();
}
void HIGH_IRQHandler(void) { SetValue(200U); }
int main(void)
{
    HAL_NVIC_SetPriorityGrouping(3);
    HAL_NVIC_SetPriority(LOW_IRQn, 3, 0);
    HAL_NVIC_SetPriority(HIGH_IRQn, 1, 0);
    return 0;
}
