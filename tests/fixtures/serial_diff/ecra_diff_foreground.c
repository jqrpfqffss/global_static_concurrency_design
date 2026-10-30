#include "ecra_diff_probe.h"

static unsigned probe_same_name;
static unsigned Probe_Snapshot(void) { return probe_stale; }
static void Probe_Commit(unsigned old)
{
    __disable_irq();
    probe_stale = old + 1;
    __enable_irq();
}

void Probe_Init(void) { probe_rmw = 1; }

void Probe_Foreground(void)
{
    ProbeFrame copy;
    unsigned sum = 0;
    probe_rmw = 3;
    __disable_irq();
    probe_lock_removed++;
    __enable_irq();
    probe_race_removed++;
    Probe_Deep1();
    Probe_Reentrant();
    probe_route.invoke(probe_route.payload);
    /* The write is protected; the read-to-writeback transaction is not. */
    Probe_Commit(Probe_Snapshot());
    memcpy(&copy, &probe_frame, sizeof(copy));
    for (unsigned i = 0; i < sizeof(probe_wide); ++i)
        sum += ((const volatile unsigned char *)&probe_wide)[i];
    probe_array[sum & 7U]++;
    probe_overlay.word++;
    probe_bits.low = !probe_bits.low;
    probe_disjoint.foreground++;
    probe_same_name++;
    Probe_HeaderStep();
    __disable_irq();
    probe_masked++;
    __enable_irq();
    (void)probe_readonly;
}
