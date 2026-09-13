#include "shared.h"
static int state;

void USART1_IRQHandler(void)
{
    state++;
    g_counter++;
    HeaderUpdate();
}
