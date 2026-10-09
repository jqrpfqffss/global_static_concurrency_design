"""Source-level semantics for APIs that can start an asynchronous executor."""
import fnmatch


ASYNC_ENABLE_APIS = {
    'HAL_NVIC_EnableIRQ', 'NVIC_EnableIRQ',
    'HAL_TIM_Base_Start_IT', 'HAL_TIM_OC_Start_IT', 'HAL_TIM_PWM_Start_IT',
    'HAL_UART_Receive_IT', 'HAL_UART_Transmit_IT', 'HAL_UART_Receive_DMA',
    'HAL_SPI_Receive_IT', 'HAL_SPI_TransmitReceive_IT', 'HAL_SPI_Receive_DMA',
    'HAL_ADC_Start_IT', 'HAL_ADC_Start_DMA',
    'HAL_DMA_Start', 'HAL_DMA_Start_IT',
}


def is_async_enable(api, cfg):
    return api in ASYNC_ENABLE_APIS or any(
        fnmatch.fnmatchcase(api, item['api']) for item in cfg.get('async_enable', ()))


def async_irq_arg(api, cfg):
    if api in {'NVIC_EnableIRQ', 'HAL_NVIC_EnableIRQ'}:
        return 0
    for item in cfg.get('async_enable', ()):
        if fnmatch.fnmatchcase(api, item['api']):
            return item.get('irq_arg')
    return None
