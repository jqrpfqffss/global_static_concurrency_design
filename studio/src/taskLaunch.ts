import { ref } from 'vue'
import { api, ApiError } from './api'

type Profile = { project_id: string, id: string, revision: string }
type Resources = { preset: string, peak_gib?: number, workers?: number }
export const taskCreationPending = ref(false)

export async function createTask(profile: Profile, mode: 'scan' | 'precheck', resources: Resources) {
  if (taskCreationPending.value) throw Error('上一项任务正在提交，请稍候。')
  taskCreationPending.value = true
  try {
    const request_id = crypto.randomUUID().replaceAll('-', '')
    const { project_id, id: profile_id, revision } = profile
    const matches = (task: any) => task?.id && task.request_id === request_id && task.mode === mode &&
      task.project_id === project_id && task.profile_id === profile_id && task.profile_revision === revision
    try {
      const task = await api('/tasks', 'POST', { project_id, profile_id, revision, mode, resources, request_id })
      if (matches(task)) return task
    } catch (error) {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) throw error
    }

    // The request may have reached Studio even when its response did not.
    const records = await api('/tasks').catch(() => null)
    const found = records?.items?.filter(matches)
    if (found?.length === 1) return found[0]
    throw Error(`任务提交结果待确认。请先到扫描任务中心核对，确认后再重试。请求编号 ${request_id}`)
  } finally {
    taskCreationPending.value = false
  }
}
