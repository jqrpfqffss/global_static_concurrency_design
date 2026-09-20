int value;void Enter(void);void Leave(void);
void TIM4_IRQHandler(void){value++;}
int main(void){Enter();value++;Leave();return 0;}
