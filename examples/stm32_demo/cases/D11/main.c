int value;
void __set_BASEPRI(unsigned);
void TIM4_IRQHandler(void){value++;}
int main(void){__set_BASEPRI(0x50);value++;__set_BASEPRI(0);return 0;}
