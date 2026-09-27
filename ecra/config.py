import re
import os
import math
from pathlib import Path

import yaml


TOOL_ROOT = Path(__file__).resolve().parent.parent
CONFIG_HOME = Path(os.environ.get('ECRA_CONFIG_HOME', str(TOOL_ROOT / 'config'))).resolve()
SEMANTICS_FILE = CONFIG_HOME / 'semantics.yaml'


class UniqueKeyLoader(yaml.SafeLoader):
    """A duplicated analysis/context section must not silently erase configuration."""
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, (str, int, float, bool)):
                raise ValueError('YAML 配置键必须是标量')
            if key in result:
                raise ValueError(f'YAML 配置键重复: {key}（第 {key_node.start_mark.line + 1} 行）')
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def read_yaml(path):
    try:
        return yaml.load(Path(path).read_text(encoding='utf-8-sig'), Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f'YAML 格式错误 {path}: {exc}') from exc


def discover_arm_toolchains(root):
    candidates = set(root.glob('*.cmake'))
    if (root/'cmake').is_dir():
        candidates.update((root/'cmake').rglob('*.cmake'))
    return sorted(p for p in candidates if 'arm-none-eabi' in p.read_text(encoding='utf-8-sig', errors='replace')
                  and 'CMAKE_C_COMPILER' in p.read_text(encoding='utf-8-sig', errors='replace'))


TEMPLATE = """# 全局/static 变量无需手工填写。相对路径均相对工程根目录。
version: 1
project:
  # 被排查固件工程的根目录；相对路径以本 semantics.yaml 所在目录为基准。
  root: ../firmware/MyBoard
  chip: STM32
  core: Cortex-M
  concurrency_model: single_core_preemptive
  native_word_bits: 32
analysis:
  build_closure_only: true  # 只分析当前固件；false 额外盘点未编译声明，但不将它们送入并发复核
  max_unknown_fanout_debug: 50
  compile_database: auto  # 或 build/compile_commands.json
  auto_configure_cmake: false
  cmake_build_dir: build
  # cmake_toolchain_file: cmake/arm-none-eabi.cmake
  # extra_args: [--target=arm-none-eabi]
  # expected_defines: [USE_HAL_DRIVER, STM32H747xx]
  # 只排除明确不属于当前固件的源文件，排除列表会显示在报告中。
  exclude: []
  # 多个目录取并集，exclude_dirs 优先；目录递归匹配，不需要写 /*。
  # 目录之外的代码可作为调用链依赖解析，但其变量不进入排查结果。
  include_dirs: []  # 空列表表示不限制包含范围
  exclude_dirs: []
  exclude_files: []  # 混放在业务目录中的第三方 .c/.h 文件；保留调用链依赖
  parse_timeout_seconds: 180
  output_dir: .ecra
  auto_contexts: true
contexts:
  - id: main
    kind: MAIN
    functions: [main]
  # 静态任务、回调、定时器、自定义调度器等无法自动识别时补充入口。
  # - id: control_task
  #   kind: TASK
  #   functions: [ControlTask]
  # 同一个函数被创建为多个任务时，填写多个不同 id。
concurrency: []
preemption: []
# 只补充 Clang 无法解析的真实调用边，不把异步注册误当直接调用。
call_edges: []  # [{caller: IRQHandler, callee: Callback}]
# 复杂 BSP/驱动将真正入口经多层回调或动态向量注册时，在这里声明
# 注册 API 的回调参数。调用链仍需有可恢复的间接调用边；本配置不会
# 凭空伪造同步调用。
# entry_registrations:
#   - api: BSP_RegisterIrqCallback
#     callback_arg: 1
#     kind: ISR
#     context_id: bsp_irq  # 同一物理 IRQ 的多个回调使用同一 id
#     may_repeat: false
resources: []   # [{symbol_id: '...', owner_context: control_task}]
protection: []  # 声明不会消除风险，仍需核对真实路径。
# 项目私有临界区语义。只有在此处明确声明的封装才会被当作 IRQ 屏蔽证据。
# critical_sections:
#   - enter: APP_EnterCritical
#     exit: APP_ExitCritical
#     type: irq_mask       # 或 primask；仅能证明屏蔽普通可配置中断
#   - save: IntLock
#     restore: IntUnlock
#     type: irq_mask
critical_sections: []
known_safe: []  # 保留记录，永不自动隐藏候选。
api_patterns:
  lock_enter: [taskENTER_CRITICAL, taskENTER_CRITICAL_FROM_ISR, __disable_irq, 'xSemaphoreTake*', 'osMutexAcquire*']
  lock_exit: [taskEXIT_CRITICAL, taskEXIT_CRITICAL_FROM_ISR, __enable_irq, 'xSemaphoreGive*', 'osMutexRelease*']
  dma_start: ['HAL_*_DMA']
review:
  enabled: false  # 默认本地排查；明确配置 --model 后启用复核
  command: [opencode]
  # model: provider/model  # 使用你已配置并登录的 OpenCode 模型
  timeout_seconds: 300
  retries: 1
  # 0 表示不限制。设置上限后剩余项始终标为 PENDING。
  max_items: 0
"""


CMAKE_TEMPLATE = """# 裸机 CMake 工程：编辑一次配置，之后只运行 ecra。
# 相对路径以固件根目录为基准。变量无需逐个填写。
version: 1
project:
  # 被排查固件工程的根目录；相对路径以本 semantics.yaml 所在目录为基准。
  root: ../firmware/MyBoard
  chip: STM32
  core: Cortex-M
  native_word_bits: 32
analysis:
  build_closure_only: true
  max_unknown_fanout_debug: 50
  # 只排查这些目录中定义的变量；多个目录取并集，递归包含子目录。
  include_dirs: [.]  # 例如 [Core/Src, Core/Inc, App]
  exclude_dirs: [Drivers, Middlewares, ThirdParty, build, .ecra]
  exclude_files: []  # 例如 [Core/Src/system_stm32f1xx.c, Core/Src/sysmem.c]
  cmake:
    build_dir: build/ecra
    generator: Ninja
    build_type: Debug
    # toolchain_file: cmake/arm-none-eabi.cmake
    args: []  # 原工程需要的 -D 选项；每项是一个参数
    # true 时每次扫描先删除 build_dir，再重新配置和构建。
    clean_before_configure: false
    build: true  # 每次先配置并增量构建，再扫描；不会烧录
  auto_system_includes: true  # 自动探测 Arm GCC 标准头文件目录
  output_dir: .ecra
  # open_report: true  # 完成后用默认浏览器打开变量报告
contexts:
  - id: main
    kind: MAIN
    functions: [main]
# 无参数 IRQHandler 自动识别，HAL 回调沿实际调用链继承上下文。
# 不能由源码恢复的动态 ISR/回调注册可使用 entry_registrations 声明。
review:
  enabled: false  # 默认本地静态排查；需要 OpenCode 复核时改为 true
  command: [opencode]
  # model: provider/model
  timeout_seconds: 300
  retries: 1
  max_items: 0
"""


def resolve_config_path(root=None, path=None):
    """Return the one central config, with explicit and legacy paths supported.

    The normal path is always ``config/semantics.yaml``.  A legacy project-local
    file is only used when a caller explicitly supplies that project root; this
    keeps historical automation readable without creating new per-project files.
    """
    if path:
        requested = Path(path)
        if requested.is_absolute():
            return requested.resolve()
        return ((Path(root).resolve() if root else CONFIG_HOME) / requested).resolve()
    if root:
        legacy = Path(root).resolve() / '.ecra' / 'semantics.yaml'
        if legacy.is_file():
            return legacy
    return SEMANTICS_FILE


def configured_project_root(path=None):
    """Read the target firmware directory selected by the central semantics file."""
    config_path = resolve_config_path(path=path)
    if not config_path.is_file():
        raise ValueError(f'缺少唯一项目配置 {config_path}；请先复制模板并填写 project.root')
    cfg = read_yaml(config_path)
    project = cfg.get('project', {}) if isinstance(cfg, dict) else {}
    value = project.get('root') if isinstance(project, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'缺少 project.root: {config_path}；请填写待排查固件工程目录')
    root = Path(value)
    return (root if root.is_absolute() else config_path.parent / root).resolve()


def load_config(root=None, path=None):
    path = resolve_config_path(root, path)
    if not path.is_file():
        raise ValueError(f"缺少工具侧项目配置 {path}；先运行 run_ecra.py init --project \"{root}\"")
    cfg = read_yaml(path)
    if not isinstance(cfg, dict) or cfg.get("version") != 1:
        raise ValueError("配置必须是 YAML 映射，且 version: 1")
    for key in ("project", "analysis", "review", "api_patterns"):
        cfg.setdefault(key, {})
        if not isinstance(cfg[key], dict):
            raise ValueError(f"{key} 必须是映射")
    if 'root' in cfg['project'] and (not isinstance(cfg['project']['root'], str) or not cfg['project']['root'].strip()):
        raise ValueError('project.root 必须是非空路径字符串')
    for key in ("contexts", "concurrency", "preemption", "call_edges", "entry_registrations", "resources", "protection", "critical_sections", "known_safe"):
        cfg.setdefault(key, [])
        if not isinstance(cfg[key], list) or any(not isinstance(x, dict) for x in cfg[key]):
            raise ValueError(f"{key} 必须是映射列表")
    ids = set()
    for c in cfg["contexts"]:
        if not isinstance(c.get('id'), str) or not c['id'].strip() or c["id"] in ids:
            raise ValueError("context id 缺失或重复")
        ids.add(c["id"])
        if c.get("kind") not in {"ISR", "TASK", "MAIN", "CALLBACK", "DMA", "CORE", "FOREGROUND", "IRQ", "EXTERNAL_ASYNC", "UNKNOWN_CONTEXT"}:
            raise ValueError(f"未知上下文类型 {c.get('kind')}")
        for field in ("functions", "patterns", "regex"):
            if field in c and (not isinstance(c[field], list) or any(not isinstance(x, str) for x in c[field])):
                raise ValueError(f"contexts.{field} 必须是字符串列表")
        for pattern in c.get("regex", []):
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f'contexts.regex 无效: {pattern}: {exc}') from exc
        for flag in ('enabled', 'reentrant', 'asynchronous'):
            if flag in c and type(c[flag]) is not bool:
                raise ValueError(f'contexts.{flag} 必须是 true/false')
    for rel in cfg["concurrency"]:
        if len(rel.get("contexts", [])) != 2 or any(x not in ids for x in rel["contexts"]):
            raise ValueError("concurrency 必须引用两个已配置的 context id")
        if rel.get("relation", "may_interleave") != "may_interleave":
            raise ValueError("当前只支持 may_interleave；不依据配置直接排除并发")
    for rel in cfg["preemption"]:
        if rel.get("higher") not in ids or rel.get("lower") not in ids:
            raise ValueError("preemption 引用了不存在的 context id")
    for entry in cfg["entry_registrations"]:
        if set(entry) - {'api', 'callback_arg', 'kind', 'context_id', 'may_repeat'}:
            raise ValueError('entry_registrations 存在未知字段')
        if not isinstance(entry.get("api"), str) or not entry["api"].strip():
            raise ValueError("entry_registrations.api 必须是非空 API 名称或通配模式")
        if type(entry.get("callback_arg")) is not int or entry["callback_arg"] < 0:
            raise ValueError("entry_registrations.callback_arg 必须是非负整数")
        if entry.get("kind") not in {"ISR", "TASK", "CALLBACK"}:
            raise ValueError("entry_registrations.kind 必须是 ISR、TASK 或 CALLBACK")
        if "context_id" in entry and (not isinstance(entry["context_id"], str) or not entry["context_id"].strip()):
            raise ValueError("entry_registrations.context_id 必须是非空字符串")
        if "may_repeat" in entry and type(entry["may_repeat"]) is not bool:
            raise ValueError("entry_registrations.may_repeat 必须是 true/false")
    for section in cfg['critical_sections']:
        allowed = {'enter', 'exit', 'save', 'restore', 'type'}
        if set(section) - allowed:
            raise ValueError('critical_sections 存在未知字段')
        paired = ((isinstance(section.get('enter'), str) and section['enter'].strip()
                   and isinstance(section.get('exit'), str) and section['exit'].strip())
                  or (isinstance(section.get('save'), str) and section['save'].strip()
                      and isinstance(section.get('restore'), str) and section['restore'].strip()))
        if not paired:
            raise ValueError('critical_sections 每项必须提供 enter/exit 或 save/restore')
        if section.get('type') not in {'primask', 'irq_mask', 'basepri'}:
            raise ValueError('critical_sections.type 必须是 primask、irq_mask 或 basepri')
    kinds = {c['id']: c['kind'] for c in cfg['contexts']}
    for e in cfg['entry_registrations']:
        cid = e.get('context_id')
        if cid and cid in kinds and kinds[cid] != e['kind']:
            raise ValueError(f'注册入口 context_id 类型冲突: {cid}')
        if cid:
            kinds[cid] = e['kind']
    for key in ("extra_args", "remove_args", "exclude", "include_dirs", "exclude_dirs", "exclude_files", "expected_defines", "cmake_args"):
        value = cfg["analysis"].get(key, [])
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise ValueError(f"analysis.{key} 必须是字符串列表")
        if key in {'include_dirs', 'exclude_dirs', 'exclude_files'} and any(not x.strip() or any(c in x for c in '*?[]') for x in value):
            raise ValueError(f'analysis.{key} 请填写非空目录路径，不使用通配符；目录自动递归匹配')
    a = cfg['analysis']
    a.setdefault('build_closure_only', True)
    closure = a.get('build_closure', {})
    if not isinstance(closure, dict):
        raise ValueError('analysis.build_closure 必须是映射')
    for key in ('linked_sources', 'linked_objects', 'missing_objects'):
        if key in closure and (not isinstance(closure[key], list) or any(not isinstance(p, str) or not p.strip() for p in closure[key])):
            raise ValueError(f'analysis.build_closure.{key} 必须是非空路径字符串列表')
    fanout = a.get('max_unknown_fanout_debug', 50)
    if type(fanout) is not int or fanout < 1:
        raise ValueError('analysis.max_unknown_fanout_debug 必须是正整数')
    if 'cmake' in a:
        c = a['cmake']
        if not isinstance(c, dict):
            raise ValueError('analysis.cmake 必须是映射')
        allowed = {'build_dir', 'generator', 'build_type', 'toolchain_file', 'args', 'build', 'build_args',
                   'clean_before_configure', 'timeout_seconds'}
        if set(c) - allowed:
            raise ValueError('analysis.cmake 未知配置项: ' + ', '.join(sorted(set(c)-allowed)))
        for key in ('args', 'build_args'):
            if not isinstance(c.get(key, []), list) or any(not isinstance(x, str) for x in c.get(key, [])):
                raise ValueError(f'analysis.cmake.{key} 必须是字符串列表')
        for key in ('build_dir', 'generator', 'build_type', 'toolchain_file'):
            if key in c and (not isinstance(c[key], str) or not c[key].strip()):
                raise ValueError(f'analysis.cmake.{key} 必须是非空字符串')
        if 'build' in c and type(c['build']) is not bool:
            raise ValueError('analysis.cmake.build 必须是 true/false')
        if 'clean_before_configure' in c and type(c['clean_before_configure']) is not bool:
            raise ValueError('analysis.cmake.clean_before_configure 必须是 true/false')
        if type(c.get('timeout_seconds', 600)) not in (int, float) or not math.isfinite(c.get('timeout_seconds', 600)) or c.get('timeout_seconds', 600) <= 0:
            raise ValueError('analysis.cmake.timeout_seconds 必须大于 0')
        if a.get('auto_configure_cmake') or any(k.startswith('cmake_') for k in a):
            raise ValueError('analysis.cmake 不可与旧的 auto_configure_cmake/cmake_* 配置混用')
    for section, name in (("analysis", "parse_timeout_seconds"), ("review", "timeout_seconds")):
        value = cfg[section].get(name, 180)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{section}.{name} 必须大于 0")
    for name in ("retries", "max_items"):
        value = cfg["review"].get(name, 0)
        if type(value) is not int or value < 0:
            raise ValueError(f"review.{name} 必须是非负整数")
    for section, key in (("analysis", "auto_contexts"), ("analysis", "auto_configure_cmake"),
                         ('analysis', 'auto_system_includes'), ('analysis', 'open_report'),
                         ('analysis', 'build_closure_only'), ("review", "enabled")):
        if key in cfg[section] and type(cfg[section][key]) is not bool:
            raise ValueError(f"{section}.{key} 必须是 true/false")
    for key, value in cfg["api_patterns"].items():
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise ValueError(f"api_patterns.{key} 必须是字符串列表")
    word = cfg["project"].get("native_word_bits", 32)
    if type(word) is not int or word <= 0 or word % 8:
        raise ValueError("project.native_word_bits 必须是正的 8 倍数")
    priority_bits = cfg['project'].get('nvic_priority_bits')
    if priority_bits is not None and (type(priority_bits) is not int or not 1 <= priority_bits <= 8):
        raise ValueError('project.nvic_priority_bits 必须是 1 到 8 的整数')
    workers = cfg['review'].get('workers', 1)
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError('review.workers 必须是 1 到 8 的整数')
    command = cfg["review"].get("command", ["opencode"])
    if not isinstance(command, list) or not command or any(not isinstance(x, str) for x in command):
        raise ValueError("review.command 必须是非空参数数组，不能是 shell 命令字符串")
    return cfg, path
