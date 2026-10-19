#include "fixture.h"
static void SetIRQ(int irq,unsigned pre,unsigned sub)
{
    unsigned local=pre+0U;
    HAL_NVIC_SetPriority(irq,local,sub);
    HAL_NVIC_EnableIRQ(irq);
}
void HAL_TIM_Base_MspInit(TIM_HandleTypeDef *h)
{
    if(h->Instance==TIM3) {SetIRQ(TIM3_IRQn,3,0);}
    else if(h->Instance==TIM4) {SetIRQ(TIM4_IRQn,2,1);}
    else if(h->Instance==TIM8) {SetIRQ(TIM8_UP_TIM13_IRQn,1,2);}
    else if(h->Instance==TIM13) {SetIRQ(TIM8_UP_TIM13_IRQn,1,2);}
    else if(h->Instance==TIM16) {SetIRQ(TIM1_UP_TIM16_IRQn,0,3);}
}
