/* Synthetic STM32-style IRQ layout for analyzer boundary tests, not a device header. */
#ifndef NVIC_RECOVERY_FIXTURE_H
#define NVIC_RECOVERY_FIXTURE_H
#define __NVIC_PRIO_BITS (1U << 2)
#define NVIC_PRIORITYGROUP_2 5U
enum {TIM3_IRQn=29, TIM4_IRQn=30, TIM8_UP_TIM13_IRQn=44, TIM1_UP_TIM16_IRQn=25};
typedef struct {void *Instance; unsigned State;} TIM_HandleTypeDef;
#define TIM3 ((void *)0x40000400U)
#define TIM4 ((void *)0x40000800U)
#define TIM8 ((void *)0x40010400U)
#define TIM13 ((void *)0x40001C00U)
#define TIM16 ((void *)0x40014400U)
extern TIM_HandleTypeDef htim3,htim4,htim8,htim13,htim16;
extern volatile unsigned shared;
void HAL_NVIC_SetPriorityGrouping(unsigned);
void HAL_NVIC_SetPriority(int,unsigned,unsigned);
void HAL_NVIC_EnableIRQ(int);
void HAL_TIM_Base_Init(TIM_HandleTypeDef *);
void HAL_TIM_Base_MspInit(TIM_HandleTypeDef *);
void HAL_TIM_IRQHandler(TIM_HandleTypeDef *);
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *);
void Board_Init(void);
#endif
