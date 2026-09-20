enum{TIM4_IRQn=30};
#define GROUP (3U)
#define PRIORITY (2+3)
int value;
void __set_BASEPRI(unsigned);void HAL_NVIC_SetPriorityGrouping(unsigned);void HAL_NVIC_SetPriority(int,unsigned,unsigned);
void TIM4_IRQHandler(void){value++;}
int main(void){HAL_NVIC_SetPriorityGrouping(GROUP);HAL_NVIC_SetPriority(TIM4_IRQn,PRIORITY,0);__set_BASEPRI(0x50);value++;__set_BASEPRI(0);return 0;}
