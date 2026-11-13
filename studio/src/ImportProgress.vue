<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from './api'
import { importJobs, importTransfer, importWake, importActive, cancelImportTransfer } from './importJobs'

defineProps<{ busy: boolean }>()
const emit = defineEmits<{ completed: [result: any], open: [id: string], continue: [id: string] }>()
const error = ref(''), expanded = ref(false), collapsed = ref(false), now = ref(Date.now())
const allJobs = computed(() => {
  const transfer = importTransfer.value
  const uploaded = transfer?.kind === 'full' && !importActive(transfer) && importJobs.value.some(job => job.id === transfer.id)
  return [
    ...(transfer && !uploaded ? [transfer] : []),
    ...importJobs.value.filter(job => uploaded || job.id !== transfer?.id)
  ]
})
const visible = computed(() => expanded.value ? allJobs.value : allJobs.value.some(importActive) ? allJobs.value.filter(importActive) : allJobs.value.slice(0, 1))
const pending = new Set<string>()
let timer: ReturnType<typeof setTimeout> | undefined, clock: ReturnType<typeof setInterval> | undefined, disposed = false, reading = false
function duration(seconds: number) { return `${Math.floor(seconds / 60)} 分 ${Math.floor(seconds % 60)} 秒` }
function elapsed(job: any) { return importActive(job) ? Math.max(job.elapsed_seconds || 0, (now.value - Date.parse(job.started)) / 1000) : job.elapsed_seconds || 0 }
function size(bytes: number) { return bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(2)} GB` : `${(bytes / 1024 ** 2).toFixed(1)} MB` }
function measured(job: any) { return Number.isFinite(job.completed) && job.total > 0 }
function graphMeasured(job: any) { return Number.isFinite(job.graph_completed) && job.graph_total > 0 }
async function poll() {
  if (disposed || reading) return
  clearTimeout(timer); reading = true
  try { importJobs.value = (await api('/import-jobs')).items; error.value = '' }
  catch (e: any) { error.value = '导入进度暂时无法读取：' + e.message + '。可重试查询。' }
  finally { reading = false; if (!disposed) timer = setTimeout(poll, allJobs.value.some(importActive) ? 1000 : 5000) }
}
async function cancel(job: any) {
  try {
    if (job.id === importTransfer.value?.id && importActive(importTransfer.value)) await cancelImportTransfer()
    else await api('/import-jobs/' + job.id + '/cancel', 'POST')
    await poll()
  } catch (e: any) { error.value = e.message }
}
watch(() => allJobs.value.map(job => ({ id: job.id, state: job.state, result: job.result })), jobs => {
  for (const job of jobs) {
    if (importActive(job)) pending.add(job.id)
    else {
      // Losing the upload response does not mean the server stopped. Retain
      // completion tracking until its durable job reports a terminal state.
      // This set does not disable retries; importPending only uses active jobs.
      const localUpload = importTransfer.value?.id === job.id && importTransfer.value.kind === 'full'
      const serverJob = importJobs.value.find(item => item.id === job.id)
      if (localUpload && !serverJob) continue
      if (pending.delete(job.id) && job.state === 'COMPLETE') emit('completed', job.result)
    }
  }
})
watch(() => importTransfer.value?.id, id => { if (id) collapsed.value = false })
watch(importWake, poll)
onMounted(() => { poll(); clock = setInterval(() => { now.value = Date.now() }, 1000) })
onUnmounted(() => { disposed = true; clearTimeout(timer); clearInterval(clock) })
</script>

<template>
  <section v-if="allJobs.length || error" class="panel import-progress" aria-label="导入进度">
    <div class="actions"><strong>导入进度</strong><button v-if="collapsed" @click="collapsed = false">显示导入进度</button><template v-else><button v-if="allJobs.length > 1" @click="expanded = !expanded">{{ expanded ? '收起导入记录' : '查看导入记录' }}</button><button @click="poll">更新进度</button><button @click="collapsed = true">隐藏导入进度</button></template></div>
    <template v-if="!collapsed">
      <p v-if="error" role="alert" class="banner error">{{ error }}</p>
      <article v-for="job in visible" :key="job.id">
        <p class="identity">{{ job.filename || job.scan_id }} · {{ job.kind === 'delta' ? '人工确认增量' : '标准完整包' }}</p>
        <p role="status">{{ importActive(job) ? job.message : job.state === 'COMPLETE' ? '导入完成' : job.error || job.message }} · 已用时 {{ duration(elapsed(job)) }}</p>
        <template v-if="importActive(job)">
          <template v-if="job.stage === 'VERIFY_ALL'">
            <div class="progress-label"><span>证据节点校验进度</span><strong v-if="graphMeasured(job)">{{ Math.min(100, 100 * job.graph_completed / job.graph_total).toFixed(1) }}%</strong><span v-else>处理中…</span></div>
            <progress v-if="graphMeasured(job)" :max="job.graph_total" :value="job.graph_completed" aria-label="证据节点校验进度" />
            <progress v-else aria-label="证据节点校验进度" />
            <p v-if="graphMeasured(job)" class="progress-detail">已校验 {{ job.graph_completed.toLocaleString() }} / {{ job.graph_total.toLocaleString() }} 个证据节点</p>
            <p class="progress-detail"><span v-if="measured(job)">独立检查已完成 {{ job.completed }} / {{ job.total }} 项；</span>全部检查通过后才发布归档。</p>
          </template>
          <template v-else>
          <div class="progress-label"><span>{{ job.stage === 'UPLOAD' || job.state === 'UPLOADING' ? '上传进度' : '当前阶段进度' }}</span><strong v-if="measured(job)">{{ Math.min(100, 100 * job.completed / job.total).toFixed(1) }}%</strong><span v-else>处理中…</span></div>
          <progress v-if="measured(job)" :max="job.total" :value="job.completed" aria-label="导入进度" />
          <progress v-else aria-label="导入进度" />
          <p v-if="job.unit === 'bytes' && measured(job)" class="progress-detail">已处理 {{ size(job.completed) }} / {{ size(job.total) }}</p>
          <p v-else-if="measured(job)" class="progress-detail">已处理 {{ job.completed.toLocaleString() }} / {{ job.total.toLocaleString() }}</p>
          </template>
          <p v-if="job.id === importTransfer?.id">{{ job.kind === 'delta' ? '正在提交人工确认增量，请保持本页打开。' : '上传完成后在后台校验；上传期间请保持本页打开。' }}</p>
          <p v-else>可继续浏览或刷新页面，进度会保留；请保持本地服务运行。</p>
          <button v-if="job.id !== importTransfer?.id || job.kind !== 'delta' || job.state === 'UPLOADING'" :disabled="job.state === 'CANCELLING'" @click="cancel(job)">{{ job.state === 'UPLOADING' ? '取消上传' : '取消导入' }}</button>
        </template>
        <template v-if="job.state === 'COMPLETE'">
          <div class="progress-label"><span>{{ job.result?.integrity_verified ? '完整性已验证' : job.kind === 'delta' ? '人工确认已合并' : '导入完成' }}</span><strong>100%</strong></div>
          <progress :max="100" :value="100" aria-label="导入进度" />
          <p v-if="job.result?.integrity_verified">{{ job.result.repeated ? '结果包数据库字节摘要已核对，完整证据和人工历史已合并保留' : '扫描数据库与结果包字节一致，证据和人工历史已完整保留' }}；可继续人工确认。</p>
          <p>归档 {{ job.result?.scan_id }} · 新增人工事件 {{ job.result?.imported_events || 0 }}{{ job.result?.repeated ? ' · 已合并到现有归档' : '' }}</p>
          <div class="actions"><button :disabled="busy" @click="emit('open', job.result.scan_id)">打开导入归档</button><button :disabled="busy" @click="emit('continue', job.result.scan_id)">继续人工确认</button></div>
        </template>
      </article>
    </template>
  </section>
</template>

<style scoped>
.import-progress { margin-bottom: 12px; }
.import-progress article + article { border-top: 1px solid #ccd4df; margin-top: 12px; padding-top: 8px; }
.import-progress progress { display: block; width: 100%; height: 16px; accent-color: #245bdb; margin: 8px 0; }
.import-progress .progress-label { display: flex; justify-content: space-between; gap: 12px; }
.import-progress .progress-detail { color: #52657e; font-size: 13px; }
.import-progress .identity { overflow-wrap: anywhere; }
</style>
