int value;
void TIM4_IRQHandler(void){value=1800;}
int main(void){int snapshot=value; value=snapshot+1;return 0;}
