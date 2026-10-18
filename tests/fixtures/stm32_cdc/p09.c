#include "lab.h"

struct Slot { uint32_t generation, value; } g_shared = {1, 10};
volatile uint32_t delivered, delivery_generation;
static struct Slot *Peek(void) { return &g_shared; }
void Lab_Init(void) { Lab_Configure(10, 2); }
void Lab_Low(void) {
 struct Slot *p = Peek(); uint32_t generation = p->generation;
 uint32_t value = p->value; delivery_generation = generation; delivered = value;
}
void Lab_High(void) { g_shared.generation++; g_shared.value = g_shared.generation * 10; }
void Lab_Poll(void) {}

