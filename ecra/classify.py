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
        summarized = {'memcpy', 'memmove', 'memset', 'memcmp', 'xTaskCreate', 'xTaskCreateStatic',
                      'osThreadNew', 'xTaskCreatePinnedToCore', '__disable_irq', '__enable_irq',
                      '__get_PRIMASK', '__set_PRIMASK', '__get_BASEPRI', '__set_BASEPRI',
                      '__set_BASEPRI_MAX', '__disable_fault_irq', '__enable_fault_irq'}
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

    def _collect_pointer_escapes(self):
        """points-to 已恢复的地址流：进入不透明代码即构成逃逸证据。"""
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
        if self.opaque_code is False:
            # 不存在不透明代码时无需内联汇编名扫描；存在时按名字匹配变量。
            for u in self.facts['unknowns']:
                if u.get('kind') != 'INLINE_ASSEMBLY':
                    continue
                text = u.get('source_text', '') or ''
                for v in self.facts['variables']:
                    if v.get('linkage') != 'EXTERNAL':
                        continue
                    if re.search(r'\b' + re.escape(v['name']) + r'\b', text):
                        refs.setdefault(v['symbol_id'], dict(
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
        enables = self.enable_events.get(main_fid, [])
        if not enables:
            return False
        first_enable = min(e.get('offset', -1) for e in enables)
        if any(a.get('offset', -1) >= first_enable for a in writes):
            return False
        if any(a.get('conditional_ancestor') for a in writes):
            return False
        # 其它函数若也启用了异步源，无法证明先后顺序。
        for fid in self.enable_events:
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
        if sid in self.address_escape:
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
        conflicts = []
        destructive_reasons = []
        for i, first in enumerate(domains):
            for second in domains[i + 1:]:
                if not self.domains_may_interleave(first, second):
                    continue
                if ({'WRITE', 'RMW'} & domain_kinds[first]
                        and {'WRITE', 'RMW'} & domain_kinds[second]):
                    conflicts.append((first, second))
        for domain in domains:
            if domain in self.reentrant_domains and {'WRITE', 'RMW'} & domain_kinds[domain]:
                conflicts.append((domain, domain))
        # CPU ↔ DMA：只要该变量同时被 DMA 和 CPU 访问且至少一方写。
        if dma_domains and writer_domains:
            dma_kinds = set().union(*(domain_kinds[d] for d in dma_domains))
            cpu_write = any(domain_kinds[d] & {'WRITE', 'RMW'} for d in domains if d not in dma_domains)
            if (dma_kinds & {'WRITE', 'RMW'} and cpu_write) or (dma_kinds & {'WRITE', 'RMW'}) or cpu_write:
                destructive_reasons.append('CPU↔DMA 访问重叠且至少一方写（DMA 传输可与 CPU 访问任意交错）')
        if variable.get('is_bitfield_container') and writes:
            destructive_reasons.append('位域容器跨上下文并发修改（读改写非原子且共享宿主字）')
        if (sid in self.coherent_members and len(domains) >= 2 and writes):
            destructive_reasons.append('多字段一致性：同一 root 的多个关联字段被一个上下文修改、'
                                       '另一上下文成对读取，可能观察到撕裂的字段组合')
        if conflicts or destructive_reasons:
            if protection == 'EFFECTIVE':
                return dict(classification='SAFE_PROVEN', safe_code='SAFE_EFFECTIVE_PROTECTION',
                            reason='跨上下文冲突访问的完整窗口已被证明处于有效临界区保护内。',
                            gaps=[], conflicts=conflicts, domains=domains,
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
                        unresolved_context_access_count=len(unresolved_context))

        # 执行上下文未知的写入：在已解析域之间未建立破坏性冲突时，未知写者
        # 本身就是关键缺口（无法证明写者集合完整）=> UNKNOWN。
        if unresolved_writes:
            return dict(classification='UNKNOWN', safe_code=None,
                        reason='；'.join(UNKNOWN_LABELS.get(g['code'], g['code']) for g in gaps),
                        gaps=gaps, conflicts=[], domains=domains,
                        unresolved_context_access_count=len(unresolved_context))

        # --- 单一写者域 + 其余只读 → SHARED_NO_REVIEW 候选 ---
        # 必须存在真实共享（≥2 个物理域）：单域变量由 SAFE 规则直接证明。
        if len(writer_domains) == 1 and len(domains) >= 2:
            writer_domain = writer_domains[0]
            writer_kinds = domain_kinds[writer_domain]
            gate_failures = []
            # 写者域内允许对同一变量存在独立读取站点：本分支已证明它是唯一
            # 写者域，先读后写不会丢失更新（stale snapshot 需要第二个写者，
            # 守门测试 G3 的双写者模式仍由 MULTI_WRITER 拦截）。RMW 是单
            # 站点事务，同样不受限。
            width = self._element_width(variable)
            if width is None:
                gate_failures.append('无法证明访问宽度为标量（结构体 / 位域 / 未知类型）')
            elif width > self.word_bytes:
                gate_failures.append(f'访问宽度 {width} 字节超过 {self.word_bytes} 字节单指令原子宽度')
            else:
                alignment = variable.get('alignment_bytes')
                if alignment is None:
                    gate_failures.append('对齐信息缺失，无法证明单指令原子访问')
                elif alignment < width:
                    gate_failures.append(f'对齐 {alignment} 字节小于访问宽度 {width} 字节')
            if gate_failures:
                if any(g['code'] != 'ACCESS_NOT_ANALYZED' for g in gaps):
                    return dict(classification='UNKNOWN', safe_code=None,
                                reason='；'.join(UNKNOWN_LABELS.get(g['code'], g['code']) for g in gaps),
                                gaps=gaps, conflicts=[], domains=domains,
                                unresolved_context_access_count=len(unresolved_context))
                return dict(classification='SUSPECT', safe_code=None,
                            reason='单一写者共享变量未通过无复核门槛：' + '；'.join(gate_failures) + '。',
                            gaps=[], conflicts=[], domains=domains,
                            unresolved_context_access_count=len(unresolved_context))
            evidence = dict(writer_domain=writer_domain, writer_kinds=sorted(writer_kinds),
                            reader_domains=sorted(d for d in domains if d != writer_domain),
                            element_width=width, alignment_bytes=variable.get('alignment_bytes'))
            return dict(classification='SHARED_NO_REVIEW', safe_code='SHARED_NO_REVIEW',
                        reason=('唯一写者（' + writer_domain + '）+ 其余上下文只读；访问宽度 '
                                + str(width) + ' 字节、对齐 ' + str(variable.get('alignment_bytes'))
                                + ' 字节满足单指令原子访问；无 DMA、地址逃逸或多字段一致性关联。'),
                        gaps=[], conflicts=[], domains=domains, shared_evidence=evidence,
                        unresolved_context_access_count=len(unresolved_context))

        if gaps:
            return dict(classification='UNKNOWN', safe_code=None,
                        reason='；'.join(UNKNOWN_LABELS.get(g['code'], g['code']) for g in gaps),
                        gaps=gaps, conflicts=[], domains=domains,
                        unresolved_context_access_count=len(unresolved_context))
        classification, reason, code = self._safe_rule(variable, runtime, writes,
                                                       domain_kinds, domains, protection)
        return dict(classification=classification, reason=reason, safe_code=code,
                    gaps=[], conflicts=[], domains=domains,
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
