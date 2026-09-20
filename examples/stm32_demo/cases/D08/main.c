int value;
void __disable_irq(void);void __enable_irq(void);
void TIM4_IRQHandler(void){value++;}
int main(void){__disable_irq();value++;__enable_irq();return 0;}
