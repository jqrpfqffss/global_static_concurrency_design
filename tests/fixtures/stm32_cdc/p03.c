#include "lab.h"

volatile uint32_t g_shared;
static void SetValue(uint32_t v) {
 uint32_t mask = __get_PRIMASK(); __disable_irq();
 g_shared = v; __set_PRIMASK(mask);
}
void Lab_Init(void) { Lab_Configure(10, 2); }
void Lab_Low(void) { uint32_t previous = g_shared; SetValue(previous); }
void Lab_High(void) { SetValue(200); }
void Lab_Poll(void) {}

