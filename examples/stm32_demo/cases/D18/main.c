int value;void __DMB(void);void __DSB(void);
void TIM4_IRQHandler(void){value++;}
int main(void){__DMB();value++;__DSB();return 0;}
