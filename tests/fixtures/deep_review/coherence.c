#include "fixture.h"
volatile uint32_t g_value, g_length;
volatile uint32_t g_mixed;
void LOW_IRQHandler(void)
{
    g_value = 8U;
    g_length = 8U;
}
void HIGH_IRQHandler(void)
{
    /* This check encodes the actual relation; review must inspect both fields. */
    if (g_value != g_length) g_mixed = 1U;
}
int main(void)
{
    HAL_NVIC_SetPriorityGrouping(3);
    HAL_NVIC_SetPriority(LOW_IRQn, 3, 0);
    HAL_NVIC_SetPriority(HIGH_IRQn, 1, 0);
    return 0;
}
