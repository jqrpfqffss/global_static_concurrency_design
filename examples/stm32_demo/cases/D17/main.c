int value;void APP_Lock(void){} void APP_Unlock(void){}
void TIM4_IRQHandler(void){value++;}
int main(void){APP_Lock();value++;APP_Unlock();return 0;}
