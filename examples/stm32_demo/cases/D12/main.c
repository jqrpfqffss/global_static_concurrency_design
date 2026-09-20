int value; void (*hook)(void);
void TIM4_IRQHandler(void){value++;}
int main(void){hook();value++;return 0;}
