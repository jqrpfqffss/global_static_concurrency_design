import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

// Exercise the actual SFC functions with controlled pending reads. No duplicate
// implementation of the selection or coverage-label logic lives in this test.
function componentFunctions(file, names, values = {}) {
  const source = readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8').split('</script>')[0].replace(/^<script[^>]*>/, '')
  const parsed = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  const snippets = parsed.statements.filter(statement => {
    if (ts.isFunctionDeclaration(statement)) return names.includes(statement.name?.text)
    if (ts.isVariableStatement(statement)) return statement.declarationList.declarations.some(declaration => names.includes(declaration.name.getText(parsed)))
    return false
  }).map(statement => statement.getText(parsed))
  const context = vm.createContext(values)
  vm.runInContext(ts.transpileModule(snippets.join('\n'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText, context)
  return context
}

test('terminal scan tasks do not retain the preflight handoff status', () => {
  const state = componentFunctions('TaskCenter.vue', ['running', 'preflightNotice'])
  const task = { mode: 'scan', preflight: { passed: true }, progress_kind: 'TU_EXTRACTION', published: true }
  for (const terminal of ['COMPLETE', 'FAILED', 'INTERRUPTED']) {
    assert.equal(state.preflightNotice({ ...task, state: terminal }), '')
    assert.equal(state.preflightNotice({ ...task, state: terminal, progress_kind: 'COMPILE_INPUT_PRECHECK' }), '')
  }
  assert.equal(state.preflightNotice({ ...task, state: 'RUNNING' }), '预检查通过，已进入正式扫描。')
  assert.equal(state.preflightNotice({ ...task, state: 'RUNNING', progress_kind: 'COMPILE_INPUT_PRECHECK' }), '预检查通过，正在等待正式扫描初始化。')
  assert.equal(state.preflightNotice({ ...task, state: 'RUNNING', preflight: { passed: false } }), '')
  assert.equal(state.preflightNotice({ ...task, state: 'COMPLETE', mode: 'precheck' }), '')
})

test('scan task titles do not assert a full-scan scope absent from task metadata', () => {
  const state = componentFunctions('TaskCenter.vue', ['states', 'taskModes', 'taskName'])
  assert.equal(state.taskName({ mode: 'scan', state: 'COMPLETE', published: true }), '扫描分析 · 扫描已发布')
  assert.equal(state.taskName({ mode: 'precheck', state: 'COMPLETE' }), '仅预检查 · 检查通过，尚未开始扫描')
})

test('common coverage labels recognize the actual engine states without hiding future values', () => {
  const state = componentFunctions('api.ts', ['labels', 'label'], { exports: {} })
  assert.equal(state.label('INCOMPLETE'), '部分覆盖（INCOMPLETE）')
  assert.equal(state.label('MODELED_SCOPE_COMPLETE'), '已完成建模范围分析')
  assert.equal(state.label('FUTURE_COVERAGE'), '未识别状态：FUTURE_COVERAGE')
})

test('header-static rows expose distinct TU paths without changing canonical identity', () => {
  const state = componentFunctions('App.vue', ['translationUnitHint', 'rowKey'])
  const rows = ['one.c', 'two.c', 'bulk.c', 'main.c', 'subsystems/diagnostics/deep_evidence.c'].map(unit => ({
    name: 'header_state', definition_file: 'shared.h', definition_line: 9,
    symbol_id: `tu::${unit}::c:shared.h@header_state`
  }))
  assert.deepEqual(rows.map(row => state.translationUnitHint(row)), ['one.c', 'two.c', 'bulk.c', 'main.c', 'subsystems/diagnostics/deep_evidence.c'])
  const rowKey = vm.runInContext('rowKey', state)
  assert.equal(new Set(rows.map(row => rowKey(row))).size, 5)
  assert.equal(state.translationUnitHint({ ...rows[0], translation_unit: 'explicit.c' }), 'explicit.c')
  assert.equal(state.translationUnitHint({ ...rows[0], definition_file: './one.c' }), '')
  assert.equal(state.translationUnitHint({ ...rows[0], symbol_id: 'c:@header_state' }), '')
  assert.equal(state.translationUnitHint({ ...rows[0], symbol_id: 'tu::opaque::future-identity' }), '')
  assert.equal(state.translationUnitHint({ ...rows[0], symbol_id: 'local::tu::one.c::c:shared.h@F@fn::value::0' }), 'one.c')
})

test('a failed submitted action reveals and focuses its rendered error without weakening validation', async () => {
  const calls = [], error = { value: '' }, busy = { value: false }, notice = { value: '' }
  const state = componentFunctions('App.vue', ['run', 'revealActionError'], {
    error, busy, notice, nextTick: async () => { calls.push('render') },
    document: { querySelector: () => null },
    errorAlert: { value: { scrollIntoView: options => calls.push(['scroll', options.block]), focus: options => calls.push(['focus', options.preventScroll]) } }
  })
  await state.run(async () => { throw new Error('analysis.command must be a list') })
  assert.equal(error.value, 'analysis.command must be a list')
  assert.equal(busy.value, false)
  assert.deepEqual(calls, ['render', ['scroll', 'nearest'], ['focus', true]])
  calls.length = 0
  assert.equal(await state.run(async () => 'valid'), 'valid')
  assert.equal(error.value, '')
  assert.deepEqual(calls, [])
})

test('an open modal keeps error focus within its existing visible error area', async () => {
  const calls = []
  const state = componentFunctions('App.vue', ['revealActionError'], {
    error: { value: 'rejected' }, nextTick: async () => {}, document: { querySelector: () => ({ open: true }) },
    errorAlert: { value: { scrollIntoView: () => calls.push('scroll'), focus: () => calls.push('focus') } }
  })
  await state.revealActionError()
  assert.deepEqual(calls, [])
})

test('Enter confirms IME input without submitting; ordinary Enter applies the filter', () => {
  let prevented = 0, queried = 0
  const state = componentFunctions('App.vue', ['submitTextFilter'], { filter: () => queried++ })
  state.submitTextFilter({ isComposing: true, preventDefault: () => prevented++ })
  assert.equal(prevented, 0)
  assert.equal(queried, 0)
  state.submitTextFilter({ isComposing: false, preventDefault: () => prevented++ })
  assert.equal(prevented, 1)
  assert.equal(queried, 1)
})

test('known DMA and external-implementation gaps have accurate guidance; unknown kinds remain explicit', () => {
  const coverage = componentFunctions('CoverageCenter.vue', ['descriptions', 'kindTitle', 'hint'])
  assert.match(coverage.kindTitle('DMA_SHARED_REVIEW'), /DMA.*待复核/)
  assert.match(coverage.hint('DMA_SHARED_REVIEW'), /生命周期.*缓存一致性.*所有权/)
  assert.match(coverage.hint('DMA_SHARED_REVIEW'), /不单独证明/)
  assert.equal(coverage.kindTitle('EXTERNAL_CALLEE'), '被调用函数缺少可分析的实现')
  assert.match(coverage.hint('EXTERNAL_CALLEE'), /不能解释为无访问或安全/)
  assert.equal(coverage.kindTitle('FUTURE_GAP'), '未识别缺口类型：FUTURE_GAP')
})

for (const [answers, chosenTab] of [[0, 'relations'], [1, 'source']]) {
  test(`pending evidence reads preserve the user's ${chosenTab} tab selection`, async () => {
    let complete
    const pending = new Promise(resolve => { complete = resolve })
    const values = {
      requireScanReady() {}, selectionGeneration: 0, scan: { value: 'scan-a' },
      evidenceScan: () => 'scan-a', detailScan: { value: 'scan-a' }, editing: null,
      drafts: { get: () => undefined }, headsKey: () => '[]', api: () => pending,
      rememberList: async () => {}, rememberSelectionPosition: () => {}
    }
    for (const name of ['selected', 'human', 'comment', 'handling', 'draftWarning', 'staticFields', 'accesses', 'findings', 'sourceRef', 'sourceLocation']) values[name] = { value: null }
    values.detailTab = { value: 'history' }
    const state = componentFunctions('App.vue', ['rowKey', 'loadSelection'], values)
    const loading = state.loadSelection({ symbol_id: 'a.c::state', node: 123, definition_file: 'a.c', definition_line: 3, ai_answer_count: answers })
    assert.equal(state.detailTab.value, answers ? 'ai' : 'access')
    state.detailTab.value = chosenTab // The real tab click writes this ref.
    complete({ items: [], heads: [], fingerprint: 'f', handling_status: 'TODO' })
    await loading
    assert.equal(state.detailTab.value, chosenTab)
    assert.equal(state.human.value.fingerprint, 'f')
  })
}

test('re-reading the same canonical object keeps the chosen tab and source location', async () => {
  const item = { symbol_id: 'a.c::state', node: 123, definition_file: 'a.c', definition_line: 3 }
  const values = {
    requireScanReady() {}, selectionGeneration: 0, scan: { value: 'scan-a' },
    evidenceScan: () => 'scan-a', detailScan: { value: 'scan-a' }, editing: null,
    drafts: { get: () => undefined }, headsKey: () => '[]',
    api: async () => ({ items: [], heads: [], fingerprint: 'f', handling_status: 'TODO' }),
    rememberList: async () => {}, rememberSelectionPosition: () => {}
  }
  for (const name of ['human', 'comment', 'handling', 'draftWarning', 'staticFields', 'accesses', 'findings', 'sourceRef']) values[name] = { value: null }
  values.selected = { value: item }
  values.sourceLocation = { value: { file: 'caller.c', line: 78 } }
  values.detailTab = { value: 'source' }
  const state = componentFunctions('App.vue', ['rowKey', 'loadSelection'], values)
  await state.loadSelection({ ...item, ai_answer_count: 1 })
  assert.equal(state.detailTab.value, 'source')
  assert.equal(state.sourceLocation.value.file, 'caller.c')
  assert.equal(state.sourceLocation.value.line, 78)
  await state.loadSelection({ ...item, symbol_id: 'b.c::state', ai_answer_count: 1 })
  assert.equal(state.detailTab.value, 'ai')
})

function navigationState(all, position) {
  const row = item => `${item.evidence_side || 'current'}:${item.symbol_id}`
  const values = {
    scan: { value: 'scan-a' }, offset: { value: Math.floor(position / 50) * 50 }, total: { value: all.length },
    items: { value: [] }, selected: { value: all[position] }, selectionAnchor: { value: null },
    search: { value: '' }, classification: { value: '' }, humanFilter: { value: '' }, extra: { value: { diff: '' } },
    listScope: () => 'pending', run: async task => task()
  }
  values.items.value = all.slice(values.offset.value, values.offset.value + 50)
  values.selectedIndex = { get value() { return values.items.value.findIndex(item => row(item) === row(values.selected.value)) } }
  values.loadList = async () => { values.items.value = all.slice(values.offset.value, values.offset.value + 50) }
  values.loadSelection = async item => { values.selected.value = item }
  return componentFunctions('App.vue', ['rowKey', 'listIdentity', 'rememberSelectionPosition', 'navigationTarget', 'adjacent'], values)
}

for (const position of [0, 49, 50, 52, 99, 149]) {
  test(`removed pending item at ${position} continues with its successor across page boundaries`, async () => {
    const all = Array.from({ length: 150 }, (_, i) => ({ name: 'same-name', symbol_id: `file-${i}.c::state` }))
    const state = navigationState(all, position)
    state.rememberSelectionPosition(state.selected.value)
    const before = all[position - 1], after = all[position + 1]
    all.splice(position, 1)
    state.total.value = all.length
    await state.loadList()
    assert.equal(state.navigationTarget(-1), before ? position - 1 : null)
    assert.equal(state.navigationTarget(1), after ? position : null)
    await state.adjacent(after ? 1 : -1)
    assert.equal(state.selected.value.symbol_id, (after || before).symbol_id)
  })
}

test('a removed-object anchor cannot leak into a different scan or filter query', async () => {
  const all = Array.from({ length: 80 }, (_, i) => ({ symbol_id: `file-${i}.c::state` }))
  const state = navigationState(all, 52)
  state.rememberSelectionPosition(state.selected.value)
  all.splice(52, 1); state.total.value = all.length; await state.loadList()
  assert.equal(state.navigationTarget(1), 52)
  state.search.value = 'changed-query'
  assert.equal(state.navigationTarget(1), 50)
  state.search.value = ''; state.scan.value = 'scan-b'
  assert.equal(state.navigationTarget(1), 50)
})

for (const remaining of [100, 0]) {
  test(`removing the last item on a page clamps the page for ${remaining} remaining rows`, async () => {
    const all = Array.from({ length: 101 }, (_, i) => ({ symbol_id: `file-${i}.c::state` }))
    const state = navigationState(all, 100)
    state.rememberSelectionPosition(state.selected.value)
    const offsets = []
    const values = {
      requireScanReady() {}, summary: { value: { diff: false } }, listRequest: 0, loading: { value: false },
      scan: state.scan, selected: state.selected, offset: state.offset, items: state.items, total: state.total,
      extra: state.extra, search: state.search, classification: state.classification, humanFilter: state.humanFilter,
      apiScan: { value: '/scans/scan-a' }, listScope: () => 'pending', URLSearchParams,
      rememberSelectionPosition: state.rememberSelectionPosition,
      api: async url => {
        const offset = Number(new URL(`http://test${url}`).searchParams.get('offset'))
        offsets.push(offset)
        return { total: remaining, items: all.slice(0, remaining).slice(offset, offset + 50) }
      }
    }
    const reader = componentFunctions('App.vue', ['loadList'], values)
    await reader.loadList()
    assert.deepEqual(offsets, [100, remaining ? 50 : 0])
    assert.equal(state.offset.value, remaining ? 50 : 0)
    assert.equal(state.navigationTarget(1), null)
    assert.equal(state.navigationTarget(-1), remaining ? 99 : null)
  })
}
