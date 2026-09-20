# D01–D20 设计验收固件

每个目录是独立固件，各有自己的 `main` 和中断入口，不能把二十个文件一起编译。旧 Demo 的配置已排除 `cases/*`。

在工具根目录运行（使用已安装依赖的 Python）：

```powershell
python scripts/verify_design.py
python scripts/verify_design.py --all
```

第一条运行设计验收和控制流反例；第二条同时运行全部历史回归。无需 OpenCode、模型账户或目标板。真实 libclang 执行抽取，不使用手写 facts 替代 AST。

每项验证事实、分类、COMPLETE/PARTIAL、保护状态、归账、完整访问与调用链、SQLite、两个 HTML、默认复核队列和离线 Evidence Packet。输出在 `output/design-acceptance/Dxx/.ecra/`；同目录上一层保留真实源文件和编译数据库。总日志为 `verification.log`，机器可读结果为 `verification.json`。

| 场景 | 内容 | 期望分类 / 保护 |
|---|---|---|
| D01 | 无运行期访问 | SAFE |
| D02 | 真正只读 | SAFE |
| D03 | 单 MAIN 串行访问 | SAFE |
| D04 | MAIN 读、ISR 写 | SUSPECT |
| D05 | MAIN/ISR 多写者 | SUSPECT |
| D06 | 旧快照回写 | SUSPECT |
| D07 | MAIN/ISR 共用函数 static | SUSPECT |
| D08 | PRIMASK 完整 RMW | SAFE / EFFECTIVE |
| D09 | 仅保护 READ | SUSPECT / PARTIAL |
| D10 | BASEPRI + 常量宏优先级 | SAFE / EFFECTIVE；额外反例验证 INEFFECTIVE |
| D11 | BASEPRI 缺优先级 | UNKNOWN / UNRESOLVED |
| D12 | 影响变量的未知函数指针 | UNKNOWN |
| D13 | 无关函数中的未知外部调用 | SAFE，不无关污染 |
| D14 | 地址逃逸外部库 | UNKNOWN |
| D15 | CPU/DMA 生命周期未知 | UNKNOWN |
| D16 | 已配置临界区 | SAFE / EFFECTIVE |
| D17 | 未配置 Lock 名称 | SUSPECT / NOT_FOUND |
| D18 | DMB/DSB | SUSPECT / INEFFECTIVE |
| D19 | 单写者但跨 MAIN/ISR 读取 | SUSPECT |
| D20 | 32 个访问、两条 MAIN 调用路径 | SUSPECT，全部展示 |

未知项不是测试失败；恰当保留 UNKNOWN/UNRESOLVED 本身就是验收条件。真实模型结论、目标板交错和 DMA 生命周期证明不属于这些离线测试的验证范围。
