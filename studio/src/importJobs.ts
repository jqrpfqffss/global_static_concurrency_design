import { computed, ref } from 'vue'
import { api, upload } from './api'

export const importJobs = ref<any[]>([])
export const importTransfer = ref<any>(null)
export const importWake = ref(0)
export const importActive = (job: any) => ['UPLOADING', 'RUNNING', 'CANCELLING'].includes(job.state)
export const importPending = computed(() => !!importTransfer.value && importActive(importTransfer.value) || importJobs.value.some(importActive))
let controller: AbortController | undefined

export async function startImport(file: File, deltaScan?: string) {
  if (importPending.value) return
  const started = Date.now(), id = crypto.randomUUID().replaceAll('-', '')
  const transfer = { id, filename: file.name, kind: deltaScan ? 'delta' : 'full', scan_id: deltaScan || '',
    started: new Date(started).toISOString(), state: 'UPLOADING', stage: 'UPLOAD', message: '正在上传结果包',
    completed: 0, total: file.size, unit: 'bytes', elapsed_seconds: 0, result: null, error: '' }
  importTransfer.value = transfer
  importWake.value++
  controller = new AbortController()
  try {
    const result = await upload(deltaScan ? '/scans/' + encodeURIComponent(deltaScan) + '/delta/import' : '/import-jobs', file, {
      id: deltaScan ? undefined : id, signal: controller.signal,
      onProgress(completed, total) { Object.assign(importTransfer.value, { completed, total, elapsed_seconds: (Date.now() - started) / 1000 }) },
      onUploaded() { Object.assign(importTransfer.value, { state: 'RUNNING', stage: deltaScan ? 'REVIEWS' : 'PREPARING',
        message: deltaScan ? '上传完成，正在校验并合并人工确认历史' : '上传完成，正在创建后台导入任务', completed: null, total: null }) }
    })
    if (deltaScan) {
      Object.assign(importTransfer.value, { state: 'COMPLETE', message: '人工确认增量已导入', result, elapsed_seconds: (Date.now() - started) / 1000 })
    } else {
      importJobs.value = [result, ...importJobs.value.filter(item => item.id !== result.id)]
      importTransfer.value = null
    }
  } catch (error: any) {
    Object.assign(importTransfer.value, { state: error.name === 'AbortError' ? 'CANCELLED' : 'FAILED',
      error: error.name === 'AbortError' ? '已取消上传' : '导入未完成：' + error.message,
      elapsed_seconds: (Date.now() - started) / 1000 })
  } finally { controller = undefined; importWake.value++ }
}

export async function cancelImportTransfer() {
  const transfer = importTransfer.value, activeController = controller
  if (!transfer || !activeController) return
  if (transfer.kind === 'full') {
    // The backend owns the same ID before receiving the body; cancelling it
    // also covers the brief transition between upload and the worker response.
    try { await api('/import-jobs/' + transfer.id + '/cancel', 'POST') }
    catch (error: any) { if (error.status !== 404 && error.status !== 400) throw error }
    finally { activeController.abort() }
  } else {
    activeController.abort()
  }
}
