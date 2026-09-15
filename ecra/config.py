import re
import hashlib
import os
import tempfile
import math
from pathlib import Path

import yaml


TOOL_ROOT = Path(__file__).resolve().parent.parent
PROJECT_INDEX = Path(os.environ.get('ECRA_CONFIG_HOME', str(TOOL_ROOT / 'config'))).resolve() / 'projects.yaml'


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


def index_path(value):
    return (PROJECT_INDEX.parent / value).resolve()


def project_profiles():
    return [dict(id=e['id'], root=str(index_path(e['root'])),
                 semantics=str(index_path(e['semantics']))) for e in _index_entries()]


def profile_target(profile):
    matches = [e for e in project_profiles() if e['id'] == profile]
    if len(matches) != 1:
        raise ValueError(f'未知项目配置 {profile}；运行 projects 查看可用项目')
    return Path(matches[0]['root']), Path(matches[0]['semantics'])


def discover_arm_toolchains(root):
    candidates = set(root.glob('*.cmake'))
    if (root/'cmake').is_dir():
        candidates.update((root/'cmake').rglob('*.cmake'))
    return sorted(p for p in candidates if 'arm-none-eabi' in p.read_text(encoding='utf-8-sig', errors='replace')
                  and 'CMAKE_C_COMPILER' in p.read_text(encoding='utf-8-sig', errors='replace'))


TEMPLATE = """# 全局/static 变量无需手工填写。相对路径均相对工程根目录。
version: 1
project:
  chip: STM32
  core: Cortex-M
  concurrency_model: single_core_preemptive
  native_word_bits: 32
analysis:
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
  chip: STM32
  core: Cortex-M
  native_word_bits: 32
analysis:
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


def _index_entries():
    """Return centrally managed projects. A damaged index must never select a config silently."""
    if not PROJECT_INDEX.is_file():
        return []
    data = read_yaml(PROJECT_INDEX)
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("projects", []), list):
        raise ValueError(f"工具项目配置索引格式无效: {PROJECT_INDEX}")
    entries = []
    ids, roots, paths = set(), set(), set()
    for item in data.get("projects", []):
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip()
                                              for k in ('id', 'root', 'semantics')):
            raise ValueError(f"工具项目配置索引存在无效项目: {PROJECT_INDEX}")
        root, path = index_path(item['root']), index_path(item['semantics'])
        if item['id'] in ids or root in roots or path in paths:
            raise ValueError(f'工具项目配置索引重复 id、工程目录或语义文件: {PROJECT_INDEX}')
        ids.add(item['id']); roots.add(root); paths.add(path)
        entries.append(item)
    return entries


def managed_config_path(root):
    """Find the central semantics file registered for *root*, if any."""
    root = Path(root).resolve()
    matches = []
    for item in _index_entries():
        project_root = Path(item["root"])
        if not project_root.is_absolute():
            project_root = (PROJECT_INDEX.parent / project_root).resolve()
        if project_root == root:
            semantics = Path(item["semantics"])
            if not semantics.is_absolute():
                semantics = (PROJECT_INDEX.parent / semantics).resolve()
            matches.append(semantics)
    if len(matches) > 1:
        raise ValueError(f"工程在工具配置索引中重复登记: {root}")
    return matches[0] if matches else None


def default_managed_config_path(root):
    """A deterministic, human-readable central location for a newly managed project."""
    root = Path(root).resolve()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", root.name).strip("-").lower() or "firmware"
    registered = managed_config_path(root)
    if registered:
        return registered
    candidate = PROJECT_INDEX.parent / "projects" / slug / "semantics.yaml"
    for item in _index_entries():
        semantics = Path(item['semantics'])
        if not semantics.is_absolute():
            semantics = (PROJECT_INDEX.parent / semantics).resolve()
        item_root = Path(item['root'])
        if not item_root.is_absolute():
            item_root = (PROJECT_INDEX.parent / item_root).resolve()
        if semantics == candidate and item_root != root:
            suffix = hashlib.sha256(str(root).encode('utf-8')).hexdigest()[:8]
            return PROJECT_INDEX.parent / "projects" / f"{slug}-{suffix}" / "semantics.yaml"
    return candidate


def register_managed_project(root, semantics):
    """Register a tool-side configuration without writing configuration into firmware sources."""
    root, semantics = Path(root).resolve(), Path(semantics).resolve()
    entries = _index_entries()
    retained = []
    for item in entries:
        item_root = Path(item["root"])
        if not item_root.is_absolute():
            item_root = (PROJECT_INDEX.parent / item_root).resolve()
        if item_root != root:
            retained.append(item)
    try:
        root_text = str(root.relative_to(PROJECT_INDEX.parent))
    except ValueError:
        root_text = str(root)
    try:
        semantics_text = str(semantics.relative_to(PROJECT_INDEX.parent))
    except ValueError:
        semantics_text = str(semantics)
    ident = semantics.parent.name
    if ident in {e['id'] for e in retained}:
        ident += '-' + hashlib.sha256(str(root).encode('utf-8')).hexdigest()[:8]
    retained.append(dict(id=ident,
                         root=root_text, semantics=semantics_text))
    PROJECT_INDEX.parent.mkdir(parents=True, exist_ok=True)
    # Serialize registration, and replace the index atomically. Preserve all
    # existing entries; concurrent init must fail instead of losing a project.
    lock = PROJECT_INDEX.with_suffix('.lock')
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError(f'配置索引正在写入: {lock}；稍后重试 init') from exc
    os.close(fd)
    temp = None
    try:
        if _index_entries() != entries:
            raise ValueError('配置索引已被另一进程更新，请重试 init')
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=PROJECT_INDEX.parent,
                                         suffix='.tmp', delete=False) as stream:
            temp = Path(stream.name)
            yaml.safe_dump(dict(version=1, projects=retained), stream, allow_unicode=True, sort_keys=False)
        temp.replace(PROJECT_INDEX)
    finally:
        if temp:
            temp.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def resolve_config_path(root, path=None):
    """Use central config by default; explicit relative paths keep legacy project-relative behavior."""
    root = Path(root).resolve()
    if path:
        requested = Path(path)
        return requested.resolve() if requested.is_absolute() else (root / requested).resolve()
    managed = managed_config_path(root)
    if managed:
        return managed
    # Existing projects remain runnable while they migrate; init never writes this location anymore.
    legacy = root / ".ecra" / "semantics.yaml"
    if legacy.is_file():
        return legacy
    # Only registered configurations are implicit. Never adopt an unrelated
    # same-named firmware's orphan config just because its filename matches.
    raise ValueError(f'工程尚未登记工具侧配置: {root}；先运行 run_ecra.py init --project "{root}"')


def load_config(root, path=None):
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
    for key in ("contexts", "concurrency", "preemption", "call_edges", "entry_registrations", "resources", "protection", "known_safe"):
        cfg.setdefault(key, [])
        if not isinstance(cfg[key], list) or any(not isinstance(x, dict) for x in cfg[key]):
            raise ValueError(f"{key} 必须是映射列表")
    ids = set()
    for c in cfg["contexts"]:
        if not isinstance(c.get('id'), str) or not c['id'].strip() or c["id"] in ids:
            raise ValueError("context id 缺失或重复")
        ids.add(c["id"])
        if c.get("kind") not in {"ISR", "TASK", "MAIN", "CALLBACK", "DMA", "CORE"}:
            raise ValueError(f"未知上下文类型 {c.get('kind')}")
        for field in ("functions", "patterns", "regex"):
            if field in c and (not isinstance(c[field], list) or any(not isinstance(x, str) for x in c[field])):
                raise ValueError(f"contexts.{field} 必须是字符串列表")
        for pattern in c.get("regex", []):
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f'contexts.regex 无效: {pattern}: {exc}') from exc
        for flag in ('enabled', 'reentrant'):
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
    if 'cmake' in a:
        c = a['cmake']
        if not isinstance(c, dict):
            raise ValueError('analysis.cmake 必须是映射')
        allowed = {'build_dir', 'generator', 'build_type', 'toolchain_file', 'args', 'build', 'build_args', 'timeout_seconds'}
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
                         ('analysis', 'auto_system_includes'), ('analysis', 'open_report'), ("review", "enabled")):
        if key in cfg[section] and type(cfg[section][key]) is not bool:
            raise ValueError(f"{section}.{key} 必须是 true/false")
    for key, value in cfg["api_patterns"].items():
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise ValueError(f"api_patterns.{key} 必须是字符串列表")
    word = cfg["project"].get("native_word_bits", 32)
    if type(word) is not int or word <= 0 or word % 8:
        raise ValueError("project.native_word_bits 必须是正的 8 倍数")
    workers = cfg['review'].get('workers', 1)
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError('review.workers 必须是 1 到 8 的整数')
    command = cfg["review"].get("command", ["opencode"])
    if not isinstance(command, list) or not command or any(not isinstance(x, str) for x in command):
        raise ValueError("review.command 必须是非空参数数组，不能是 shell 命令字符串")
    return cfg, path
