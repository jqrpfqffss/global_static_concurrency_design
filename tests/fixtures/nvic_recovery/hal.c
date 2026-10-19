#include "fixture.h"
void HAL_NVIC_SetPriorityGrouping(unsigned group) {(void)group;}
void HAL_NVIC_SetPriority(int irq,unsigned pre,unsigned sub) {(void)irq;(void)pre;(void)sub;}
void HAL_NVIC_EnableIRQ(int irq) {(void)irq;}
__attribute__((weak)) void HAL_TIM_Base_MspInit(TIM_HandleTypeDef *h) {(void)h;}
void HAL_TIM_Base_Init(TIM_HandleTypeDef *h)
{
    if(h && h->State==0) {HAL_TIM_Base_MspInit(h);h->State=1;}
}
void HAL_TIM_IRQHandler(TIM_HandleTypeDef *h) {HAL_TIM_PeriodElapsedCallback(h);}
