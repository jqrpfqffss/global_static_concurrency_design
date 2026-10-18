/* Host replay injects HIGH on entry to LOW's setter, after argument loading. */
#include <assert.h>
#include <stdio.h>
static void preempt_after_argument_load(void);
#define WRITEBACK_ENTRY() preempt_after_argument_load()
#define main firmware_main
#include "unsafe_direct_writeback.c"
#undef main
static int inject_high;
void HAL_NVIC_SetPriorityGrouping(unsigned group) { (void)group; }
void HAL_NVIC_SetPriority(unsigned irq, unsigned preempt, unsigned sub)
{ (void)irq; (void)preempt; (void)sub; }
static void preempt_after_argument_load(void)
{
    if (inject_high) {
        inject_high = 0;
        assert(g_value == 100U);
        HIGH_IRQHandler();
        assert(g_value == 200U);
    }
}
int main(void)
{
    SetValue(100U);
    inject_high = 1;
    LOW_IRQHandler();
    assert(g_value == 100U);
    puts("READ 100 -> HIGH WRITE 200 -> LOW WRITEBACK 100; final=100");
    return 0;
}
