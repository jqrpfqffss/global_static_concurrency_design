#ifndef ECRA_DIFF_PROBE_H
#define ECRA_DIFF_PROBE_H
#include "main.h"
#include <string.h>

/* Deliberately separate instances in the foreground and IRQ translation units. */
static unsigned probe_header_private;
static inline void Probe_HeaderStep(void) { probe_header_private++; }

typedef void (*ProbeCallback)(void *);
typedef struct { ProbeCallback invoke; void *payload; } ProbeRoute;
typedef struct { unsigned sequence, value; } ProbeFrame;
typedef union { unsigned word; unsigned char bytes[4]; } ProbeOverlay;
typedef struct { unsigned low : 1; unsigned high : 1; } ProbeBits;
typedef struct { unsigned foreground, irq; } ProbeDisjoint;

extern volatile unsigned probe_rmw, probe_lock_removed, probe_race_removed;
extern volatile unsigned probe_stale, probe_masked;
extern unsigned probe_indirect, probe_callback, probe_array[8];
extern volatile unsigned long long probe_wide;
extern ProbeFrame probe_frame;
extern ProbeOverlay probe_overlay;
extern ProbeBits probe_bits;
extern ProbeDisjoint probe_disjoint;
extern const unsigned probe_readonly;
extern const ProbeRoute probe_route;

unsigned *Probe_LocalSlot(void);
unsigned **Probe_SlotBridge(unsigned **slot);
void Probe_Increment(unsigned *slot);
void Probe_Deep1(void);
void Probe_Reentrant(void);
void Probe_IrqBody(void);
void Probe_Foreground(void);
void Probe_Irq(void);
void Probe_Init(void);
#endif
