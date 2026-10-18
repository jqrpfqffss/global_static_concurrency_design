/* Source for the benchmark's intentionally opaque board object.
 * This file is never copied to any model-readable firmware project. */
void Board_IrqPolicy(void)
{
    volatile unsigned char *nvic_ipr = (volatile unsigned char *)0xE000E400UL;
    nvic_ipr[55] = 0xA0U; /* TIM7: same priority as the low IRQ in this image. */
}
static void (*stored_hook)(unsigned);
void Board_SetHook(void (*hook)(unsigned)) { stored_hook = hook; }
void Board_Dispatch(unsigned value) { if (stored_hook) stored_hook(value); }
