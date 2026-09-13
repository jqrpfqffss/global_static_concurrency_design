#include "shared.h"

volatile uint32_t g_counter;
uint16_t g_msgSP;
static int state;
static const uint32_t lookup_table[] = {1, 2, 3};
static int never_referenced;
static unsigned char rx_buffer[32];
struct Packet { unsigned flag:1; unsigned value; } g_packet;
static int *global_pointer;
void taskENTER_CRITICAL(void);
void taskEXIT_CRITICAL(void);
void HAL_UART_Receive_DMA(void *uart, unsigned char *buffer, unsigned length);
void *memcpy(void *dst, const void *src, unsigned length);
int xTaskCreate(void (*entry)(void *), const char *, unsigned, void *, unsigned, void *);

static void ParseByte(void)
{
    static unsigned parser_state;
    parser_state++;
}

void Work(void)
{
    g_counter = g_counter + 1;
    ParseByte();
    HeaderUpdate();
}

void TIM4_IRQHandler(void)
{
    g_counter++;
    g_msgSP = 1800;
    state = 1;
    g_packet.flag = 1;
    Work();
}

void ControlTask(void *argument)
{
    (void)argument;
    taskENTER_CRITICAL();
    g_counter += 2;
    taskEXIT_CRITICAL();
    state = 2;
    g_packet.value = 3;
    Work();
}

void ECAT_Task(void)
{
    uint16_t snapshot = g_msgSP;
    Work();
    g_msgSP = snapshot;
    int *alias = &state;
    *alias = 42;
    global_pointer = alias;
    *global_pointer = 9;
    rx_buffer[g_counter & 31] = 1;
    HAL_UART_Receive_DMA(0, rx_buffer, sizeof(rx_buffer));
}

void UnknownCallback(void)
{
    static unsigned parser_state;
    parser_state++;
    g_counter++;
}

int main(void)
{
    xTaskCreate(ControlTask, "control", 128, 0, 1, 0);
    for (;;) { ECAT_Task(); }
}
