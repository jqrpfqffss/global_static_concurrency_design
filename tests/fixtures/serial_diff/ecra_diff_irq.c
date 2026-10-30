#include "ecra_diff_probe.h"

static unsigned probe_same_name;
static void Probe_Dispatch3(const ProbeRoute *route) { route->invoke(route->payload); }
static void Probe_Dispatch2(const ProbeRoute *route) { Probe_Dispatch3(route); }
static void Probe_Dispatch1(void) { Probe_Dispatch2(&probe_route); }

/* Compiled in both versions: only a distant caller is changed in the delta. */
void Probe_IrqBody(void)
{
    Probe_Deep1();
    Probe_Reentrant();
    Probe_Dispatch1();
    probe_stale += 100;
    probe_frame.sequence++;
    probe_frame.value = probe_frame.sequence * 7U;
    probe_wide++;
    probe_array[2]++;
    ((unsigned char *)&probe_overlay)[0] ^= 0x80U;
    probe_bits.high = !probe_bits.high;
}

void Probe_Irq(void)
{
    probe_rmw = 5;
    probe_lock_removed++;
    probe_race_removed++;
    probe_masked++;
    probe_disjoint.irq++;
    probe_same_name++;
    Probe_HeaderStep();
    (void)probe_readonly;
    /* DELTA_ACTIVATE_DEEP_IRQ */
}
