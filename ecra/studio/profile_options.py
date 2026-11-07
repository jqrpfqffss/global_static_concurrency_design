"""UI descriptions only. Engine defaults and validation remain authoritative."""
import copy
import math
import json
import yaml


def option(path, group, label, kind, hint, example='', minimum=None, maximum=None):
    return dict(path=path,group=group,label=label,kind=kind,hint=hint,example=example,minimum=minimum,maximum=maximum)


OPTIONS = [
    option('project.chip','工程','芯片型号','text','仅作工程说明；实际芯片宏来自编译命令。','STM32F103C8'),
    option('project.native_word_bits','工程','原生字长（位）','integer','通常填32；必须是8的正整数倍。','32',8),
    option('project.nvic_priority_bits','工程','NVIC优先级位数','integer','按芯片手册填写；不确定时留空，不猜测。','4',1,8),
    option('project.concurrency_model','工程','并发模型说明','text','保留原配置的模型说明，不代替真实入口与抢占证据。','single_core_preemptive'),
    option('analysis.cmake.generator','构建细节','CMake生成器','text','与工程真实构建方式一致；按目标选TU时需要Ninja。','Ninja'),
    option('analysis.cmake.build_dir','构建细节','构建目录标识','text','保留已有工程配置；正式构建仍由独立数据根隔离管理。','build/manual'),
    option('analysis.cmake.args','构建细节','CMake配置附加参数','lines','每行一个完整参数，空格保留；不要填-S、-B或-G。','-DAPP_RTOS=OFF\n-DBOARD=MY_BOARD'),
    option('analysis.cmake.build_args','构建细节','CMake构建附加参数','lines','每行一个参数；已填目标名称时不要再次指定--target。','--parallel\n4'),
    option('analysis.cmake.build','构建细节','配置后执行构建','boolean','通常开启；关闭时只配置并取得编译数据库。'),
    option('analysis.cmake.clean_before_configure','构建细节','构建前清理专用目录','boolean','只清理经归属校验的ECRA构建目录；开启可避免旧缓存。'),
    option('analysis.cmake.timeout_seconds','构建细节','构建超时（秒）','number','单次配置或构建的最长等待时间；默认600秒。','600',0.001),
    option('analysis.cmake.allow_external_toolchain','构建细节','允许外部工具链文件','boolean','工具链在固件目录外时按实际情况开启；仍会校验输入。'),
    option('analysis.exclude_files','纳入与排除','排除单个文件中的变量','lines','每行一个相对工程路径；只排除其变量，仍保留调用依赖。','Core/Src/syscalls.c'),
    option('analysis.exclude','排查选项','跳过解析的文件模式','lines','会减少解析覆盖；通常优先用“排除变量清单文件”。','Core/Src/legacy_unused.c'),
    option('analysis.expected_defines','排查选项','必须存在的编译宏','lines','每行一个宏；只核对真实命令，不会替你注入。','STM32F103xB\nUSE_HAL_DRIVER'),
    option('analysis.parse_timeout_seconds','排查选项','单文件解析超时（秒）','number','默认180秒；大文件频繁超时时再增加。','180',0.001),
    option('analysis.extraction_workers','排查选项','并行解析数','integer','1–8；内存紧张时减少。任务中心预算仍会约束实际并行。','1',1,8),
    option('analysis.auto_contexts','排查选项','自动识别执行入口','boolean','通常开启；识别常见中断、任务和回调，手工入口用于补充。'),
    option('analysis.build_closure_only','排查选项','仅分析当前构建闭包','boolean','通常开启；关闭可额外盘点未编译声明，不等于它们已完成并发分析。'),
    option('analysis.extra_args','排查选项','Clang附加参数','lines','每行一个真实需要的解析参数；错误参数会影响解析，请谨慎填写。','--target=arm-none-eabi'),
    option('analysis.remove_args','排查选项','移除的编译参数','lines','仅填写Clang不兼容的实际参数；不要移除芯片宏或ABI选项。'),
    option('analysis.allow_external_toolchain','排查选项','允许数据库引用外部工具链','boolean','编译器或工具链在工程外时使用；输入仍须完整校验。'),
    option('analysis.max_unknown_fanout_debug','排查选项','调试用未知分支显示数','integer','仅调试展示使用，不截断实际扫描关系；默认50。','50',1),
    option('analysis.git_diff.cache_enabled','排查选项','差异扫描缓存','boolean','通常保持默认开启；缓存仍须经过内容与环境校验。'),
    option('analysis.git_diff.verify_against_full','排查选项','差异结果对照全量','boolean','开启会增加一次完整分析作严格对照，耗时和磁盘占用会增加。'),
    option('review.enabled','OpenCode','扫描后自动OpenCode复核','boolean','首次接入建议关闭；开启后扫描会调用所配命令，可能使用联网模型。'),
    option('review.prepare_packets','OpenCode','关闭自动复核时仍准备输入','boolean','自动复核关闭时仍生成Packet和提示词，便于离线核对；自动复核开启时仍会调用模型。'),
    option('review.command','OpenCode','OpenCode命令与参数','lines','第一行是程序路径，其余每行一个参数；不要填整条shell命令。','opencode'),
    option('review.model','OpenCode','模型','text','填写已登录的provider/model；留空使用OpenCode自己的默认模型。','provider/model'),
    option('review.timeout_seconds','OpenCode','单次复核超时（秒）','number','每次调用的等待上限，不是变量之间的间隔。','600',0.001),
    option('review.retries','OpenCode','失败后额外重试数','integer','0表示不作技术重试；格式修复另行计算。','1',0),
    option('review.workers','OpenCode','同时复核数','integer','1–8个独立只读会话；按模型服务容量填写。','3',1,8),
    option('review.summary.enabled','OpenCode','生成一句话摘要','boolean','关闭后仍完整保留复核理由和证据。'),
    option('review.summary.max_chars','OpenCode','摘要最多字符数','integer','按字符计算，含标点；不是token，不会直接截断理由。','120',1,10000),
    option('review.summary.fix_retries','OpenCode','摘要格式修复次数','integer','摘要不合格时最多重新修复几次，范围0–10。','2',0,10),
]

# Complex declarations remain separate, explicit YAML segments with examples.
# Editing one segment never replaces the rest of the configuration.
for path,label,hint,example in [
    ('entry_registrations','自定义回调注册','只有工具无法识别注册API时填写。callback_arg从0计数；同一IRQ共用context_id。','- api: BSP_RegisterCallback\n  callback_arg: 1\n  kind: ISR\n  context_id: adc_irq'),
    ('call_edges','补充真实调用边','只填写确认存在但无法恢复的直接调用；不要把异步注册写成同步调用。','- caller: BoardDispatch\n  callee: UserCallback'),
    ('concurrency','已知并发关系','引用已配置入口ID；只记录may_interleave，不据此排除风险。','- contexts: [main, adc_irq]\n  relation: may_interleave'),
    ('preemption','已知抢占关系','higher和lower填已配置入口ID；声明仍须结合真实硬件证据。','- higher: adc_irq\n  lower: main'),
    ('resources','资源归属说明','按已有配置填写变量身份和归属；不会自动删除风险。',"- symbol_id: '报告中的完整变量身份'\n  owner_context: main"),
    ('protection','保护措施说明','保留原有保护声明；具体能否保护仍按静态证据判断。','[]'),
    ('known_safe','已知安全说明','只记录已核实的说明；不能代替扫描证明。','[]'),
    ('critical_sections','自定义临界区API','成对填写enter/exit或save/restore；函数名须与源码一致。','- enter: App_Lock\n  exit: App_Unlock'),
    ('async_enable','异步使能API','工具未识别的使能函数；irq_arg从0计数。','- api: Board_EnableIRQ\n  irq_arg: 0'),
    ('api_patterns','API识别模式','沿用工程原有模式，每个键对应函数名或模式的字符串列表。','{}'),
    ('analysis.build_closure','补充构建闭包','仅用于无法自动恢复的链接输入；可用linked_sources、linked_objects、missing_objects路径列表。','linked_sources: []\nlinked_objects: []\nmissing_objects: []'),
]:
    example=json.dumps(yaml.safe_load(example),ensure_ascii=False,indent=2)
    OPTIONS.append(option(path,'扩展语义',label,'mapping' if path in {'api_patterns','analysis.build_closure'} else 'records',hint,example))

BY_PATH={row['path']:row for row in OPTIONS}

MANAGED = {
    'version':'配置格式版本，当前使用1。',
    'analysis.output':'结果位置由“设置与验收状态”管理；正式扫描使用独立数据根。',
    'analysis.open_report':'旧CLI报告开关；Studio正式扫描不生成旧HTML，不用于启动上位机。',
    'analysis.output_dir':'旧输出路径；正式流程需迁移到独立数据根。',
    'analysis.auto_configure_cmake':'旧CMake兼容项，请使用当前构建方式；不能与analysis.cmake混用。',
}
BASE = {'project.name','project.root','project.core','analysis.include_dirs','analysis.exclude_dirs',
        'analysis.compile_database','analysis.auto_system_includes','analysis.cmake.target','analysis.cmake.toolchain_file',
        'analysis.cmake.build_type','analysis.git_diff.enabled','analysis.git_diff.base_ref','analysis.git_diff.current_ref',
        'analysis.git_diff.include_uncommitted','contexts'}


def inventory(document):
    rows=[]
    def walk(node,path=''):
        if isinstance(node,dict) and node:
            for key,value in node.items():walk(value,path+'.'+str(key) if path else str(key))
            return
        owner=next((key for key in BY_PATH if path==key or path.startswith(key+'.')),None)
        normal=next((key for key in BASE if path==key or path.startswith(key+'.')),None)
        managed=next((key for key in MANAGED if path==key or path.startswith(key+'.')),None)
        rows.append(dict(path=path,location=BY_PATH[owner]['group'] if owner else '普通表单' if normal else '兼容与位置设置' if managed else '高级原文',
                         hint=BY_PATH[owner]['hint'] if owner else MANAGED[managed] if managed else '在原文中完整保留；仅修改明确选择的配置项。'))
    walk(document);return rows


def validate(path,value):
    spec=BY_PATH.get(path)
    if not spec:raise ValueError('未知配置表单字段：'+str(path))
    if value is None:return
    kind=spec['kind'];valid=True
    if kind=='text':valid=isinstance(value,str) and not any(c in value for c in '\r\n\0')
    elif kind=='boolean':valid=type(value) is bool
    elif kind in {'integer','number'}:
        valid=type(value) in ((int,) if kind=='integer' else (int,float)) and math.isfinite(value)
        if valid:valid=(spec['minimum'] is None or value>=spec['minimum']) and (spec['maximum'] is None or value<=spec['maximum'])
    elif kind=='lines':valid=isinstance(value,list) and all(isinstance(x,str) and not any(c in x for c in '\r\n\0') for x in value)
    elif kind=='records':valid=isinstance(value,list) and all(isinstance(x,dict) for x in value)
    elif kind=='mapping':valid=isinstance(value,dict)
    if not valid:raise ValueError(spec['label']+' 的类型或取值不正确，请按提示填写')


def state(document):
    values={}
    for path in BY_PATH:
        node=document
        for key in path.split('.'):
            if not isinstance(node,dict) or key not in node:node=None;break
            node=node[key]
        values[path]=copy.deepcopy(node)
    return values
