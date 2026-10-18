#ifndef STALE_WRITEBACK_FIXTURE_H
#define STALE_WRITEBACK_FIXTURE_H
typedef unsigned int uint32_t;
_Static_assert(sizeof(uint32_t) == 4, "fixture requires 32-bit values");
enum { LOW_IRQn = 20, HIGH_IRQn = 21 };
void HAL_NVIC_SetPriorityGrouping(unsigned group);
void HAL_NVIC_SetPriority(unsigned irq, unsigned preempt, unsigned sub);
void __disable_irq(void);
void __enable_irq(void);
#ifndef WRITEBACK_ENTRY
#define WRITEBACK_ENTRY() ((void)0)
#endif
#endif
