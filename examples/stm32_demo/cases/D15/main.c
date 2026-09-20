unsigned char value[16];
void HAL_UART_Receive_DMA(void*,unsigned char*,unsigned);
void HAL_UART_RxCpltCallback(void){}
int main(void){HAL_UART_Receive_DMA(0,value,16);value[0]=1;return 0;}
