int value;
void TIM4_IRQHandler(void){value=9;}
int main(void){int first=value;int second=value;return first+second;}
