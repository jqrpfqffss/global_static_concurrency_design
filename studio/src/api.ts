const fragment = new URLSearchParams(location.hash.slice(1))
if (fragment.get('session')) {
  sessionStorage.setItem('ecra-session', fragment.get('session')!)
  history.replaceState(null, '', location.pathname + location.search)
}
export async function api(path: string, method = 'GET', data?: unknown): Promise<any> {
  const response = await fetch('/api' + path, {
    method, headers: { 'X-ECRA-Session': sessionStorage.getItem('ecra-session') || '', 'Content-Type': 'application/json' },
    body: data === undefined ? undefined : JSON.stringify(data)
  })
  const result = await response.json()
  if (!response.ok) throw new Error(result.error || `请求失败 (${response.status})`)
  return result
}
export async function upload(path: string, file: File): Promise<any> {
  const response = await fetch('/api' + path, { method: 'POST', headers: { 'X-ECRA-Session': sessionStorage.getItem('ecra-session') || '' }, body: file })
  const result = await response.json()
  if (!response.ok) throw new Error(result.error || '导入未完成')
  return result
}
export async function download(path: string, filename: string) {
  const response = await fetch(path, { headers: { 'X-ECRA-Session': sessionStorage.getItem('ecra-session') || '' } })
  if (!response.ok) throw new Error('读取导出包失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click()
  URL.revokeObjectURL(url)
}
const labels: Record<string, string> = {
  SUSPECT: '静态疑似', UNKNOWN: '无法判断', SAFE_PROVEN: '本构建已证明安全', SHARED_NO_REVIEW: '共享但无需复核',
  CONTAINER: '容器汇总', NON_STORAGE: '非存储对象', OUT_OF_BUILD: '未进入本构建',
  PENDING: '待确认', CONFIRMED_RISK: '人工确认有风险', CONFIRMED_SAFE: '人工确认无风险',
  NEED_MORE_EVIDENCE: '暂无法确认', RECHECK_REQUIRED: '需重新确认', CONFLICT: '离线确认冲突',
  TODO: '待修复', FIXING: '修复中', TO_VERIFY: '待验证', CLOSED: '已关闭', ACCEPTED_RISK: '接受风险',
  UNVERIFIED: '来源尚未验证', LEGACY_READ_ONLY: '旧格式只读', STATIC_VALIDATED: '发布者记录：静态已校验',
  DONE: '复核完成（结论独立）', TECH_FAILED:'复核技术失败', NEED_MORE_CONTEXT:'复核缺少条件', NOT_QUEUED:'未列入复核', COMPLETE:'覆盖记录完整',
  READ: '读取', WRITE: '写入', RMW: '读改写', PARSED: '解析成功', PARTIAL: '部分覆盖', FAILED: '失败'
}
export function label(value: string) { return labels[value] || `未识别状态：${value}` }
const fields: Record<string, string> = {
  uncertainties:'待核实条件', configured_preemption:'配置中的抢占关系', configured_concurrency:'配置中的并发关系',
  qualified_name: '变量全名', symbol_id: '规范存储身份', static_classification: '静态分类', definition_file: '定义文件',
  definition_line: '定义行', readers: '读取上下文', writers: '写入上下文', read_accesses: '全部读取访问',
  write_accesses: '全部写入访问', accesses: '全部访问', function_id: '函数身份', caller: '调用者', callee: '被调用者',
  access_kind: '访问方式', file: '源文件', line: '行号', access_id: '访问身份', expression: '表达式',
  context: '执行上下文', contexts: '全部执行上下文', reason: '判定依据', summary: '摘要', unknowns: '未知事实',
  protections: '保护窗口', protection: '保护依据', initialization: '初始化依据', analysis_coverage: '覆盖状态',
  findings: '静态发现', variables: '完整对象清单', calls: '完整调用边', functions: '完整函数',
  translation_units: '编译单元', coverage: '覆盖与诊断', context_call_graph: '上下文完整调用图',
  pointer_solution: '指针不动点解', blocking_evidence: '阻断证明的证据', conflict_pairs: '潜在冲突关系',
  variable_evidence_slice: '变量完整相关证据', nvic: 'NVIC配置与证据', source: '源码/来源'
  , declarations: '全部声明位置', definitions: '全部定义位置', definition_extent: '定义源码范围',
  concurrency_hints: '并发线索', shared_no_review_rejections: '未通过共享筛除的理由', unknown_reason_codes: '未知原因代码',
  coverage_reasons: '覆盖状态的依据', screening_blockers: '安全筛除的阻断条件', annotations: '证据注解',
  protection_details: '完整保护窗口', concurrency_relations: '执行域的并发关系', multi_field_coherence: '多字段一致性',
  unknown_reason: '无法判断的具体原因', required_context: '需要补齐的条件', call_graph_slice: '完整相关调用子图',
  build_closure:'真实构建闭包',excluded_sources:'分析范围排除的源文件',excluded_from_build:'未进入当前构建的源文件',
  unlisted_sources:'未列入清单的源文件',unlisted_headers:'未列入清单的头文件',excluded_headers_from_build:'未进入构建的头文件',
  assembly_sources:'汇编源文件',cmake_steps:'CMake实际步骤',cmake_cache:'CMake构建缓存',compilers:'编译器来源',
  external_tools:'外部工具来源',consumed_inputs:'实际消费的输入',file_coverage:'文件覆盖记录',unknown_reason_distribution:'原始未知原因分布',
  source_file:'编译单元源文件',directory:'编译工作目录',original_arguments:'原始真实编译命令',arguments:'实际解析参数',
  removed_arguments:'解析适配移除的参数',response_files:'编译响应文件',inferred_target:'推导的编译目标',missing_defines:'缺失的宏定义',
  tu_id:'编译单元身份',system_include_dirs:'系统头文件路径',audit_role:'编译单元用途',parse_status:'原始解析状态',
  diagnostics:'原始解析诊断',diagnostic:'原始诊断',includes:'实际包含的头文件',semantic_macros_digest:'语义宏摘要',
  dynamic_predefined_inputs:'动态预定义宏输入',relevance_proofs:'全部对象关联证明',symbol_ids:'归档关联对象身份'
}
export function field(value: string) { return fields[value] || '技术字段：'+value }
