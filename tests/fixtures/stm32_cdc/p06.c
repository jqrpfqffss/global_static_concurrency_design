#include "lab.h"

struct Record { uint32_t value, version; };
struct Record g_shared;
static void Commit(struct Record *target, const struct Record *copy) { memcpy(target, copy, sizeof(*target)); }
static void Forward(struct Record *target, const struct Record *copy) { Commit(target, copy); }
void Lab_Init(void) { Lab_Configure(10, 2); }
void Lab_Low(void) { struct Record saved; memcpy(&saved, &g_shared, sizeof(saved)); Forward(&g_shared, &saved); }
void Lab_High(void) { g_shared.value = 200; g_shared.version++; }
void Lab_Poll(void) {}

