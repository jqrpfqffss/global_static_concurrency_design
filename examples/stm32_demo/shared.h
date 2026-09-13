#ifndef DEMO_SHARED_H
#define DEMO_SHARED_H
typedef unsigned int uint32_t;
typedef unsigned short uint16_t;
extern volatile uint32_t g_counter;
extern uint16_t g_msgSP;
static int header_state;
static inline void HeaderUpdate(void) { header_state++; }
void ECAT_Task(void);
void ControlTask(void *argument);
void Work(void);
#endif
