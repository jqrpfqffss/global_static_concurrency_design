# STM32 裸机工程：初始化与接收中断的直接复核

本记录由 Codex 直接核对当前固定固件变体的源码与扫描事实。它不是 OpenCode 收据，也不把当前 38 项待复核队列标记为完成。

## 可成立的初始化窗口

1. `main` 在 `apps/cli/cli_simple.c:74` 调用 `uart_init()`；它在 `drivers/src/uart.c:234` 设置 `RXNEIE`，并在第 240 行使能 UART IRQ。
2. `main` 在 `apps/cli/cli_simple.c:103` 调用 `cli_app_attach_uart_callbacks()`，其第 67 行注册 `on_char_received`；`drivers/src/uart.c:317-318` 将回调保存到 `rx_callback`。
3. `main` 直到 `apps/cli/cli_simple.c:108` 才调用 `cli_init(&g_cli, ..., g_cmd_buffer, MAX_CMD_SIZE)`。此调用在 `utils/src/cli.c:172-173` 才写入 `g_cli.buffer` 和 `g_cli.buffer_size`。调用前，这两个静态成员仍是零初始化值。
4. 在步骤 2 与 3 之间，USART2 收到可打印字符时，`drivers/src/uart.c:440-443` 会调用已注册的回调；`apps/cli/cli_simple.c:33` 随即进入 `cli_process_char(&g_cli, ...)`。
5. `utils/src/cli.c:433-434` 的条件为 `buffer_pos < buffer_size - 1`。`buffer_size` 是 `size_t`（`utils/inc/cli.h:43`），尚为零时减一发生无符号回绕；`buffer_pos` 也为零，条件成立，随后经仍为空的 `buffer` 指针写字符。

这个交错不依赖 main 抢占 ISR；ISR 抢占正在初始化的 main 即可。它说明旧版模型对 `g_cli.buffer` 和 `g_cli.buffer_size` 的 `REVIEWED_SAFE` 结论遗漏了注册与初始化之间的窗口。两项在当前静态扫描中仍为 `SUSPECT`，未被自动筛除。固件尚未上板复现，因此此处记录的是源码与 Cortex-M 中断模型支持的可成立执行路径。

最直接的固件修复顺序是先完成 `cli_init`，再注册 RX 回调；如硬件可能在注册瞬间已有待处理 RX 字节，注册前应明确清除或屏蔽接收事件，并在初始化完成后恢复。上游示例源码在本验证目录中保持原样，便于继续复现。

## 工具改动的对应验证

- 复核包对主循环写入且 IRQ 访问、又缺少初始化先行证明的变量增加 `lifecycle:async_before_init` 必查项；真实工程的 `g_cli.buffer` 与 `g_cli.buffer_size` 均生成了此项。最终安全或确认结论须至少引用两个不同源码位置。
- OpenCode 主提示词和反证提示词现在明确要求核对 IRQ 使能、回调注册、对象初始化三者的先后。
- `status` 会验证收据的提示词、输入包、原始日志、答案与源码引用，不能仅凭队列中的 `DONE` 标签宣称复核完成。

当前扫描的 OpenCode 队列为 38 项 `PENDING`。自动审批拒绝向外部 OpenCode 服务发送源码及候选项，因为当前 `AGENTS.md` 禁用外部代理委派；没有绕过该限制，也没有生成新的 OpenCode 结论。
