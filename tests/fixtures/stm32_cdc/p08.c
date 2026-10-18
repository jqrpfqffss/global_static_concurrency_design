#include "lab.h"

volatile uint32_t g_shared;
static unsigned char lock_a, lock_b;
static void Update(unsigned char *lock, uint32_t delta) {
 if (__atomic_test_and_set(lock, __ATOMIC_ACQUIRE)) return;
 uint32_t next = g_shared + delta; g_shared = next;
 __atomic_clear(lock, __ATOMIC_RELEASE);
}
void Lab_Init(void) { Lab_Configure(10, 2); }
void Lab_Low(void) { Update(&lock_a, 1); }
void Lab_High(void) { Update(&lock_b, 10); }
void Lab_Poll(void) {}

