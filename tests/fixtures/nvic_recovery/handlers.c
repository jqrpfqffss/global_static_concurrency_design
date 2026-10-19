#include "fixture.h"
void TIM3_IRQHandler(void) {HAL_TIM_IRQHandler(&htim3);}
void TIM4_IRQHandler(void) {HAL_TIM_IRQHandler(&htim4);}
void TIM8_UP_TIM13_IRQHandler(void) {HAL_TIM_IRQHandler(&htim8);HAL_TIM_IRQHandler(&htim13);}
void TIM1_UP_TIM16_IRQHandler(void) {HAL_TIM_IRQHandler(&htim16);}
static void Business_Update(unsigned step) {shared+=step;}
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *h)
{
    if(h->Instance==TIM3) Business_Update(3);
    else if(h->Instance==TIM4) Business_Update(4);
    else if(h->Instance==TIM8) Business_Update(8);
    else if(h->Instance==TIM13) Business_Update(13);
    else if(h->Instance==TIM16) Business_Update(16);
}
extern int main(void);
typedef void (*Vector)(void);
__attribute__((section(".isr_vector"),used))
Vector const vectors[61] = {
    [1]=(Vector)main,
    [16+TIM3_IRQn]=TIM3_IRQHandler,
    [16+TIM4_IRQn]=TIM4_IRQHandler,
    [16+TIM8_UP_TIM13_IRQn]=TIM8_UP_TIM13_IRQHandler,
    [16+TIM1_UP_TIM16_IRQn]=TIM1_UP_TIM16_IRQHandler
};
