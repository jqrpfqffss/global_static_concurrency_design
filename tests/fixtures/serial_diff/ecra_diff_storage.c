#include "ecra_diff_probe.h"

volatile unsigned probe_rmw, probe_lock_removed, probe_race_removed;
volatile unsigned probe_stale, probe_masked;
unsigned probe_indirect, probe_callback, probe_array[8];
volatile unsigned long long probe_wide;
ProbeFrame probe_frame;
ProbeOverlay probe_overlay;
ProbeBits probe_bits;
ProbeDisjoint probe_disjoint;
const unsigned probe_readonly = 17;
unsigned probe_deleted;
static unsigned probe_untouched;

unsigned *Probe_LocalSlot(void)
{
    static unsigned hidden_epoch;
    return &hidden_epoch;
}

unsigned **Probe_SlotBridge(unsigned **slot) { return slot; }
void Probe_Increment(unsigned *slot) { (*slot)++; }
static void Probe_Deep6(unsigned **slot) { Probe_Increment(*slot); }
static void Probe_Deep5(unsigned **slot) { Probe_Deep6(Probe_SlotBridge(slot)); }
static void Probe_Deep4(unsigned **slot) { Probe_Deep5(slot); }
static void Probe_Deep3(unsigned **slot) { Probe_Deep4(slot); }
static void Probe_Deep2(unsigned **slot) { Probe_Deep3(slot); }
void Probe_Deep1(void)
{
    unsigned *alias = &probe_indirect;
    Probe_Deep2(&alias);
    alias = Probe_LocalSlot();
    Probe_Deep2(&alias);
}

void Probe_Reentrant(void)
{
    static unsigned hidden_scratch;
    hidden_scratch++;
}

static void Probe_CallbackBody(void *payload) { Probe_Increment(payload); }
const ProbeRoute probe_route = { Probe_CallbackBody, &probe_callback };

/* A real vector entry unconnected to any edited code or shared state. */
void EXTI4_IRQHandler(void) { probe_untouched++; }
