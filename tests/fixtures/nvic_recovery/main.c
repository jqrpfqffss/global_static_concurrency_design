#include "fixture.h"
TIM_HandleTypeDef htim3,htim4,htim8,htim13,htim16;
volatile unsigned shared;
int main(void)
{
    HAL_NVIC_SetPriorityGrouping(NVIC_PRIORITYGROUP_2);
    Board_Init();
    while(1) { shared++; }
}
void Board_Init(void)
{
    htim3.Instance=TIM3; HAL_TIM_Base_Init(&htim3);
    htim4.Instance=TIM4; HAL_TIM_Base_Init(&htim4);
    htim8.Instance=TIM8; HAL_TIM_Base_Init(&htim8);
    htim13.Instance=TIM13; HAL_TIM_Base_Init(&htim13);
    htim16.Instance=TIM16; HAL_TIM_Base_Init(&htim16);
}
