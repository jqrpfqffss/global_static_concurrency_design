"""Conflict-based pre-OpenCode classification with variable-local evidence slices.

四类分类最高层公式（本模块唯一裁决逻辑）::

    破坏性冲突（双写 / RMW 交叉 / DMA 与 CPU 至少一方写 / 位域并发写 /
                   多字段一致性 / 可重入写者，且 MHP != NO）+ 未证明有效保护
        => SUSPECT（即使抢占优先级或保护细节尚未恢复）

    单一写者域 + 其余域只读 + 写者无独立读站点 + 可证明单指令原子宽度
    + 无 DMA / 地址逃逸 / 未知写者 / 多字段一致性关联
        => SHARED_NO_REVIEW（共享访问，无需复核；不进入 OpenCode，也不是安全证明）

    无冲突 + 该变量证据切片内存在可能隐藏冲突的关键缺口
        => UNKNOWN（精准 reason code，禁止宽泛兜底）

    无冲突 + 变量相关证据足够证明不存在其它冲突
        => SAFE_PROVEN（必须携带 safe_reason_code + safe_evidence）

工程中其它位置的函数指针、未知 alias、缺失 caller、解析失败，
只要不进入该变量的 Evidence Slice，一律不影响该变量分类。
"""
from collections import Counter, defaultdict, deque
import re


# ---------------------------------------------------------------------------
# 物理执行上下文（裸机模型）
# ---------------------------------------------------------------------------

def context_domains(contexts):
    """Map context id -> physical execution domain.

    STM32 裸机的物理执行者是 foreground(main)、每个 IRQ vector、每个 DMA
    通道和真正的异步线程。多个 MAIN 上下文（以及显式声明同一
    ``execution_domain`` 的上下文）合并为一个 FOREGROUND 串行域；
    由同一 foreground dispatcher 串行调度的协作任务天然继承该域。
    """
    domain = {}
    for cid, c in contexts.items():
        explicit = c.get('execution_domain')
        if isinstance(explicit, str) and explicit.strip():
            domain[cid] = explicit.strip()
        elif c.get('kind') == 'MAIN':
            domain[cid] = 'FOREGROUND'
        else:
            domain[cid] = cid
    return domain


SAFE_LABELS = {
    'SAFE_NO_RUNTIME_ACCESS': '静态已判安全：无运行期访问',
    'SAFE_READ_ONLY': '静态已判安全：所有访问均为只读',
    'SAFE_MULTI_CONTEXT_READ_ONLY': '静态已判安全：所有上下文均只读取',
    'SAFE_SINGLE_FOREGROUND': '静态已判安全：仅主循环串行访问',
    'SAFE_SINGLE_IRQ': '静态已判安全：仅同一中断上下文串行访问',
    'SAFE_SINGLE_CONTEXT': '静态已判安全：仅单一执行域串行访问',
    'SAFE_NON_INTERLEAVING': '静态已判安全：多上下文已证明无法交错',
    'SAFE_EFFECTIVE_PROTECTION': '静态已判安全：完整临界区保护',
    'SAFE_INIT_ONLY_WRITE': '静态已判安全：初始化阶段写入，运行期只读',
    'SHARED_NO_REVIEW': '共享访问，无需复核：唯一写者 + 其余只读 + 原子宽度',
}

UNKNOWN_LABELS = {
    'UNKNOWN_ADDRESS_ESCAPE': '变量地址逃逸到无法分析的代码',
    'UNKNOWN_RELEVANT_ALIAS': '指针别名指向无法收敛到该变量',
    'UNKNOWN_RELEVANT_INDIRECT_CALL': '无法确认某间接访问是否指向该变量',
    'UNKNOWN_RELEVANT_MISSING_TU': '缺失编译单元可能访问该变量',
    'UNKNOWN_EXECUTION_CONTEXT': '访问函数的执行上下文无法确定',
    'UNKNOWN_DMA_LIFETIME': 'DMA 所有权 / 生命周期无法确认',
    'UNKNOWN_INLINE_ASM': '内联汇编 / 汇编访问无法恢复',
    'UNKNOWN_SCAN_INVALID': '扫描期间源码发生变化，扫描失效',
    'UNKNOWN_UNMODELED_CONCURRENCY': '多核 / 未建模并发模型，无法静态证明',
    'ACCESS_NOT_ANALYZED': '声明未按当前构建分析（补充盘点）',
}

RECOVERY_ACTIONS = {
    'UNKNOWN_ADDRESS_ESCAPE': '补齐取得该地址的被调函数实现或注册关系，恢复其写副作用分析后重新扫描。',
    'UNKNOWN_RELEVANT_ALIAS': '提供该指针的赋值来源或受限证据，使 points-to 收敛后重新扫描。',
    'UNKNOWN_RELEVANT_INDIRECT_CALL': '补齐该间接调用的目标函数（赋值/表注册）后重新扫描。',
    'UNKNOWN_RELEVANT_MISSING_TU': '补齐引用该变量的编译单元（编译数据库或解析参数）后重新扫描。',
    'UNKNOWN_EXECUTION_CONTEXT': '补齐该访问函数的调用/注册关系，恢复其物理执行上下文。',
    'UNKNOWN_DMA_LIFETIME': '提供 DMA 启停、完成回调、缓冲区所有权和 Cache 一致性协议。',
    'UNKNOWN_INLINE_ASM': '提供该汇编的等效 C 语义，或改写为可解析的内建函数。',
    'UNKNOWN_SCAN_INVALID': '保持工程在扫描期间只读，然后重新扫描。',
    'UNKNOWN_UNMODELED_CONCURRENCY': '多核 / 其他调度模型尚未完整建模，须人工复核共享内存、HSEM、Cache 和屏障。',
    'ACCESS_NOT_ANALYZED': '补齐该源码 / 构建变体的真实编译命令后重新分析访问。',
}

# 使整个扫描失效（fail-closed）的工程级事实：任何变量都不能据此判安全。
GLOBAL_SCAN_INVALID_KINDS = {'SOURCE_CHANGED_DURING_SCAN', 'HEADER_CHANGED_DURING_SCAN'}

# 表示"工程中存在不透明机器码 / 未解析代码"的事实。只有当变量的地址或
# 可能指向它的指针进入这些不透明代码时，才与该变量相关。
OPAQUE_CODE_KINDS = {'EXTERNAL_CALLEE', 'INDIRECT_CALL', 'UNRESOLVED_POINTEE',
                     'INLINE_ASSEMBLY', 'ASSEMBLY_SOURCE_REVIEW'}

# 函数入口不确定性：该函数（及其调用子树）可能在不明物理上下文中执行。
ENTRY_UNCERTAIN_KINDS = {
    'MISSING_SOURCE_CALLER',            # 未解析源码按名称引用了该函数
    'UNRESOLVED_REGISTERED_ENTRY',      # 注册 API 的回调参数无法恢复
    'UNRESOLVED_TASK_ENTRY',            # RTOS 创建任务入口无法恢复
    'TASK_ENTRY_WITHOUT_DEFINITION',    # 注册的入口没有定义
    'CMSIS_V1_TASK_ENTRY',              # CMSIS v1 宏注册
    'AMBIGUOUS_ENTRY_REGISTRATION',     # 多条注册规则冲突
    'UNRESOLVED_CONFIG_CALL',           # 配置的调用边无法解析
    'CPP_SEMANTICS_REVIEW',             # C++ 方法调用语义保守处理
    'UNMATCHED_CONTEXT',                # 配置上下文未匹配任何函数
    'UNRESOLVED_CALL_TARGET_FN',        # 函数地址流入无法解析的间接调用
}

# 变量直接绑定的 unknown kind -> 精准 UNKNOWN reason code。
SYMBOL_UNKNOWN_CODES = {
    'DMA_SHARED_REVIEW': 'UNKNOWN_DMA_LIFETIME',
    'SOURCE_NOT_IN_DATABASE': 'UNKNOWN_RELEVANT_MISSING_TU',
    'ASSEMBLY_SYMBOL_REFERENCE': 'UNKNOWN_INLINE_ASM',
    # 地址经已解析函数中转后，流入目标无法解析的间接调用（传递性逃逸）。
    'UNRESOLVED_CALL_ESCAPE': 'UNKNOWN_ADDRESS_ESCAPE',
}

# 异步源启用 API：初始化阶段证明（SAFE_INIT_ONLY_WRITE）使用。覆盖 NVIC、
# SysTick、HAL 外设 IT/DMA 启动与 RTOS 调度入口；发生即视为异步执行已可用。
ASYNC_ENABLE_APIS = {'NVIC_EnableIRQ', 'HAL_NVIC_EnableIRQ', '__enable_irq',
                     'SysTick_Config', 'HAL_SYSTICK_Config', 'HAL_SYSTICK_CLKSourceConfig',
                     'HAL_TIM_Base_Start_IT', 'HAL_TIM_OC_Start_IT', 'HAL_TIM_PWM_Start_IT',
                     'HAL_TIM_IC_Start_IT', 'HAL_TIM_Encoder_Start_IT',
                     'HAL_TIM_Base_Start_DMA', 'HAL_TIM_OC_Start_DMA', 'HAL_TIM_PWM_Start_DMA',
                     'HAL_UART_Receive_IT', 'HAL_UART_Transmit_IT',
                     'HAL_UART_Receive_DMA', 'HAL_UART_Transmit_DMA',
                     'HAL_SPI_Receive_IT', 'HAL_SPI_Transmit_IT',
                     'HAL_SPI_Receive_DMA', 'HAL_SPI_Transmit_DMA',
                     'HAL_I2C_Receive_IT', 'HAL_I2C_Slave_Receive_IT',
                     'HAL_I2C_Receive_DMA', 'HAL_I2C_Slave_Receive_DMA',
                     'HAL_ADC_Start_IT', 'HAL_ADC_Start_DMA',
                     'HAL_DAC_Start_IT', 'HAL_DAC_Start_DMA',
                     'HAL_LPTIM_Counter_Start_IT', 'HAL_RTC_SetAlarm_IT',
                     'osKernelStart', 'osKernelInitialize', 'vTaskStartScheduler'}

INTERLEAVING_RELATIONS = {'CAN_PREEMPT', 'MAY_INTERLEAVE', 'MAY_REENTER', 'UNKNOWN_PREEMPTION'}

# 破坏性模式码（规划 §4.4）：SUSPECT 的结构化原因，供根因统计与反事实
# 分析使用；文字 reason 只是展示层。检测器本身不变（OPT-02 只结构化输出）。
DESTRUCTIVE_LABELS = {
    'D-01': '跨域写-写（含 RMW）且可交错',
    'D-02': '可重入写者',
    'D-03': 'CPU↔DMA 重叠且至少一方写',
    'D-04': '位域容器跨上下文并发修改',
    'D-05': 'union/重叠视图跨域写',
    'D-06': '整对象写 ↔ 成员访问跨域',
    'D-07': '多字段一致性（撕裂快照）',
    'D-08': '非原子宽度共享',
    'D-09': '中间值暴露',
    'D-10': '可见性',
    'D-11': '配置所有权违例',
    'D-12': 'NMI/HardFault 参与的写冲突',
}


def _iter_definitions(facts):
    return {f['function_id']: f for f in facts['functions']}


class ClassificationModel:
    """每个变量共享的物理执行域 / 入口不确定性 / 逃逸证据索引。"""

    def __init__(self, facts, contexts, relations, paths, cfg, coverage):
        self.facts = facts
        self.cfg = cfg
        self.coverage = coverage
        self.contexts = contexts
        self.paths = paths
        self.funcs = _iter_definitions(facts)
        self.variables = {v['symbol_id']: v for v in facts['variables']}
        self.domain = context_domains(contexts)
        self.domain_pair_relation = self._domain_relations(relations)
        self.reentrant_domains = {self.domain[c] for c in contexts if contexts[c].get('reentrant')}
        self.summarized = self._summarized_apis()
        self.ranges_by_file = self._unresolved_call_ranges()
        self.opaque_code = self._opaque_code_exists()
        # 名称可达性缺口：只有缺失编译单元 / 未展开汇编才可能按名称引用
        # 外部链接对象。工程其它位置存在未解析间接调用不构成名称可达。
        self.build_closure_incomplete = bool(
            coverage.get('unlisted_sources') or coverage.get('translation_units_failed')
            or any(u.get('kind') == 'ASSEMBLY_SOURCE_REVIEW' for u in facts['unknowns']))
        self.global_blockers = self._global_blockers()
        self.address_escape = {}       # sid -> evidence dict
        self.fn_address_escape = set() # function ids handed to opaque code
        # 写入声明为 const 且非 volatile 的对象是 C 未定义行为，且在
        # Cortex-M 上 const 静态存储位于 flash：运行期写物理不可能。
        # 这些变量的地址即使流入不透明代码也不构成可写路径。
        self.impossible_write_sids = self._impossible_write_sids()
        self.asm_symbol_refs = self._assembly_symbol_references()
        self._collect_pointer_escapes()
        self._collect_address_escapes()
        self._propagate_table_function_escapes()
        self.entry_uncertain = self._entry_uncertain_functions()
        self.dead_functions = self._dead_functions()
        self.points_to_limit = any(u.get('kind') == 'POINTS_TO_LIMIT' for u in facts['unknowns'])
        self.enable_events = self._async_enable_events()
        self.word_bytes = max(1, (cfg.get('project', {}).get('native_word_bits', 32) or 32) // 8)
        # 多字段一致性 flagged 成员（analysis 在访问聚合后填充）。
        self.coherent_members = set()
        self._build_phase_model()

    # -- 域间关系 ---------------------------------------------------------

    def _domain_relations(self, relations):
        """Aggregate per-context relations into per-domain-pair relations.

        大型工程的每个 IRQ vector 都是独立域，域对数量是上下文数的平方
        量级；逐对枚举是组合爆炸。只有存在 relation 证据的域对需要显式
        聚合，缺失的域对在 ``domains_may_interleave`` 中默认
        MAY_INTERLEAVE，与逐对枚举的结果完全一致。
        """
        result = {}
        for r in relations:
            first, second = r['contexts']
            a, b = self.domain.get(first, first), self.domain.get(second, second)
            if a == b:
                continue
            key = (a, b) if a < b else (b, a)
            result.setdefault(key, set()).add(r['relation'])
        return {key: ('SERIAL' if names == {'SERIAL'} else 'MAY_INTERLEAVE')
                for key, names in result.items()}

    def domains_may_interleave(self, first, second):
        if first == second:
            return first in self.reentrant_domains
        key = (first, second) if first < second else (second, first)
        return self.domain_pair_relation.get(key, 'MAY_INTERLEAVE') != 'SERIAL'

    # -- 不透明代码 / 未解析调用范围 ---------------------------------------

    def _summarized_apis(self):
        from .protection import NEUTRAL
        from .common import LIBC_FUNCTION_NAMES
        # 定长标准 C 库函数的参数语义由 C 标准确定（ecra.common）：
        # 语义已知 ⇒ 不是不透明代码，其调用点参数中的地址不构成逃逸。
        summarized = {'xTaskCreate', 'xTaskCreateStatic',
                      'osThreadNew', 'xTaskCreatePinnedToCore', '__disable_irq', '__enable_irq',
                      '__get_PRIMASK', '__set_PRIMASK', '__get_BASEPRI', '__set_BASEPRI',
                      '__set_BASEPRI_MAX', '__disable_fault_irq', '__enable_fault_irq'}
        summarized |= LIBC_FUNCTION_NAMES
        summarized.update(NEUTRAL)
        summarized.update(s[k] for s in self.cfg.get('critical_sections', [])
                          for k in ('enter', 'exit', 'save', 'restore') if k in s)
        return summarized

    def _unresolved_call_ranges(self):
        """未解析调用的源码区间：参数中的地址 / 函数地址会进入不透明代码。"""
        # 指针求解已恢复目标的间接调用点不再是不透明代码：其参数中的
        # 地址只流向已知的被调函数，不构成逃逸。
        resolved_sites = {(c.get('caller_function_id'), c.get('file'), c.get('offset'))
                          for c in self.facts['calls']
                          if c.get('call_kind') == 'INDIRECT_RESOLVED'}
        ranges = defaultdict(list)
        for call in self.facts['calls']:
            callee = call.get('callee_function_id')
            # ASSEMBLY edges connect inline-asm operands to their target
            # functions; they are resolved reachability, not opaque calls.
            resolved = call.get('call_kind') in {'DIRECT', 'INDIRECT_RESOLVED', 'CONFIGURED', 'ASSEMBLY'} and callee in self.funcs
            if resolved or call.get('callee_name') in self.summarized:
                continue
            if ((call.get('call_kind') == 'INDIRECT')
                    and (call.get('caller_function_id'), call.get('file'), call.get('offset')) in resolved_sites):
                continue
            start = call.get('offset')
            end = call.get('end_offset') or start
            if start is not None:
                ranges[call.get('file')].append((start, end))
        for u in self.facts['unknowns']:
            if u.get('kind') == 'INDIRECT_CALL' and u.get('offset') is not None:
                if (u.get('function_id'), u.get('file'), u.get('offset')) in resolved_sites:
                    continue
                ranges[u.get('file')].append((u['offset'], u.get('end_offset') or u['offset']))
        return ranges

    def in_unresolved_range(self, file, offset):
        if file is None or offset is None:
            return False
        return any(start <= offset <= end for start, end in self.ranges_by_file.get(file, ()))

    def _opaque_code_exists(self):
        if any(u.get('kind') in OPAQUE_CODE_KINDS for u in self.facts['unknowns']):
            return True
        return bool(self.coverage.get('unlisted_sources') or self.coverage.get('translation_units_failed'))

    def _global_blockers(self):
        blockers = sorted({u['kind'] for u in self.facts['unknowns']
                           if u.get('kind') in GLOBAL_SCAN_INVALID_KINDS})
        project = self.cfg.get('project', {})
        if project.get('cm4_enabled') or project.get('concurrency_model', 'single_core_preemptive') != 'single_core_preemptive':
            blockers.append('UNKNOWN_UNMODELED_CONCURRENCY')
        return blockers

    # -- 地址 / 函数地址逃逸 ------------------------------------------------

    def _impossible_write_sids(self):
        """const 且非 volatile 的变量（含 const root 下的成员）不可运行期写。"""
        impossible = set()
        for v in self.variables.values():
            cursor, seen = v, set()
            is_const = is_volatile = False
            while cursor is not None and cursor['symbol_id'] not in seen:
                seen.add(cursor['symbol_id'])
                is_volatile = is_volatile or bool(cursor.get('is_volatile'))
                is_const = is_const or bool(cursor.get('is_const'))
                root_sid = cursor.get('root_symbol_id')
                cursor = self.variables.get(root_sid) if root_sid else None
            if is_const and not is_volatile:
                impossible.add(v['symbol_id'])
        return impossible

    def _collect_pointer_escapes(self):
        """points-to 已恢复的地址流：进入不透明代码即构成逃逸证据。"""
        from .common import LIBC_FUNCTION_NAMES
        for row in self.facts.get('pointer_targets', []):
            location, targets = row['location'], row['targets']
            root = location.split('/', 1)[0]
            reason = None
            if root.startswith('obj:'):
                owner = self.variables.get(root[4:])
                # 构建闭包不完整时，缺失编译单元可以按名称 extern 引用
                # 外部链接对象。闭包完整时，地址必须实际流入不透明代码
                # （参数、间接调用、汇编引用）才算逃逸；工程其它位置存在
                # 未解析调用不会让存入外部全局的地址凭空逃逸。
                if (owner is not None and owner.get('linkage') == 'EXTERNAL'
                        and self.build_closure_incomplete):
                    reason = ("该地址存储于外部链接对象 " + owner.get('qualified_name', root[4:])
                              + "，缺失的编译单元可按名称获得它")
            elif ':param:' in root:
                fid = root.rsplit(':param:', 1)[0]
                if fid not in self.funcs:
                    # OPT-19（FS-10）：函数 ID 可能是 USR（c:@F@strcpy），
                    # 旧的裸名集合比较永远不匹配。统一按被调函数名查定长
                    # 标准库语义表：语义已知（参数方向由 C 标准确定、不保留
                    # 指针）的函数不是不透明代码，读取方向的实参不构成写
                    # 逃逸；写方向已按参数语义记为访问行。
                    from .common import libc_function_name
                    if libc_function_name(fid) not in LIBC_FUNCTION_NAMES:
                        reason = '该地址作为参数流入未解析函数 ' + fid
            if not reason:
                continue
            for target in targets:
                if target.startswith('obj:'):
                    evidence = dict(kind='ADDRESS_ESCAPE', location=location,
                                    explanation=reason, evidence_layer='pointer_solver')
                    self.address_escape.setdefault(target[4:], evidence)
                elif target.startswith('fn:'):
                    self.fn_address_escape.add(target[3:])

    def _propagate_table_function_escapes(self):
        """地址已逃逸（或被汇编按名称引用）的对象中存放的函数指针。

        不透明代码获得该对象后可以经它间接调用这些函数，因此它们可能
        从未恢复的物理上下文进入执行。
        """
        for row in self.facts.get('pointer_targets', []):
            root = row['location'].split('/', 1)[0]
            if not root.startswith('obj:'):
                continue
            owner_sid = root[4:]
            if owner_sid in self.address_escape or owner_sid in self.asm_symbol_refs:
                self.fn_address_escape.update(t[3:] for t in row['targets'] if t.startswith('fn:'))

    def _collect_address_escapes(self):
        """取地址表达式落在未解析调用参数内 => 地址进入不透明代码。"""
        for u in self.facts['unknowns']:
            if u.get('kind') != 'ADDRESS_ESCAPE' or not u.get('symbol_id'):
                continue
            if self.in_unresolved_range(u.get('file'), u.get('offset')):
                self.address_escape.setdefault(u['symbol_id'], dict(
                    kind='ADDRESS_ESCAPE', file=u.get('file'), line=u.get('line'),
                    explanation='该变量地址作为参数传给了无法解析的函数', evidence_layer='call_site'))

    # -- 入口不确定性 -------------------------------------------------------

    def _entry_uncertain_functions(self):
        uncertain = set()
        has_context = set(self.paths)
        resolved_indirect = {c['callee_function_id'] for c in self.facts['calls']
                             if c.get('call_kind') == 'INDIRECT_RESOLVED' and c.get('callee_function_id')}
        for u in self.facts['unknowns']:
            kind = u.get('kind')
            fid = u.get('target_function_id') or u.get('function_id')
            if kind == 'FUNCTION_ADDRESS' and fid:
                if (fid not in has_context and fid not in resolved_indirect
                        and fid not in self.fn_address_escape):
                    # 地址被取得，但没有任何已解析的调度/调用边恢复其执行路径。
                    uncertain.add(fid)
                elif self.in_unresolved_range(u.get('file'), u.get('offset')) or fid in self.fn_address_escape:
                    # 地址交给了不透明代码：可能从任何上下文被回调。
                    uncertain.add(fid)
            elif kind in ENTRY_UNCERTAIN_KINDS and fid:
                uncertain.add(fid)
        uncertain |= self.fn_address_escape
        # 不确定性沿调用图前向传播：入口不明时，整个调用子树都可能在
        # 未知物理上下文中执行。
        graph = defaultdict(set)
        for call in self.facts['calls']:
            if call.get('callee_function_id'):
                graph[call['caller_function_id']].add(call['callee_function_id'])
        queue = deque(uncertain)
        while queue:
            fid = queue.popleft()
            for callee in graph[fid]:
                if callee not in uncertain:
                    uncertain.add(callee)
                    queue.append(callee)
        return uncertain

    # -- 不可达（可证明死亡）函数 -------------------------------------------

    def _asm_name_references(self):
        names = defaultdict(set)
        for u in self.facts['unknowns']:
            if u.get('kind') != 'INLINE_ASSEMBLY':
                continue
            for token in set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*', u.get('source_text', '') or '')):
                names[token].add(u.get('file'))
        return names

    def _dead_functions(self):
        """按函数粒度证明死亡：无任何已解析入口，且无任何入口证据。

        file/function-static 函数在不取地址且无调用边时，任何其它 TU 或
        库代码都无法通过名称访问它。外部链接函数只有在构建闭包完整且
        工程中不存在不透明代码时才可证明死亡。
        """
        roots = set(self.paths)
        for u in self.facts['unknowns']:
            fid = u.get('target_function_id') or u.get('function_id')
            if fid and u.get('kind') not in {'EXTERNAL_CALLEE', 'INDIRECT_CALL', 'POINTER_DEREFERENCE',
                                             'POINTER_SUBSCRIPT', 'UNRESOLVED_POINTEE'}:
                roots.add(fid)
        roots |= {r['function_id'] for r in self.facts.get('registrations', [])}
        for f in self.facts['functions']:
            if f.get('entry_attributes') or f.get('linkage') in {'HARDWARE'}:
                roots.add(f['function_id'])
        # 内联汇编文本中出现的函数名可能是真实调用目标。
        asm_names = self._asm_name_references()
        for f in self.facts['functions']:
            if f['name'] in asm_names:
                roots.add(f['function_id'])
        if self.opaque_code:
            # 不透明代码可按名称调用任何外部链接函数（weak override 等）。
            roots.update(f['function_id'] for f in self.facts['functions']
                         if f.get('linkage') == 'EXTERNAL')
        graph = defaultdict(set)
        for call in self.facts['calls']:
            if call.get('callee_function_id'):
                graph[call['caller_function_id']].add(call['callee_function_id'])
        reachable = set()
        queue = deque(roots)
        while queue:
            fid = queue.popleft()
            if fid in reachable:
                continue
            reachable.add(fid)
            queue.extend(graph[fid])
        return {f['function_id'] for f in self.facts['functions']} - reachable

    # -- 汇编对变量的直接引用 ------------------------------------------------

    def _assembly_symbol_references(self):
        refs = {}
        for u in self.facts['unknowns']:
            if u.get('kind') == 'ASSEMBLY_SYMBOL_REFERENCE' and u.get('symbol_id'):
                refs.setdefault(u['symbol_id'], u)
        # OPT-14（FS-5）：只要工程中存在内联汇编就扫描汇编文本中的变量名。
        # 旧条件 `self.opaque_code is False` 恰好写反——内联汇编本身使
        # opaque_code 为真，扫描从未执行，汇编文本写入被判只读（P23）。
        # 性能：逐汇编 × 逐变量做正则是 O(N_asm × N_var) 乘积爆炸
        # （betaflight ~5875 s）；先按外部变量建 Aho-Corasick 式词表——
        # 变量数有限，逐汇编一次扫描所有候选词的匹配用简单子串预过滤 +
        # 词边界正则确认，仅对文本中出现候选子串的变量执行。
        if any(u.get('kind') == 'INLINE_ASSEMBLY' for u in self.facts['unknowns']):
            externals = [v for v in self.facts['variables'] if v.get('linkage') == 'EXTERNAL']
            patterns = {}
            for v in externals:
                try:
                    patterns[v['symbol_id']] = re.compile(
                        r'\b' + re.escape(v['name']) + r'\b')
                except re.error:
                    continue
            for u in self.facts['unknowns']:
                if u.get('kind') != 'INLINE_ASSEMBLY':
                    continue
                text = u.get('source_text', '') or ''
                modeled = set(u.get('modeled_operand_sids') or ())
                for v in externals:
                    sid = v['symbol_id']
                    if sid in modeled or sid in refs:
                        # 操作数语义已恢复的变量不按文本重报（OPT-14）；
                        # 已有引用记录的变量保留首条证据。
                        continue
                    pattern = patterns.get(sid)
                    if pattern is None or v['name'] not in text:
                        continue
                    if pattern.search(text):
                        refs.setdefault(sid, dict(
                            kind='INLINE_ASSEMBLY', file=u.get('file'), line=u.get('line'),
                            source_text=text[:200], explanation='内联汇编文本引用了该外部变量名'))
        return refs

    # -- 初始化阶段启用事件 --------------------------------------------------

    def _async_enable_events(self):
        events = defaultdict(list)
        for call in self.facts['calls']:
            if call.get('callee_name') in ASYNC_ENABLE_APIS:
                events[call['caller_function_id']].append(call)
        return events

    def _main_function_id(self):
        mains = [cid for cid, c in self.contexts.items() if c.get('kind') == 'MAIN']
        main_roots = {b['function_id'] for b in self.facts.get('context_bindings', [])
                      if b['call_depth'] == 0 and b['context_id'] in mains}
        for fid in main_roots:
            if self.funcs.get(fid, {}).get('name') == 'main':
                return fid
        return next(iter(main_roots), None)

    def init_only_write_proof(self, writes, runtime_accesses):
        """SAFE_INIT_ONLY_WRITE：所有写只发生在异步源启用之前。"""
        if not writes:
            return False
        main_fid = self._main_function_id()
        if main_fid is None:
            return False
        if any(a['function_id'] != main_fid for a in writes):
            return False
        enable_offsets = [e.get('offset') for e in self.enable_events.get(main_fid, [])]
        # OPT-13（FS-3）：未知使能点（外部函数 / 未解析间接调用 / 内联汇编）
        # 同样终止初始化窗口；识别不了使能机制不等于使能不存在。
        enable_offsets.extend(self.unknown_enable_offsets.get(main_fid, ()))
        enable_offsets = [e for e in enable_offsets if e is not None and e >= 0]
        if not enable_offsets:
            return False
        first_enable = min(enable_offsets)
        if any(a.get('offset', -1) >= first_enable for a in writes):
            return False
        if any(a.get('conditional_ancestor') for a in writes):
            return False
        # 其它函数若也启用了异步源（含未知使能点），无法证明先后顺序。
        for fid in list(self.enable_events) + list(self.unknown_enable_offsets):
            if fid != main_fid and self._reachable_from(fid, main_fid):
                return False
        # 非前台访问必须全部为 READ（缺口类 UNKNOWN 已在此之前拦截）。
        for a in runtime_accesses:
            for cid in a.get('contexts', ()):
                if self.domain[cid] != 'FOREGROUND' and a['access_kind'] != 'READ':
                    return False
        return True

    def _reachable_from(self, target, start):
        graph = defaultdict(set)
        for call in self.facts['calls']:
            if call.get('callee_function_id'):
                graph[call['caller_function_id']].add(call['callee_function_id'])
        seen, queue = set(), deque([start])
        while queue:
            fid = queue.popleft()
            if fid == target:
                return True
            if fid in seen:
                continue
            seen.add(fid)
            queue.extend(graph[fid])
        return False

    # -- 初始化 / 运行期相位（transitive init-phase proof） ------------------

    def _build_phase_model(self):
        """phase(F)=PRE：F 的每次执行都发生在任何异步源启用之前。

        传递定义（Section 6 泛化，声音性优先）::

            边 (C, off) 是 PRE ⟺ phase(C)=PRE
                                 ∧ C 体内 off 之前没有直接启用调用
                                 ∧ C 体内 off 之前没有调用"可能包含启用"的函数
                                 ∧ ¬(off 位于 C 的循环体内 ∧ C 可能包含启用)

            phase(F) = PRE ⟺ F 至少有一条入边且全部入边都是 PRE 边。
            根：main 入口为 PRE；ISR/DMA/注册入口与无入边函数为 RUNTIME。

        启用后调用的初始化函数如实降级为 RUNTIME 写者（仍可走单写者共享
        规则）；无启用事件的工程不产生 PRE 证明（无异步即单前台域）。
        """
        calls_by_caller = defaultdict(list)
        for c in self.facts['calls']:
            if c.get('callee_function_id'):
                calls_by_caller[c['caller_function_id']].append(c)
        incoming = defaultdict(list)
        for c in self.facts['calls']:
            if c.get('callee_function_id'):
                incoming[c['callee_function_id']].append(c)
        direct_enable_offsets = defaultdict(list)
        for c in self.facts['calls']:
            if c.get('callee_name') in ASYNC_ENABLE_APIS and c.get('offset') is not None:
                direct_enable_offsets[c['caller_function_id']].append(c['offset'])
        # OPT-13（FS-3）：fail-closed 使能事件（UNKNOWN_MAY_ENABLE）。下列
        # 调用点之后不能再证明"异步源尚未启用"：无定义且无标准语义摘要的
        # 外部函数、未解析间接调用、语义未知的内联汇编。识别不了使能机制
        # 不等于使能不存在——PRE 证明宁可不成立。
        unknown_enable_offsets = defaultdict(list)
        for c in self.facts['calls']:
            off = c.get('offset')
            if off is None or c.get('caller_function_id') not in self.funcs:
                continue
            callee_fid = c.get('callee_function_id')
            if callee_fid and callee_fid in self.funcs:
                continue    # 已定义目标：使能效果经 may_enable 反向传播覆盖
            if (c.get('callee_name') in self.summarized
                    or c.get('callee_name') in ASYNC_ENABLE_APIS):
                continue    # 定长标准库 / 屏蔽内建 / 已识别使能 API：语义已知
            # 只有声明没有定义的函数（外部库 / 缺失 TU）：其副作用未知，
            # 可能使能某个中断 → UNKNOWN_MAY_ENABLE（fail-closed，FS-3）。
            unknown_enable_offsets[c['caller_function_id']].append(off)
        for u in self.facts['unknowns']:
            if (u.get('kind') == 'INLINE_ASSEMBLY' and u.get('function_id') in self.funcs
                    and u.get('offset') is not None):
                unknown_enable_offsets[u['function_id']].append(u['offset'])
        may_enable = {fid for fid, offs in direct_enable_offsets.items() if offs}
        may_enable.update(fid for fid, offs in unknown_enable_offsets.items() if offs)
        # init_only_write_proof 同样使用未知使能点（OPT-13）。
        self.unknown_enable_offsets = unknown_enable_offsets
        # 反向传播：调用者的执行包含被调者的启用效果（callee 有启用 =>
        # caller 可能在启用后继续运行）。
        callers_of = defaultdict(list)
        for c in self.facts['calls']:
            if c.get('callee_function_id'):
                callers_of[c['callee_function_id']].append(c['caller_function_id'])
        changed = True
        while changed:
            changed = False
            for fid in list(may_enable):
                for caller in callers_of.get(fid, ()):
                    if caller not in may_enable:
                        may_enable.add(caller)
                        changed = True
        # 循环体偏移（CFG 回边可达节点集合）。只对 may_enable 的函数计算
        # （其余函数的 in_loop_with_enable 恒为 False）。
        # 算法：迭代 Tarjan SCC——"节点在循环体内" ⟺ 位于 size>1 的强
        # 连通分量或存在自环。旧的"每个起点一次带 path 列表的 DFS"是
        # O(V²·E) 且路径拷贝昂贵，blackmagic 规模下单此循环 ~590 s
        # （基线因 main_reachable 守门几乎总提前返回从未暴露；OPT-13 的
        # 未知使能点使 may_enable & main_reachable 非空后首次触发）。
        loop_offsets = defaultdict(set)
        for g in self.facts.get('control_flow', []):
            if g['function_id'] not in may_enable:
                continue
            succs = defaultdict(list)
            for n in g['nodes']:
                for s in n['successors']:
                    if s != n['id']:
                        succs[n['id']].append(s)
                    elif n.get('offset') is not None:
                        # 自环节点本身在循环体内。
                        loop_offsets[g['function_id']].add(
                            (n['offset'], n.get('end_offset') or n['offset']))
            on_cycle = set()
            index, lowlink, on_stack = {}, {}, set()
            stack, call = [], []
            next_index = [0]
            for root in list(succs):
                if root in index:
                    continue
                index[root] = lowlink[root] = next_index[0]
                next_index[0] += 1
                stack.append(root); on_stack.add(root)
                call.append((root, iter(succs[root])))
                while call:
                    node, it = call[-1]
                    advanced = False
                    for nxt in it:
                        if nxt not in index:
                            index[nxt] = lowlink[nxt] = next_index[0]
                            next_index[0] += 1
                            stack.append(nxt); on_stack.add(nxt)
                            call.append((nxt, iter(succs[nxt])))
                            advanced = True
                            break
                        elif nxt in on_stack:
                            lowlink[node] = min(lowlink[node], index[nxt])
                    if advanced:
                        continue
                    call.pop()
                    if call:
                        parent = call[-1][0]
                        lowlink[parent] = min(lowlink[parent], lowlink[node])
                    if lowlink[node] == index[node]:
                        component = []
                        while True:
                            member = stack.pop()
                            on_stack.discard(member)
                            component.append(member)
                            if member == node:
                                break
                        if len(component) > 1:
                            on_cycle.update(component)
            if not on_cycle:
                continue
            for n in g['nodes']:
                if n['id'] in on_cycle and n.get('offset') is not None:
                    loop_offsets[g['function_id']].add(
                        (n['offset'], n.get('end_offset') or n['offset']))

        # blocked_at 的调用边预索引：caller → 按偏移排序的 (offset, callee)
        # 列表，只保留 callee ∈ may_enable 的边。旧实现对每个查询线性扫描
        # 调用者全部调用边，may_enable 因 OPT-13 的未知使能点扩大后成为
        # 平方级热点（blackmagic analyze 604 s 中 877 s CPU 的主因）。
        enable_call_edges = defaultdict(list)
        for fid, rows in calls_by_caller.items():
            edges = [(c['offset'], c['callee_function_id']) for c in rows
                     if c.get('offset') is not None and c.get('callee_function_id') in may_enable]
            if edges:
                edges.sort()
                enable_call_edges[fid] = edges

        def blocked_at(fid, off):
            for e in direct_enable_offsets.get(fid, ()):
                if e < off:
                    return True
            # OPT-13：未知使能点之后无法证明 PRE。
            for e in unknown_enable_offsets.get(fid, ()):
                if e < off:
                    return True
            import bisect
            edges = enable_call_edges.get(fid)
            if edges:
                i = bisect.bisect_left(edges, (off, ''))
                if i > 0:
                    return True
            return False

        def in_loop_with_enable(fid, off):
            if not loop_offsets.get(fid) or fid not in may_enable:
                return False
            for lo, hi in loop_offsets[fid]:
                if lo <= off <= hi:
                    return True
            return False

        def edge_is_pre(c):
            caller, off = c['caller_function_id'], c.get('offset')
            if caller not in self.funcs or off is None:
                return False
            if blocked_at(caller, off):
                return False
            return not in_loop_with_enable(caller, off)

        async_roots = set()
        for b in self.facts.get('context_bindings', []):
            if b['call_depth'] == 0 and self.contexts.get(b['context_id'], {}).get('kind') != 'MAIN':
                async_roots.add(b['function_id'])
        for f in self.facts['functions']:
            if f.get('entry_attributes') or f.get('linkage') == 'HARDWARE':
                async_roots.add(f['function_id'])
        main_fids = {b['function_id'] for b in self.facts.get('context_bindings', [])
                     if b['call_depth'] == 0 and self.contexts.get(b['context_id'], {}).get('kind') == 'MAIN'}
        # 前提守门：只有 main 可达代码中确实存在启用调用（异步源在复位后
        # 某一时刻才打开）才存在"启用前的初始化窗口"。没有任何启用事件的
        # 工程，中断从复位即可能活�动，初始化期证明整体不适用。
        main_reachable = set(main_fids)
        frontier = list(main_fids)
        while frontier:
            fid = frontier.pop()
            for c in calls_by_caller.get(fid, ()):
                callee = c.get('callee_function_id')
                if callee and callee not in main_reachable:
                    main_reachable.add(callee)
                    frontier.append(callee)
        if not (may_enable & main_reachable):
            self.phase = {}
            self._phase_blocked = lambda fid, off: False
            self._phase_loop_guard = lambda fid, off: False
            self._phase_may_enable_any = {}
            return
        phase = {}
        queue = deque()
        for fid in self.funcs:
            # main 入口（无入边）是 PRE 根；其余无入边函数入口不明 → RUNTIME。
            if fid in async_roots or (not incoming.get(fid) and fid not in main_fids):
                phase[fid] = 'RUNTIME'
                queue.append(fid)
        for fid in main_fids:
            if fid not in phase:
                phase[fid] = 'PRE'
        while queue:
            runtime_caller = queue.popleft()
            for c in calls_by_caller.get(runtime_caller, ()):
                callee = c.get('callee_function_id')
                if callee and phase.get(callee) != 'RUNTIME':
                    phase[callee] = 'RUNTIME'
                    queue.append(callee)
        # 未被 RUNTIME 洪水覆盖的函数默认 PRE 候选，随后按入边阻断降级。
        for fid in self.funcs:
            if fid not in phase:
                phase[fid] = 'PRE'
        pending = deque(fid for fid, p in phase.items() if p == 'PRE')
        while pending:
            fid = pending.popleft()
            if phase.get(fid) != 'PRE':
                continue
            edges = incoming.get(fid, ())
            if edges and any(not edge_is_pre(c) for c in edges):
                phase[fid] = 'RUNTIME'
                for c in calls_by_caller.get(fid, ()):
                    callee = c.get('callee_function_id')
                    if callee and phase.get(callee) != 'RUNTIME':
                        phase[callee] = 'RUNTIME'
                        pending.append(callee)
        may_enable_any = {}
        for fid in self.funcs:
            if fid in may_enable or any(
                    c.get('callee_function_id') in may_enable
                    for c in calls_by_caller.get(fid, ())):
                may_enable_any[fid] = True
        self.phase = phase
        self._phase_blocked = blocked_at
        self._phase_loop_guard = in_loop_with_enable
        self._phase_may_enable_any = may_enable_any

    def is_pre_write(self, function_id, offset, conditional_ancestor=False):
        """写站点是否可证明发生在全部异步源启用之前。

        函数自身包含启用效果时，条件分支/循环内的写点无法用源码偏移证明
        与启用的先后（CFG 循环未建模时同样无法排除回边），宁可放弃证明。
        """
        if self.phase.get(function_id) != 'PRE' or offset is None:
            return False
        if self._phase_blocked(function_id, offset):
            return False
        if self._phase_loop_guard(function_id, offset):
            return False
        if conditional_ancestor and self._phase_may_enable_any.get(function_id):
            return False
        return True

    # -- 单变量分类 -----------------------------------------------------------

    # C 标量类型名 → 字节宽度（用于单写者共享的原子宽度证明）。
    _SCALAR_WIDTHS = (
        ('uint64_t', 8), ('int64_t', 8), ('long long', 8), ('unsigned long long', 8),
        ('double', 8), ('uint32_t', 4), ('int32_t', 4), ('unsigned int', 4), ('int', 4),
        ('unsigned long', 4), ('long', 4), ('unsigned', 4), ('float', 4), ('size_t', 4),
        ('ssize_t', 4), ('intptr_t', 4), ('uintptr_t', 4), ('ptrdiff_t', 4),
        ('uint16_t', 2), ('int16_t', 2), ('unsigned short', 2), ('short', 2),
        ('uint8_t', 1), ('int8_t', 1), ('unsigned char', 1), ('signed char', 1),
        ('char', 1), ('bool', 1), ('_Bool', 1),
    )

    def _element_width(self, variable):
        """声明类型解析出的元素宽度（字节）；无法识别返回 None。

        指针类型按目标机字宽处理；数组取元素类型（访问按元素粒度记录）。
        """
        if variable.get('is_struct') or variable.get('is_bitfield_container'):
            return None
        type_text = (variable.get('type') or '').strip()
        base = type_text.split('[')[0].strip().rstrip('*').strip()
        if '*' in (variable.get('type') or ''):
            return max(1, self.word_bytes)
        for name, width in self._SCALAR_WIDTHS:
            if base == name or base.endswith(' ' + name) or base.endswith('unsigned ' + name):
                return width
        if not base:
            return None
        return None

    def _effective_alignment(self, variable):
        """单指令原子证明使用的有效对齐（OPT-15，FS-6）。

        结构体成员取 analysis 计算的 ``effective_alignment_bytes``（已并入
        偏移整除性与根对象对齐）；顶层变量退回声明对齐。
        """
        effective = variable.get('effective_alignment_bytes')
        if effective is not None:
            return effective
        return variable.get('alignment_bytes')

    def classify(self, variable, accesses, symbol_unknowns, protection):
        """四类裁决：SUSPECT / SHARED_NO_REVIEW / UNKNOWN / SAFE_PROVEN。

        最高层逻辑（destructive conflict 优先）::

            破坏性冲突（双写 / RMW 交叉 / DMA 与 CPU 至少一方写 / 位域并发写
                       / 多字段一致性 / 可重入写者，且 MHP != NO）+ 未证明有效保护
                => SUSPECT

            单一写者域 + 其余域只读 + 写者无独立读站点 + 原子宽度可证明
            + 无 DMA/逃逸/未知写者/一致性关联
                => SHARED_NO_REVIEW（共享访问，无需复核；不是 SAFE_PROVEN）

            与该变量直接相关的关键未知
                => UNKNOWN

            其余（只读 / 单一串行域 / 初始化期写入 / 有效保护……）
                => SAFE_PROVEN
        """
        sid = variable['symbol_id']
        runtime = [a for a in accesses if a.get('access_kind') in {'READ', 'WRITE', 'RMW'}]
        writes = [a for a in runtime if a['access_kind'] in {'WRITE', 'RMW'}]
        # 初始化期写入（PRE 相位证明）：发生在任何异步源启用之前，与运行期
        # 访问有序，不参与破坏性冲突枚举。
        pre_writes = {id(a) for a in writes
                      if self.is_pre_write(a['function_id'], a.get('offset', -1),
                                           a.get('conditional_ancestor'))}
        all_writers_pre = bool(writes) and all(id(a) in pre_writes for a in writes)
        domain_kinds = defaultdict(set)
        domain_of_context = self.domain
        dma_domains = set()
        for a in runtime:
            for cid in a.get('contexts', ()):
                domain = domain_of_context[cid]
                domain_kinds[domain].add(a['access_kind'])
                if self.contexts.get(cid, {}).get('kind') == 'DMA':
                    dma_domains.add(domain)
        unresolved_context = [a for a in runtime
                              if not a.get('contexts') or a.get('function_id') in self.entry_uncertain]

        gaps = []

        def add_gap(code, evidence):
            if not any(g['code'] == code for g in gaps):
                gaps.append(dict(code=code, evidence=evidence or {}))

        # --- 变量证据切片内的缺口（与工程其它位置无关） ---
        for kind in self.global_blockers:
            add_gap('UNKNOWN_SCAN_INVALID' if kind != 'UNKNOWN_UNMODELED_CONCURRENCY'
                    else 'UNKNOWN_UNMODELED_CONCURRENCY', dict(kind=kind))
        if sid in self.address_escape and sid not in self.impossible_write_sids:
            add_gap('UNKNOWN_ADDRESS_ESCAPE', self.address_escape[sid])
        if self.points_to_limit:
            add_gap('UNKNOWN_RELEVANT_ALIAS', dict(kind='POINTS_TO_LIMIT'))
        for u in symbol_unknowns:
            code = SYMBOL_UNKNOWN_CODES.get(u.get('kind'))
            if code:
                add_gap(code, u)
        if variable.get('parse_status') == 'FAILED':
            add_gap('UNKNOWN_RELEVANT_MISSING_TU', dict(kind='PARSE_FAILED',
                    symbol_id=sid, explanation='该符号所在编译单元解析失败'))
        if not variable.get('definition_file'):
            add_gap('UNKNOWN_RELEVANT_MISSING_TU', dict(kind='DEFINITION_MISSING',
                    symbol_id=sid, explanation='当前构建闭包内没有该变量的定义'))
        # 执行上下文未知的"写入"才构成未知写者；未知上下文的纯 READ 不与
        # 任何读发生冲突，也不隐藏其它写入（该函数体的全部访问都已提取）。
        unresolved_writes = [a for a in unresolved_context
                             if a['access_kind'] in {'WRITE', 'RMW'}]
        if unresolved_writes:
            witness = unresolved_writes[0]
            add_gap('UNKNOWN_EXECUTION_CONTEXT', dict(
                kind='EXECUTION_CONTEXT_UNRESOLVED', file=witness.get('file'), line=witness.get('line'),
                function_id=witness.get('function_id'),
                explanation='该写入所在函数的物理执行上下文无法恢复（可能从 MAIN、ISR 或未解析入口进入）'))
        # OPT-17（FS-8）：未知上下文的读不再被完全忽略。未知入口可能是 ISR：
        # 当 r 有写者且 r 不满足单拷贝原子（NR-03），或 r 属于一致性候选组时，
        # 未知读者可能读到撕裂值 / 撕裂字段组合 → 相关缺口。原子宽度且无一
        # 致性关系时读不产生新风险，但 r 不再是"单域"（见单写者分支）。
        unresolved_reads = [a for a in unresolved_context if a['access_kind'] == 'READ']
        if unresolved_reads and not unresolved_writes:
            width = self._element_width(variable)
            alignment = self._effective_alignment(variable)
            atomic = (width is not None and width <= self.word_bytes
                      and alignment is not None and alignment >= width)
            if ((writes and not atomic) or sid in self.coherent_members):
                witness = unresolved_reads[0]
                add_gap('UNKNOWN_EXECUTION_CONTEXT', dict(
                    kind='EXECUTION_CONTEXT_UNRESOLVED', access_kind='READ',
                    file=witness.get('file'), line=witness.get('line'),
                    function_id=witness.get('function_id'),
                    explanation='该读取所在函数的物理执行上下文无法恢复；变量存在写者且'
                                '访问宽度 / 一致性关系使读者可能观察到撕裂值'))
        if sid in self.asm_symbol_refs:
            add_gap('UNKNOWN_INLINE_ASM', self.asm_symbol_refs[sid])

        scan_invalid = any(g['code'] in {'UNKNOWN_SCAN_INVALID', 'UNKNOWN_UNMODELED_CONCURRENCY'}
                           for g in gaps)
        if scan_invalid:
            return dict(classification='UNKNOWN', safe_code=None,
                        reason='扫描完整性或并发模型缺口：不能据此判定安全。',
                        gaps=gaps, conflicts=[], domains=sorted(domain_kinds),
                        unresolved_context_access_count=len(unresolved_context))

        # --- 破坏性冲突模式（destructive conflict） ---
        domains = sorted(domain_kinds)
        writer_domains = [d for d in domains if domain_kinds[d] & {'WRITE', 'RMW'}]
        # 初始化期证明（Section 6）：全部写者都可证明发生在任何异步源启用
        # 之前，运行期只有读取。在"ISR 可能从复位即活"的保守语义下，PRE
        # 写者不得与任何运行期写者组合降噪（守门 G5，对应任务书
        # P0-HARD-RISK-01/02 的硬守门：任何优化都不能绕过）。
        if all_writers_pre and len(domains) >= 2:
            return dict(classification='SAFE_PROVEN', safe_code='SAFE_INIT_ONLY_WRITE',
                        reason='全部写入发生在初始化阶段（调用链传递证明：任何异步源启用之前），运行期只有读取。',
                        gaps=[], conflicts=[], domains=domains,
                        unresolved_context_access_count=len(unresolved_context))
        conflicts = []
        destructive_reasons = []
        # 结构化模式码与最小见证（OPT-02）：每条见证引用代表访问的稳定
        # evidence id 与两个域，支撑根因统计、热点聚类与后续 Stage B。
        domain_write_sample, domain_read_sample = {}, {}
        for a in runtime:
            for cid in a.get('contexts', ()):
                d = domain_of_context[cid]
                if a['access_kind'] in {'WRITE', 'RMW'}:
                    domain_write_sample.setdefault(d, a.get('access_id'))
                elif a['access_kind'] == 'READ':
                    domain_read_sample.setdefault(d, a.get('access_id'))
        destructive_codes = []
        witnesses = []
        for i, first in enumerate(domains):
            for second in domains[i + 1:]:
                if not self.domains_may_interleave(first, second):
                    continue
                if ({'WRITE', 'RMW'} & domain_kinds[first]
                        and {'WRITE', 'RMW'} & domain_kinds[second]):
                    conflicts.append((first, second))
                    destructive_codes.append('D-01')
                    witnesses.append(dict(pattern='D-01', domains=[first, second],
                                          access_ids=[x for x in (domain_write_sample.get(first),
                                                                  domain_write_sample.get(second)) if x]))
        for domain in domains:
            if domain in self.reentrant_domains and {'WRITE', 'RMW'} & domain_kinds[domain]:
                conflicts.append((domain, domain))
                destructive_codes.append('D-02')
                witnesses.append(dict(pattern='D-02', domains=[domain],
                                      access_ids=[domain_write_sample.get(domain)]))
        # CPU ↔ DMA：只要该变量同时被 DMA 和 CPU 访问且至少一方写。
        if dma_domains and writer_domains:
            dma_kinds = set().union(*(domain_kinds[d] for d in dma_domains))
            cpu_write = any(domain_kinds[d] & {'WRITE', 'RMW'} for d in domains if d not in dma_domains)
            if (dma_kinds & {'WRITE', 'RMW'} and cpu_write) or (dma_kinds & {'WRITE', 'RMW'}) or cpu_write:
                destructive_reasons.append('CPU↔DMA 访问重叠且至少一方写（DMA 传输可与 CPU 访问任意交错）')
                destructive_codes.append('D-03')
                witnesses.append(dict(pattern='D-03', domains=sorted(dma_domains),
                                      access_ids=[domain_write_sample.get(d) for d in sorted(dma_domains)
                                                  if domain_write_sample.get(d)]))
        if variable.get('is_bitfield_container') and writer_domains:
            destructive_reasons.append('位域容器跨上下文并发修改（读改写非原子且共享宿主字）')
            destructive_codes.append('D-04')
            witnesses.append(dict(pattern='D-04', domains=sorted(writer_domains),
                                  access_ids=[domain_write_sample.get(d) for d in sorted(writer_domains)
                                              if domain_write_sample.get(d)]))
        if (sid in self.coherent_members and len(domains) >= 2 and writer_domains):
            destructive_reasons.append('多字段一致性：同一 root 的多个关联字段被一个上下文修改、'
                                       '另一上下文成对读取，可能观察到撕裂的字段组合')
            destructive_codes.append('D-07')
            witnesses.append(dict(pattern='D-07', domains=sorted(writer_domains),
                                  access_ids=[domain_write_sample.get(d) for d in sorted(writer_domains)
                                              if domain_write_sample.get(d)]))
        # D-05（OPT-11，FS-1）：union 重叠视图上的写参与冲突（OVERLAP_ACCESS
        # 副本行）时标注 union 模式码。
        if any(a.get('access_scope') == 'OVERLAP_ACCESS'
               and a['access_kind'] in {'WRITE', 'RMW'} for a in runtime):
            destructive_codes.append('D-05')
        if conflicts or destructive_reasons:
            if protection == 'EFFECTIVE':
                return dict(classification='SAFE_PROVEN', safe_code='SAFE_EFFECTIVE_PROTECTION',
                            reason='跨上下文冲突访问的完整窗口已被证明处于有效临界区保护内。',
                            gaps=[], conflicts=conflicts, domains=domains,
                            destructive_codes=sorted(set(destructive_codes)), witnesses=witnesses,
                            unresolved_context_access_count=len(unresolved_context))
            reason_parts = ['、'.join(f'{a} ↔ {b}' for a, b in conflicts[:4])
                            + ('…' if len(conflicts) > 4 else '')] if conflicts else []
            reason = '存在破坏性并发冲突模式（' + '；'.join(
                [p for p in reason_parts if p] + destructive_reasons) + '）；' + (
                '保护有效性待确认。' if protection in {'DETECTED', 'PARTIAL', 'UNRESOLVED'}
                else '尚未发现能排除该冲突的有效保护。')
            return dict(classification='SUSPECT', safe_code=None, reason=reason,
                        gaps=gaps, conflicts=conflicts, domains=domains,
                        destructive=destructive_reasons,
                        destructive_codes=sorted(set(destructive_codes)), witnesses=witnesses,
                        unresolved_context_access_count=len(unresolved_context))

        # 执行上下文未知的写入：在已解析域之间未建立破坏性冲突时，未知写者
        # 本身就是关键缺口（无法证明写者集合完整）=> UNKNOWN。
        if unresolved_writes:
            return dict(classification='UNKNOWN', safe_code=None,
                        reason='；'.join(UNKNOWN_LABELS.get(g['code'], g['code']) for g in gaps),
                        gaps=gaps, conflicts=[], domains=domains,
                        unresolved_context_access_count=len(unresolved_context))

        # 相关缺口优先于一切非 SUSPECT 结论（OPT-10，FS-4；规划 §4.6 顺序）：
        # 单写者门槛通过也不能无视证据切片内的缺口——地址逃逸、别名、缺失
        # TU 等可能隐藏未知的第二个写者。缺口存在 => UNKNOWN，绝不 NO_REVIEW。
        if gaps:
            return dict(classification='UNKNOWN', safe_code=None,
                        reason='；'.join(UNKNOWN_LABELS.get(g['code'], g['code']) for g in gaps),
                        gaps=gaps, conflicts=[], domains=domains,
                        unresolved_context_access_count=len(unresolved_context))

        # --- 单一运行期写者域 + 其余只读 → SHARED_NO_REVIEW 候选 ---
        # 必须存在真实共享（≥2 个物理域）：单域变量由 SAFE 规则直接证明。
        # 例外（OPT-17）：存在未知上下文只读者时，读者物理域不可枚举，
        # 变量按共享处理（原子宽度前提已在缺口检查中保证）。
        if len(writer_domains) == 1 and (len(domains) >= 2 or unresolved_reads):
            writer_domain = writer_domains[0]
            writer_kinds = domain_kinds[writer_domain]
            gate_failures = []
            # 结构化门槛结果（OPT-02，规划 NR-11）：逐项记录 NR 检查，
            # 失败项带稳定码，供根因统计与反事实分析。
            gate_results = [dict(gate='NR-01', result='PASS'),
                            dict(gate='NR-02', result='PASS'),
                            dict(gate='NR-09', result='PASS'),
                            dict(gate='NR-10', result='PASS')]
            # 写者域内允许对同一变量存在独立读取站点：本分支已证明它是唯一
            # 写者域，先读后写不会丢失更新（stale snapshot 需要第二个写者，
            # 守门测试 G3 的双写者模式仍由 MULTI_WRITER 拦截）。RMW 是单
            # 站点事务，同样不受限。
            width = self._element_width(variable)
            if width is None:
                gate_failures.append('无法证明访问宽度为标量（结构体 / 位域 / 未知类型）')
                gate_results.append(dict(gate='NR-03', result='FAIL', code='NR-03_WIDTH_UNKNOWN'))
            elif width > self.word_bytes:
                gate_failures.append(f'访问宽度 {width} 字节超过 {self.word_bytes} 字节单指令原子宽度')
                gate_results.append(dict(gate='NR-03', result='FAIL', code='NR-03_WIDTH_EXCEEDS_WORD',
                                         width=width, word_bytes=self.word_bytes))
            else:
                alignment = self._effective_alignment(variable)
                if alignment is None:
                    gate_failures.append('对齐信息缺失，无法证明单指令原子访问')
                    gate_results.append(dict(gate='NR-03', result='FAIL', code='NR-03_ALIGNMENT_MISSING'))
                elif alignment < width:
                    gate_failures.append(f'对齐 {alignment} 字节小于访问宽度 {width} 字节')
                    gate_results.append(dict(gate='NR-03', result='FAIL', code='NR-03_ALIGNMENT_INSUFFICIENT',
                                             width=width, alignment=alignment))
                else:
                    gate_results.append(dict(gate='NR-03', result='PASS', width=width,
                                             alignment=alignment))
            gate_results.append(dict(gate='NR-06', result='PASS' if not dma_domains else 'FAIL'))
            if gate_failures:
                if any(g['code'] != 'ACCESS_NOT_ANALYZED' for g in gaps):
                    return dict(classification='UNKNOWN', safe_code=None,
                                reason='；'.join(UNKNOWN_LABELS.get(g['code'], g['code']) for g in gaps),
                                gaps=gaps, conflicts=[], domains=domains,
                                destructive_codes=[], witnesses=[],
                                gate_results=gate_results,
                                unresolved_context_access_count=len(unresolved_context))
                return dict(classification='SUSPECT', safe_code=None,
                            reason='单一写者共享变量未通过无复核门槛：' + '；'.join(gate_failures) + '。',
                            gaps=[], conflicts=[], domains=domains,
                            destructive_codes=['D-08'],
                            witnesses=[dict(pattern='D-08', domains=sorted(domains),
                                            access_ids=[domain_write_sample.get(writer_domain)],
                                            failed_gates=[g.get('code') for g in gate_results
                                                          if g.get('result') == 'FAIL'])],
                            gate_results=gate_results,
                            unresolved_context_access_count=len(unresolved_context))
            evidence = dict(writer_domain=writer_domain, writer_kinds=sorted(writer_kinds),
                            reader_domains=sorted(d for d in domains if d != writer_domain),
                            unknown_context_readers=len(unresolved_reads) or None,
                            element_width=width, alignment_bytes=variable.get('alignment_bytes'),
                            effective_alignment_bytes=self._effective_alignment(variable),
                            nr_checks=gate_results + [
                                dict(gate='NR-04', result='NOT_EVALUATED'),
                                dict(gate='NR-05', result='PASS' if sid not in self.coherent_members
                                     else 'FAIL'),
                                dict(gate='NR-07', result='PASS' if not gaps else 'FAIL'),
                                dict(gate='NR-08', result='NOT_EVALUATED')])
            return dict(classification='SHARED_NO_REVIEW', safe_code='SHARED_NO_REVIEW',
                        reason=('唯一写者（' + writer_domain + '）+ 其余上下文只读；访问宽度 '
                                + str(width) + ' 字节、对齐 ' + str(variable.get('alignment_bytes'))
                                + ' 字节满足单指令原子访问；无 DMA、地址逃逸或多字段一致性关联。'),
                        gaps=[], conflicts=[], domains=domains, shared_evidence=evidence,
                        destructive_codes=[], witnesses=[],
                        unresolved_context_access_count=len(unresolved_context))

        if gaps:
            return dict(classification='UNKNOWN', safe_code=None,
                        reason='；'.join(UNKNOWN_LABELS.get(g['code'], g['code']) for g in gaps),
                        gaps=gaps, conflicts=[], domains=domains,
                        unresolved_context_access_count=len(unresolved_context))
        # OPT-16（FS-7）：多个写者域两两不可交错（同抢占优先级）时，旧逻辑
        # 直接返回 SAFE_NON_INTERLEAVING，忽略写者组与可交错读者域之间的
        # 撕裂（P28：两个同优先级 ISR 写 64 位、前台读）。把互相串行的写者
        # 域视为一个"写者组"：组与可交错读者域之间必须满足单拷贝原子门槛
        # （NR-03），全部满足才共享无复核，否则读者可见撕裂值（D-08）。
        if len(writer_domains) >= 2 and len(domains) >= 2:
            interleaving_readers = [d for d in domains
                                    if not domain_kinds[d] & {'WRITE', 'RMW'}
                                    and any(self.domains_may_interleave(d, w) for w in writer_domains)]
            if interleaving_readers:
                width = self._element_width(variable)
                alignment = self._effective_alignment(variable)
                tear_failures = []
                if width is None:
                    tear_failures.append('无法证明访问宽度为标量')
                elif width > self.word_bytes:
                    tear_failures.append(f'访问宽度 {width} 字节超过 {self.word_bytes} 字节单指令原子宽度')
                elif alignment is None:
                    tear_failures.append('对齐信息缺失')
                elif alignment < width:
                    tear_failures.append(f'对齐 {alignment} 字节小于访问宽度 {width} 字节')
                if tear_failures:
                    return dict(classification='SUSPECT', safe_code=None,
                                reason=('多个写者域相互串行，但写者组与可交错的读者域（'
                                        + '、'.join(interleaving_readers) + '）之间访问宽度 '
                                        '不满足单拷贝原子：' + '；'.join(tear_failures) + '。'),
                                gaps=gaps, conflicts=[], domains=domains,
                                destructive_codes=['D-08'],
                                witnesses=[dict(pattern='D-08',
                                                domains=[min(writer_domains), min(interleaving_readers)],
                                                writer_group=sorted(writer_domains),
                                                reader_domains=sorted(interleaving_readers))],
                                unresolved_context_access_count=len(unresolved_context))
                evidence = dict(writer_domains=sorted(writer_domains),
                                reader_domains=sorted(interleaving_readers),
                                element_width=width, alignment_bytes=alignment,
                                writer_group_serial=True)
                return dict(classification='SHARED_NO_REVIEW', safe_code='SHARED_NO_REVIEW',
                            reason=('多个写者域（' + '、'.join(sorted(writer_domains))
                                    + '）已证明相互不可交错，构成单一串行写者组；可交错读者域只读，'
                                    '访问宽度 ' + str(width) + ' 字节满足单拷贝原子。'),
                            gaps=[], conflicts=[], domains=domains, shared_evidence=evidence,
                            destructive_codes=[], witnesses=[],
                            unresolved_context_access_count=len(unresolved_context))

        classification, reason, code = self._safe_rule(variable, runtime, writes,
                                                       domain_kinds, domains, protection)
        return dict(classification=classification, reason=reason, safe_code=code,
                    gaps=[], conflicts=[], domains=domains,
                    destructive_codes=[], witnesses=[],
                    unresolved_context_access_count=len(unresolved_context))

    def _safe_rule(self, variable, runtime, writes, domain_kinds, domains, protection):
        if not runtime:
            return ('SAFE_PROVEN', '无运行期访问（定义/初始化之外未发现 READ/WRITE/RMW）。',
                    'SAFE_NO_RUNTIME_ACCESS')
        if not writes:
            if len(domains) > 1:
                return ('SAFE_PROVEN', '多个物理上下文均只读取该变量，没有写者。',
                        'SAFE_MULTI_CONTEXT_READ_ONLY')
            return 'SAFE_PROVEN', '全部已解析访问均为 READ，且没有地址逃逸或外部写入证据。', 'SAFE_READ_ONLY'
        if len(domains) == 1:
            domain = domains[0]
            if domain == 'FOREGROUND':
                return ('SAFE_PROVEN', '全部访问属于同一前台（main 调度）串行执行域，没有 ISR/DMA/异步访问。',
                        'SAFE_SINGLE_FOREGROUND')
            kinds = {self.contexts[c].get('kind') for c in self.domain if self.domain[c] == domain}
            if kinds == {'ISR'}:
                return ('SAFE_PROVEN', '全部访问属于同一 IRQ 物理上下文；单个 Cortex-M 中断处理内部串行执行。',
                        'SAFE_SINGLE_IRQ')
            return 'SAFE_PROVEN', '全部访问属于同一串行执行域。', 'SAFE_SINGLE_CONTEXT'
        if protection == 'EFFECTIVE':
            return ('SAFE_PROVEN', '跨上下文冲突访问的完整窗口已被证明处于有效临界区保护内。',
                    'SAFE_EFFECTIVE_PROTECTION')
        if self.init_only_write_proof(writes, runtime):
            return ('SAFE_PROVEN', '全部写入只发生在 main 初始化阶段（异步源启用之前），运行期只有读取。',
                    'SAFE_INIT_ONLY_WRITE')
        # 多域 + 写 + 全部域对不可交错（同一抢占优先级等已证明关系）。
        return ('SAFE_PROVEN', '多个执行域均已被证明无法互相抢占 / 重入。', 'SAFE_NON_INTERLEAVING')


def unknown_fanout_report(variables, threshold):
    """UNKNOWN 根因聚类与过度传播检查（诊断目标，不是通过标准）。"""
    counts = Counter()
    for v in variables:
        if v.get('static_classification') == 'UNKNOWN':
            for reason in v.get('unknown_reason') or ['UNKNOWN_GENERAL']:
                counts[reason] += 1
    total = len(variables) or 1
    rows = [dict(reason=reason, variables=count, share=round(100 * count / total, 2),
                 over_propagation_suspected=count > threshold)
            for reason, count in counts.most_common()]
    return rows
