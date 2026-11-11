<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from './api'
import EvidenceNode from './EvidenceNode.vue'
import WorkspaceDialog from './WorkspaceDialog.vue'

type Diff = {
  node: number
  pin?: {base_ref?: string, base_sha?: string, current_ref?: string, head_sha?: string, include_uncommitted?: boolean}
  file_count?: number
  deleted_variable_count?: number
  selected_symbol_ids_count: number
  conservative_symbol_ids_count: number
  impact_coverage?: string
  fallback_reasons?: string[]
}
type Change = {
  ordinal: number, node: number, status?: string, old_path?: string, new_path?: string,
  comment_only?: boolean, name?: string, symbol_id?: string
}
const props = defineProps<{scan: string, diff: Diff, total: number, compact?: boolean, busy: boolean}>()
const emit = defineEmits<{impacts: []}>()
const open = ref(false), kind = ref<'files' | 'deleted'>('files'), offset = ref(0)
const page = ref<{items: Change[], total: number, next_offset: number | null} | null>(null)
const loading = ref(false), error = ref(''), retry = ref(0)
const pageSize = 25
const direction = computed(() => {
  const {base_ref, base_sha, current_ref, head_sha} = props.diff.pin ?? {}
  const display = (ref?: string, sha?: string) => ref && sha && ref !== sha ? `${ref} (${sha.slice(0, 7)})` : ref || sha || '未记录'
  return `${display(base_ref, base_sha)} → ${display(current_ref, head_sha)}`
})
const counts = computed(() => [
  `变更文件 ${props.diff.file_count ?? '未记录'}`,
  `受影响变量 ${props.diff.selected_symbol_ids_count} / ${props.total}`,
  `已删除变量 ${props.diff.deleted_variable_count ?? '未记录'}`,
  `保守潜在影响 ${props.diff.conservative_symbol_ids_count}`,
].join(' · '))
const changeCount = computed(() => kind.value === 'files' ? props.diff.file_count : props.diff.deleted_variable_count)
const statuses: Record<string, string> = {A: '新增', M: '修改', D: '删除', R: '重命名', C: '复制', T: '类型变更', '?': '未跟踪'}
function choose(value: typeof kind.value) {
  kind.value = value
  offset.value = 0
}
watch([open, kind, offset, retry], async (_, __, onCleanup) => {
  page.value = null
  error.value = ''
  loading.value = false
  if (!open.value || !changeCount.value) return
  let active = true
  onCleanup(() => { active = false })
  loading.value = true
  try {
    const result = await api(`/scans/${encodeURIComponent(props.scan)}/diff-changes?kind=${kind.value}&offset=${offset.value}&limit=${pageSize}`)
    if (active) page.value = result
  } catch (exc) {
    if (active) error.value = (exc as Error).message
  } finally {
    if (active) loading.value = false
  }
})
function showImpacts() {
  open.value = false
  emit('impacts')
}
</script>

<template>
  <div v-if="compact" class="diff-strip">
    <span :title="`${direction} · ${counts}`">Git 差异 · {{ direction }} · {{ counts }}</span>
    <button @click="open=true">查看差异结果</button>
  </div>
  <section v-else class="panel" aria-label="Git 差异扫描">
    <h2>Git 差异扫描</h2>
    <p class="identity">{{ direction }}</p>
    <p>{{ counts }}</p>
    <div class="actions">
      <button @click="open=true">查看差异结果</button>
      <button :disabled="busy" @click="showImpacts">查看受影响变量</button>
    </div>
  </section>
  <WorkspaceDialog v-if="open" title="Git 差异结果" :error="error" @close="open=false">
    <p class="identity" :title="`${diff.pin?.base_sha ?? ''} → ${diff.pin?.head_sha ?? ''}`">{{ direction }}</p>
    <p v-if="diff.pin?.include_uncommitted">当前版本包含扫描时固定的未提交输入。</p>
    <p>{{ counts }}</p>
    <template v-if="diff.fallback_reasons?.length">
      <h3>扩大分析范围的原因</h3>
      <ul><li v-for="reason in diff.fallback_reasons" :key="reason">{{ reason }}</li></ul>
    </template>
    <div class="section-tabs" aria-label="差异明细">
      <button :aria-pressed="kind==='files'" @click="choose('files')">变更文件</button>
      <button :aria-pressed="kind==='deleted'" @click="choose('deleted')">已删除变量</button>
    </div>
    <p v-if="changeCount === undefined">归档未记录此明细。</p>
    <p v-else-if="changeCount === 0">{{ kind === 'files' ? '两个版本之间没有文件变更。' : '当前版本没有删除基准中的变量。' }}</p>
    <p v-if="loading" role="status">正在读取差异明细…</p>
    <button v-if="error" @click="retry++">重试读取</button>
    <template v-if="page">
      <ul v-if="kind==='files'" class="changed-files">
        <li v-for="file in page.items" :key="file.ordinal">
          <strong>{{ statuses[file.status?.[0] ?? ''] || file.status }}</strong>
          <code>{{ file.old_path && file.new_path && file.old_path !== file.new_path ? `${file.old_path} → ${file.new_path}` : file.new_path || file.old_path }}</code>
          <small v-if="file.comment_only">仅注释变化</small>
        </li>
      </ul>
      <template v-else>
        <EvidenceNode v-for="item in page.items" :key="item.ordinal" :scan="scan" :node="item.node" :title="item.name || item.symbol_id || '已删除变量'"/>
      </template>
      <div class="page-controls">
        <button :disabled="offset===0" @click="offset=Math.max(0,offset-pageSize)">上一页</button>
        <span>{{ offset+1 }}–{{ offset+page.items.length }} / {{ page.total }}</span>
        <button :disabled="page.next_offset===null" @click="offset=page.next_offset ?? offset">下一页</button>
      </div>
    </template>
    <EvidenceNode :scan="scan" :node="diff.node" title="完整 Git 差异证据"/>
    <template #footer>
      <span>{{ diff.impact_coverage === 'COMPLETE' ? '影响闭包记录完整' : '存在未排除的潜在影响' }}</span>
      <button :disabled="busy" @click="showImpacts">查看受影响变量</button>
    </template>
  </WorkspaceDialog>
</template>

<style scoped>
.identity,.changed-files code{overflow-wrap:anywhere}
.changed-files{list-style:none;padding:0}
.changed-files li{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 12px;padding:6px 0;border-bottom:1px solid #dce4ee}
.section-tabs button[aria-pressed=true]{background:#eaf1ff;border-color:#426fbe}
</style>
