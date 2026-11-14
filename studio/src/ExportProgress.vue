<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, download } from './api'
import { exportJobs, exportWake, exportAutoDownload } from './exportJobs'

const error = ref(''), expanded = ref(false), downloading = ref(''), collapsed = ref(false)
const active = (job: any) => ['RUNNING', 'CANCELLING'].includes(job.state)
const visible = computed(() => expanded.value ? exportJobs.value : exportJobs.value.filter(active).length ? exportJobs.value.filter(active) : exportJobs.value.slice(0, 1))
let timer: ReturnType<typeof setTimeout> | undefined, disposed = false, reading = false
function duration(seconds: number) { return `${Math.floor(seconds / 60)} 分 ${Math.floor(seconds % 60)} 秒` }
function size(bytes: number) { return bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(2)} GB` : `${(bytes / 1024 ** 2).toFixed(1)} MB` }
async function save(job: any) {
  downloading.value = job.id; error.value = ''
  try { await download(job.result.download, job.result.filename) }
  catch (e: any) { error.value = '下载未开始：' + e.message + '；可重试下载已完成的结果包。' }
  finally { downloading.value = '' }
}
async function poll() {
  if (disposed || reading) return
  clearTimeout(timer); reading = true
  try {
    exportJobs.value = (await api('/export-jobs')).items
    error.value = ''
    for (const job of exportJobs.value) {
      if (!active(job) && exportAutoDownload.delete(job.id) && job.state === 'COMPLETE') await save(job)
    }
  } catch (e: any) { error.value = '导出进度暂时无法读取：' + e.message + '。后台任务可能仍在运行，请重试查询。' }
  finally {
    reading = false
    if (!disposed) timer = setTimeout(poll, exportJobs.value.some(active) ? 1000 : 5000)
  }
}
async function cancel(job: any) {
  try { await api('/export-jobs/' + job.id + '/cancel', 'POST'); await poll() }
  catch (e: any) { error.value = e.message }
}
watch(exportWake, () => { collapsed.value = false; poll() })
onMounted(poll)
onUnmounted(() => { disposed = true; clearTimeout(timer) })
</script>

<template>
  <section v-if="exportJobs.length || error" class="panel export-progress" aria-label="导出进度">
    <div class="actions"><strong>导出进度</strong><button v-if="collapsed" @click="collapsed = false">显示导出进度</button><template v-else><button v-if="exportJobs.length > 1" @click="expanded = !expanded">{{ expanded ? '收起导出记录' : '查看导出记录' }}</button><button @click="poll">更新进度</button><button @click="collapsed = true">隐藏导出进度</button></template></div>
    <template v-if="!collapsed">
    <p v-if="error" role="alert" class="banner error">{{ error }}</p>
    <article v-for="job in visible" :key="job.id">
      <p class="identity">{{ job.scan_id }} · {{ job.kind === 'full' ? '标准完整包' : '人工确认增量' }}</p>
      <p role="status">{{ active(job) ? job.message : job.state === 'COMPLETE' ? '导出完成' : job.error || job.message }} · 已用时 {{ duration(job.elapsed_seconds) }}</p>
      <template v-if="active(job)">
        <div class="progress-label"><span>{{ job.stage === 'COMPRESS' ? '打包数据进度' : '当前阶段进度' }}</span><strong v-if="job.total > 0 && job.completed !== null">{{ (100 * job.completed / job.total).toFixed(1) }}%</strong><span v-else>处理中…</span></div>
        <progress v-if="job.total > 0 && job.completed !== null" :max="job.total" :value="job.completed" aria-label="导出进度" />
        <progress v-else aria-label="导出进度" />
        <p v-if="job.unit === 'bytes' && job.total > 0" class="progress-bytes">已处理 {{ size(job.completed) }} / {{ size(job.total) }} 扫描与排查数据 · 全部数据写入并核对后发布结果包</p>
        <p>可继续浏览或刷新页面，进度会保留；请保持本地服务运行。</p>
        <button :disabled="job.state === 'CANCELLING'" @click="cancel(job)">取消导出</button>
      </template>
      <template v-if="job.state === 'COMPLETE'">
        <div class="progress-label"><span>{{ job.kind === 'delta' ? '人工确认增量已就绪' : '完整结果包已就绪' }}</span><strong>100%</strong></div>
        <progress :max="100" :value="100" aria-label="导出进度" />
        <p v-if="job.result.compression_fallback">为保证正常导入，已使用快速压缩。</p>
        <button :disabled="downloading === job.id" @click="save(job)">下载结果包（{{ size(job.result.bytes) }}）</button>
      </template>
    </article>
    </template>
  </section>
</template>

<style scoped>
.export-progress { margin-bottom: 12px; }
.export-progress article + article { border-top: 1px solid #ccd4df; margin-top: 12px; padding-top: 8px; }
.export-progress progress { display: block; width: 100%; height: 16px; accent-color: #245bdb; margin: 8px 0; }
.export-progress .progress-label { display: flex; justify-content: space-between; gap: 12px; }
.export-progress .progress-bytes { color: #52657e; font-size: 13px; }
.export-progress .identity { overflow-wrap: anywhere; }
</style>
