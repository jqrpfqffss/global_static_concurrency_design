# 固定环境的原版/新版与完整验证队列

2026-11-03（北京时间）。保留旧G1非零差异与G4不足，不改变规范化、数组顺序、类型、重复次数或求解统计。新协议是[40号记录](40-fixed-execution-environment-baseline.md)的实际执行。

| 项目 | 完成状态/实际证据 |
|---|---|
| v26完整回归 | 1355项，1353PASS/2联网SKIP，2397.319s；2007个冻结文件与独立测试副本后验无差异。[收据](evidence/full-regression-studio-v26.json)。原生v11在启动前撤销，原队列收据保留，没有借其生成新测量。 |
| v27完整回归 | 1369项，1367PASS/2联网SKIP，2016.572s；冻结1493c051165973838b35653e26ce1a0943e419d3、2043文件，源与独立测试副本无差异。[收据](evidence/full-regression-studio-v27.json)。 |
| v27真实构建 | 498.438s，目录与中文ZIP解包两份各27CLI验收通过；ZIP SHA256 0edc217422f44c06917c19c14256fba7b4ab88902aae8b400c7e3fc8348b282f。[实际构建](evidence/portable-studio-v27-build-v1.json)。17组浏览器与全分发SHA尚需封存，不将构建成功称完整发布。 |
| 新原版原生 | 未修改e69原引擎，真实388TU，seed0/日期epoch1793577600，同d1bc配置；15454.922s，exit2、analysis_valid=true、STATIC_SCAN_SAVED、VERIFIED，保留真实INCOMPLETE覆盖。[完整原生](evidence/inav-original-seed0-native-v3-final.json)。 |
| 新原版后验 | 全4123源/Git/构建输入与699个原引擎文件前后SHA不变；原配置6b27不变，共享新配置d1bc固定。[控制器](evidence/inav-original-seed0-native-v3-driver-result.json)、[前验](evidence/inav-original-seed0-native-v3-preflight.json)、[后验](evidence/inav-original-seed0-native-v3-postflight.json)。 |
| 新版原生 | 冻结v27通过1369项后，在全新H:/ECRA-NATIVE-A12-SEED0进行真实冷388TU，16GiB Job；截至本记录正在单次权威库发布，未完成即不报通过。 |
| 原始备份/比较图 | 新原版全部57773文件独立复制到I:/ECRA-GOLDEN-O3-SEED0，完整SHA和只读属性完成后才开始无损流式建立新比较图；当前排队/执行中，未称完成。源/备份只读属性不等于ACL只读挂载。 |
| 严格对照与包 | 等两方有效完成及输入后验/原版备份/完整比较图全部通过后，在独立2GiB Job执行完整图/引用/投影检查与全字段比较；非零立即FAIL，不导出。差异0后才归档必要审计、绑定manifest、标准包导出和独立数据根严格导入；不是第二物理电脑。 |

| 新原版实际指标 | 字节/耗时 | 范围 |
|---|---:|---|
| Job Commit峰值 | 29811765248 | 显式32GiB受控原版，不是物理32GB测试 |
| 进程树RSS峰值 | 29559390208 | 与Job分开记录 |
| Private峰值 | 29741166592 | 原版同环境新测量 |
| 采样输出逻辑峰值 | 46427693457 | 原版独立数据根 |
| 采样文件分配峰值 | 46538663768 | 排除目录/MFT/ADS，不当作全策略峰值 |
| 耗时 | 15454.922s | 同宿主/HDD存在并行任务，不作独占加速归因 |

## 验证连接的64MiB页缓存

比较器文件SHA256仍为427998f4705cdb753464e490ec2c11f243772ab88db2c92fd27d381d4fd9ba98，与已冻结旧版一致。生产分页/元数据连接保持原默认；只在这个独立完整比较进程为两条只读连接设置`PRAGMA cache_size=-65536`，每连接按需页缓存建议值，不是进程内存硬限。比较Job仍2GiB；完整`EvidenceProvider.validate(deep=True)`、同一BEGIN读视图、全部typed节点/边/投影、完整facts和原report归一化/删减清单保持。

[实际F030控制](evidence/comparator-read-cache-f030-v1.json)对同一完整原/新图分别用显式2MiB和64MiB比较，双方全部检查通过、facts/report摘要完全相同，原始两库完整SHA前后不变，比较器文件字节不变。原先/后测和共享磁盘下的时间不作为加速结论；不是大型G1。

大型观察器只替换创建连接这一处：

```python
original_connect = comparator.connect_readonly
def comparison_connection(path):
    connection = original_connect(path)
    connection.execute('PRAGMA cache_size=-65536')
    return connection
comparator.connect_readonly = comparison_connection
comparison = comparator.compare(old, new, envelope=envelope)
```

完整标准包与新70%物理口径仍待实际结果；旧40.2058%失败、原失控seed差异和所有失败运行保持。G2其余工程按用户决定NOT_VERIFIED_USER_DEFERRED；物理32GB、干净离线PC、第二物理电脑、DPI、真实OpenCode和工程师UAT未验证。
