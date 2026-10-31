<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from './api'
const history = ref<any[]>([]), job = ref<any>(null), plan = ref<any>(null)
const error = ref(''), confirmed = ref(false), busy = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
const names: Record<string,string> = {PREVIEW:'预览完成，尚未移动文件',MOVING:'隔离中，可恢复',QUARANTINED:'已隔离，可以恢复或永久释放',RESTORED:'已恢复',RESTORE_CONFLICT:'恢复存在路径冲突，保留暂存',PURGING:'释放中，可重试',PURGED:'释放结束',RUNNING:'正在校验与执行',COMPLETE:'操作结束',FAILED:'操作失败',preview:'生成预览',quarantine:'隔离暂存',restore:'恢复文件',purge:'永久释放',SOURCE:'原路径',QUARANTINE:'可恢复暂存',PROTECTED:'出现引用，已保护',UNREFERENCED_OBJECT:'未被引用的证据对象',TU_CACHE:'可重建 TU 缓存'}
names.INTERRUPTED='上次整理中断，可检查计划恢复'
const title = (s:string) => names[s] || s
const size = (n:number) => (n/1024/1024/1024).toFixed(3)+' GiB'
async function refresh() { history.value=(await api('/storage/cleanup/jobs')).items }
async function open(id:string,offset=0) { plan.value=await api('/storage/cleanup/previews/'+id+'?offset='+offset);confirmed.value=false }
async function poll() {
  try {
    if (!job.value) return
    job.value=await api('/storage/cleanup/jobs/'+job.value.id)
    if(job.value.state==='RUNNING') timer=setTimeout(poll,1000)
    else { busy.value=false; await refresh(); if(job.value.preview_id) await open(job.value.preview_id); if(job.value.error) error.value=job.value.error }
  } catch(e:any) { error.value=e.message;busy.value=false }
}
async function start(operation:string) {
  error.value='';busy.value=true
  try { job.value=await api('/storage/cleanup','POST',{operation,preview_id:plan.value?.id,confirmed:confirmed.value}); confirmed.value=false; await poll() }
  catch(e:any) { error.value=e.message;busy.value=false }
}
async function view(item:any) { error.value='';try { if(item.state==='RUNNING') {job.value=item;busy.value=true;await poll()} else if(item.preview_id) await open(item.preview_id); if(item.error) error.value=item.error } catch(e:any){error.value=e.message} }
onMounted(async()=>{try{await refresh()}catch(e:any){error.value=e.message}})
onUnmounted(()=>clearTimeout(timer))
</script>
<template>
  <section class="panel cleanup-center" aria-label="安全空间整理">
    <div class="page-heading"><div><h2>安全空间整理</h2><p>检查所有扫描、AI、人工记录与审计引用。有效历史、原固件、构建目录和导出包不在回收范围。</p></div><button :disabled="busy" @click="start('preview')">生成回收预览</button></div>
    <div v-if="error" class="banner error" role="alert">{{ error }}。文件与日志保留；核对后重新预览或恢复。</div>
    <p v-if="busy" role="status">正在校验完整引用和内容哈希，剩余量未知。大文件需要等待；此时不能执行其他整理操作。</p>
    <template v-if="plan">
      <h3>{{ title(plan.state) }}</h3><p>本计划 {{ plan.files }} 个候选 · {{ size(plan.logical_bytes) }} 逻辑字节</p><p class="muted">{{ plan.reason }}</p>
      <p v-for="group in plan.groups" :key="group.category+group.state">{{title(group.category)}} · {{title(group.state)}}：{{group.files}} 个 / {{size(group.logical_bytes)}}</p>
      <div class="cleanup-files"><article v-for="item in plan.items" :key="item.ordinal"><strong>{{title(item.category)}} · {{title(item.state)}} · {{size(item.size)}}</strong><p class="identity">数据根内路径：{{item.relative}}</p><p class="identity">SHA-256：{{item.sha256}}</p></article></div>
      <div class="page-controls"><button :disabled="busy || plan.offset===0" @click="open(plan.id,Math.max(0,plan.offset-50))">上一页候选</button><span>{{ plan.files ? plan.offset+1 : 0 }}–{{ Math.min(plan.offset+plan.items.length,plan.files) }} / {{ plan.files }}</span><button :disabled="busy || plan.next_offset===null" @click="open(plan.id,plan.next_offset)">下一页候选</button></div>
      <label v-if="['PREVIEW','QUARANTINED','PURGING'].includes(plan.state)" class="cleanup-confirm"><input type="checkbox" v-model="confirmed" :disabled="busy">我已核对全部候选路径与范围，确认执行本次{{plan.state==='PREVIEW'?'隔离（可恢复）':'永久释放（释放后不能恢复）'}}。</label>
      <div class="actions"><button v-if="plan.state==='PREVIEW'" :disabled="busy || !confirmed || plan.files===0" @click="start('quarantine')">确认隔离暂存</button><button v-if="['MOVING','QUARANTINED','RESTORE_CONFLICT'].includes(plan.state)" :disabled="busy" @click="start('restore')">恢复原路径</button><button v-if="['QUARANTINED','PURGING'].includes(plan.state)" :disabled="busy || !confirmed" @click="start('purge')">确认永久释放</button></div>
    </template>
    <details><summary>整理历史与故障恢复</summary><button :disabled="busy" @click="refresh">刷新整理历史</button><article v-for="item in history" :key="item.id" class="history-row"><div><strong>{{title(item.operation)}} · {{title(item.state)}}</strong><p>{{item.started}} · {{item.error}}</p></div><button :disabled="busy" @click="view(item)">查看计划与恢复</button></article><p v-if="!history.length">尚无整理记录。</p></details>
  </section>
</template>
