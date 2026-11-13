import { ref } from 'vue'
import { api } from './api'

export const exportJobs = ref<any[]>([])
export const exportRequestPending = ref(false)
export const exportWake = ref(0)
export const exportAutoDownload = new Set<string>()

export async function startExport(scan: string, kind: string, compression = 'deflate') {
  if (exportRequestPending.value) return
  exportRequestPending.value = true
  try {
    const job = await api('/scans/' + encodeURIComponent(scan) + '/export-jobs', 'POST', { kind, compression })
    exportJobs.value = [job, ...exportJobs.value.filter(item => item.id !== job.id)]
    exportAutoDownload.add(job.id)
    exportWake.value++
    return job
  } finally { exportRequestPending.value = false }
}
