void use(void){static int value;value++;}
void TIM4_IRQHandler(void){use();}
int main(void){use();return 0;}
