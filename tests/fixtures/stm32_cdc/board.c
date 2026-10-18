#include "lab.h"

void Lab_Configure(uint32_t low_priority, uint32_t high_priority)
{
    __HAL_RCC_TIM6_CLK_ENABLE();
    __HAL_RCC_TIM7_CLK_ENABLE();
    HAL_NVIC_SetPriorityGrouping(NVIC_PRIORITYGROUP_4);
    HAL_NVIC_SetPriority(TIM6_DAC_IRQn, low_priority, 0);
    HAL_NVIC_SetPriority(TIM7_IRQn, high_priority, 0);
    TIM6->CR1 = 0;
    TIM7->CR1 = 0;
    TIM6->PSC = 84 - 1;
    TIM7->PSC = 84 - 1;
    TIM6->ARR = 1000 - 1;
    TIM7->ARR = 997 - 1;
    TIM6->EGR = TIM_EGR_UG;
    TIM7->EGR = TIM_EGR_UG;
    TIM6->SR = 0;
    TIM7->SR = 0;
    HAL_NVIC_ClearPendingIRQ(TIM6_DAC_IRQn);
    HAL_NVIC_ClearPendingIRQ(TIM7_IRQn);
    TIM6->DIER = TIM_DIER_UIE;
    TIM7->DIER = TIM_DIER_UIE;
    HAL_NVIC_EnableIRQ(TIM6_DAC_IRQn);
    HAL_NVIC_EnableIRQ(TIM7_IRQn);
    TIM6->CR1 = TIM_CR1_CEN;
    TIM7->CR1 = TIM_CR1_CEN;
}

void TIM6_DAC_IRQHandler(void)
{
    TIM6->SR = 0;
    Lab_Low();
}

void TIM7_IRQHandler(void)
{
    TIM7->SR = 0;
    Lab_High();
}

void Lab_DmaConfigure(void)
{
    __HAL_RCC_DMA2_CLK_ENABLE();
    DMA2_Stream0->CR &= ~DMA_SxCR_EN;
    while (DMA2_Stream0->CR & DMA_SxCR_EN) {}
    DMA2->LIFCR = DMA_LIFCR_CTCIF0 | DMA_LIFCR_CHTIF0 |
                  DMA_LIFCR_CTEIF0 | DMA_LIFCR_CDMEIF0 | DMA_LIFCR_CFEIF0;
    /* DMA2 supports software-triggered memory-to-memory transfers. */
    DMA2_Stream0->CR = DMA_SxCR_DIR_1 | DMA_SxCR_PSIZE_1 | DMA_SxCR_MSIZE_1;
    DMA2_Stream0->FCR = DMA_SxFCR_DMDIS;
}

void Lab_DmaStart(volatile uint32_t *source, volatile uint32_t *destination)
{
    DMA2->LIFCR = DMA_LIFCR_CTCIF0 | DMA_LIFCR_CHTIF0 |
                  DMA_LIFCR_CTEIF0 | DMA_LIFCR_CDMEIF0 | DMA_LIFCR_CFEIF0;
    DMA2_Stream0->PAR = (uint32_t)source;
    DMA2_Stream0->M0AR = (uint32_t)destination;
    DMA2_Stream0->NDTR = 1;
    __DMB();
    DMA2_Stream0->CR |= DMA_SxCR_EN;
}
