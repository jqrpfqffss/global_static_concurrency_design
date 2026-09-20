int value;
void __disable_irq(void);void __enable_irq(void);
void TIM4_IRQHandler(void){value=1800;}
int main(void){__disable_irq();int snapshot=value;__enable_irq();value=snapshot+1;return 0;}
