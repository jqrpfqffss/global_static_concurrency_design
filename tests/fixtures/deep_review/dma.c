#include "fixture.h"
uint32_t g_value[2];
volatile uint32_t dma_busy;
volatile uint32_t sample;
/* Board DMA writes both elements independently while dma_busy is set.
 * dma_busy is cleared by its completion IRQ, not by CPU interrupt masking.
 * The board_start_rx implementation and register setup are external. */
void board_start_rx(uint32_t *buffer, unsigned count);
void LOW_IRQHandler(void)
{
    __disable_irq();
    if (dma_busy) sample = g_value[0] + g_value[1];
    __enable_irq();
}
void HIGH_IRQHandler(void) { dma_busy = 0U; }
int main(void)
{
    dma_busy = 1U;
    board_start_rx(g_value, 2U);
    HAL_NVIC_SetPriorityGrouping(3);
    HAL_NVIC_SetPriority(LOW_IRQn, 3, 0);
    HAL_NVIC_SetPriority(HIGH_IRQn, 1, 0);
    return 0;
}
