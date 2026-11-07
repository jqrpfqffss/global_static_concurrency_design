<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import WorkspaceDialog from './WorkspaceDialog.vue'
import { api } from './api'
import BuildPreflight from './BuildPreflight.vue'
const emit=defineEmits<{open:[scanId:string],focus:[taskId:string]}>()
const resourcesOpen=ref(false)
const props=defineProps<{focusTask?:string}>()
const profiles=ref<any[]>([]), tasks=ref<any[]>([]), selected=ref(''), profile=ref(''), detail=ref<any>(null)
const resourcePreset=ref('auto'),peakGib=ref(16),workers=ref(4)
const error=ref(''), pollError=ref(''), notice=ref(''), busy=ref(false), logOffset=ref(0), search=ref('')
const names:Record<string,string>={RUNNING:'正在扫描',STOP_REQUESTED:'停止请求已发送',COMPLETE:'扫描已发布',FAILED:'扫描失败',INTERRUPTED:'已停止 / 上次中断'}
function taskName(task:any){if(task.mode==='multicore')return ({RUNNING:'正在多核派生合并',STOP_REQUESTED:'合并停止请求已发送',COMPLETE:'派生结果已发布',FAILED:'多核合并失败',INTERRUPTED:'合并已停止 / 上次中断'} as Record<string,string>)[task.state]||task.state;if(task.mode==='precheck')return ({RUNNING:'正在检查真实构建',STOP_REQUESTED:'检查停止请求已发送',COMPLETE:'编译输入检查通过',FAILED:'真实构建检查失败',INTERRUPTED:'检查已停止'} as Record<string,string>)[task.state]||task.state;if(task.mode&&task.mode!=='scan')return ({RUNNING:'正在复核',COMPLETE:'复核执行已结束',FAILED:'复核执行失败'} as Record<string,string>)[task.state]||names[task.state]||task.state;return names[task.state]||task.state}
const active=computed(()=>tasks.value.some(x=>['RUNNING','STOP_REQUESTED'].includes(x.state)))
const currentProfile=computed(()=>profiles.value.find(x=>x.id===profile.value))
const chartMax=computed(()=>Math.max(1,...(detail.value?.samples||[]).map((s:any)=>s.working_set_bytes||0)))
const lines=computed(()=>(detail.value?.log?.text||'').split('\n').filter((x:string)=>!search.value||x.includes(search.value)))
const size=(bytes:number|undefined)=>bytes===undefined?'尚未采样':`${(bytes/1024/1024).toFixed(1)} MiB`
const reviewTask=computed(()=>['review','review-failed'].includes(detail.value?.mode))
const counterName=computed(()=>({WORKING_INPUT_INVENTORY:'编译输入盘点',COMPILE_INPUT_PRECHECK:'编译输入检查',AI_REVIEW:'复核项目已处理（含技术失败）'} as Record<string,string>)[detail.value?.progress_kind]||'TU 解析完成')
let timer:ReturnType<typeof setInterval>|undefined, polling=false
async function poll(){
  if(polling)return
  polling=true
  try{
    tasks.value=(await api('/tasks')).items
    if(!selected.value&&tasks.value.length)selected.value=tasks.value[0].id
    if(selected.value)detail.value=await api(`/tasks/${selected.value}?offset=${logOffset.value}`)
    pollError.value=''
  }catch(e:any){pollError.value=e.message}finally{polling=false}
}
async function action(fn:()=>Promise<any>){busy.value=true;error.value='';notice.value='';try{await fn();await poll()}catch(e:any){error.value=e.message}finally{busy.value=false}}
async function start(){await action(async()=>{const p=currentProfile.value;if(!p)throw Error('请选择已保存的工程配置');const task=await api('/tasks','POST',{project_id:p.project_id,profile_id:p.id,revision:p.revision,resources:{preset:resourcePreset.value,peak_gib:peakGib.value,workers:workers.value}});selected.value=task.id;logOffset.value=0})}
async function stop(){await action(async()=>{await api(`/tasks/${selected.value}/stop`,'POST',{});notice.value=reviewTask.value?'复核停止请求已提交。已写入的队列和收据保留，原静态结果仍可打开。':'停止请求已提交。引擎将中断当前工作并保留已验证 TU；上一次有效扫描仍可打开。'})}
async function retry(){await action(async()=>{const task=await api(`/tasks/${selected.value}/retry`,'POST',{});selected.value=task.id;logOffset.value=0;notice.value=reviewTask.value?'已提交完整输入重验与复核重试；全部复核与仅技术失败复核仍按原任务模式执行。':detail.value?.mode==='multicore'?'已提交固定输入的重新校验与派生重试。':'重新验证真实构建与完整输入闭包；只复用内容身份完全匹配的 TU 缓存。'})}
watch(selected,(id)=>{if(id)emit('focus',id)})
watch(()=>props.focusTask,(id)=>{if(id&&id!==selected.value){selected.value=id;logOffset.value=0;poll()}})
onMounted(async()=>{try{profiles.value=(await api('/profiles')).items;profile.value=profiles.value[0]?.id||'';selected.value=props.focusTask||'';await poll();if(detail.value?.profile_id&&profiles.value.some(p=>p.id===detail.value.profile_id))profile.value=detail.value.profile_id;timer=setInterval(poll,1000)}catch(e:any){error.value=e.message}})
onUnmounted(()=>{if(timer)clearInterval(timer)})
</script>
<template>
  <div class="task-center">
  <h1>扫描任务中心</h1>
  <div v-if="error" class="banner error" role="alert">{{error}}</div><div v-if="notice" class="banner" role="status">{{notice}}</div>
  <div v-if="pollError" class="banner warning" role="alert"><strong>任务状态暂时无法读取，正在重试；保留上次真实详情。</strong><details><summary>查看读取失败原因</summary>{{pollError}}</details></div>
  <section class="panel task-controls"><details :open="!detail"><summary>扫描配置与资源预算 · {{currentProfile?.project_root || '尚未选择工程'}}</summary><label>工程与构建配置<select v-model="profile" aria-label="扫描工程配置" :disabled="busy||active"><option v-for="p in profiles" :value="p.id">{{p.project_root}} · {{p.id.slice(0,8)}}</option></select></label>
    <div class="resource-settings"><label>资源预设<select aria-label="资源预设" v-model="resourcePreset" :disabled="busy||active"><option value="auto">自动</option><option value="low">低内存</option><option value="high">高性能</option><option value="manual">手动预算</option></select></label><label v-if="resourcePreset==='manual'">进程树峰值提交预算（GiB）<input type="number" min="2" max="64" v-model.number="peakGib" :disabled="busy||active"></label><label>最大 TU 并行数<input type="number" min="1" max="8" v-model.number="workers" :disabled="busy||active||resourcePreset==='low'"></label></div></details><button class="primary" :disabled="busy||active||!profile" @click="start">检查并扫描</button><p v-if="!profiles.length">请先在“工程配置”保存真实构建配置。</p>
    <details v-if="detail?.review_materials?.status==='FROZEN'" class="task-boundary"><summary>本任务实际使用的复核资料</summary><p v-for="(item,name) in detail.review_materials.documents">{{name}} · 来源 {{item.origin||'空背景'}} · {{item.bytes}} 字节 · SHA-256 {{item.sha256}}</p></details><details class="task-boundary"><summary>构建检查、数据位置与预算说明</summary><p>输出保存在当前独立数据根。开始后先检查真实构建、全部TU编译输入，通过后才提取事实；失败保留外部诊断和上次有效结果。自动默认软目标 12 GiB、峰值提交预算 16 GiB；低内存采用 6/8 GiB。接近阈值降低后续TU并行并请求安全停止，同一数据根共享一个扫描预算。目标能否满足须由真实工程测量。</p></details>
  </section>
  <div class="overview-columns task-columns"><section class="panel task-detail"><h2>任务与阶段</h2><details v-if="currentProfile"><summary>预先检查并查看全部编译命令</summary><BuildPreflight :profile="currentProfile" @tasks="(id:string)=>{selected=id;logOffset=0;poll()}" /></details><details class="task-history"><summary>任务历史 · {{tasks.length}} 项</summary><button v-for="task in tasks" class="profile" :class="{selected:selected===task.id}" @click="selected=task.id;logOffset=0;poll()">{{taskName(task)}} · {{task.started}}<small>{{task.project_root}}</small></button></details>
    <template v-if="detail"><h3>{{taskName(detail)}}</h3><p class="identity">{{detail.id}} · {{detail.profile_id}}</p><p>{{detail.project_root}}</p>
      <ol class="task-stages"><li v-for="stage in detail.stages" :key="stage.started"><strong>{{stage.stage}}</strong> · {{stage.status==='RUNNING'?'进行中，剩余量未知':stage.status==='COMPLETE'?'阶段结束':stage.status}}<span v-if="stage.seconds"> · {{stage.seconds.toFixed(1)}} s</span></li></ol>
      <p v-if="detail.mode==='multicore'">本任务使用已归档输入，记录实际校验和派生阶段。</p><p v-else-if="detail.memory?.total_units">{{counterName}} {{detail.memory.completed_units}} / {{detail.memory.total_units}}（实际记录）</p>
      <p v-else-if="detail.progress?.total_units">{{counterName}} {{detail.progress.completed_units}} / {{detail.progress.total_units}}（实时计数）</p>
      <p v-if="detail.tu_cache">内容校验后的 TU 缓存：命中 {{detail.tu_cache.hits}}，重新提取 {{detail.tu_cache.extracted}}，损坏 {{detail.tu_cache.corrupt}}</p>
      <div v-if="detail.failure" class="banner error"><strong>{{detail.failure.stage?.stage}}：{{detail.failure.exception_type}}</strong><p>{{detail.failure.message}}</p><p>完整诊断和栈保存在该任务的 diagnostics/exception.log；可检索下方真实日志。</p></div>
      <p v-if="detail.error" class="banner warning">{{detail.error}}</p>
      <div class="task-actions"><button :disabled="busy||!['RUNNING'].includes(detail.state)" @click="stop">安全停止</button><button :disabled="busy||active||!['FAILED','INTERRUPTED'].includes(detail.state)" @click="retry">{{reviewTask?'重新核对输入并重试复核':detail.mode==='multicore'?'重新校验固定输入并重试合并':'从已验证 TU 恢复 / 重试'}}</button><button v-if="detail.published" :disabled="busy" class="primary" @click="emit('open',detail.scan_id)">打开扫描结果</button></div>
      <p v-if="detail.reused_working_inputs">已完整复验并复用原任务 {{detail.reused_working_inputs.source_task}} 的CMake构建、生成输入及SDK。</p>
      <p v-if="reviewTask">重试先完整核对源码、编译器、宏与依赖，再按原任务模式执行：全部疑似/未知重新复核，或仅重跑技术失败。历史收据保留；技术失败不代表安全。</p><p v-else-if="detail.mode==='multicore'">重试将完整核对固定扫描、归档配置和ELF后重新执行派生合并。原有效结果与人工记录保留。</p><p v-else-if="detail.build_mode==='cmake'">恢复先完整复验已固定的源码、编译器、生成输入与SDK，通过后复用构建及匹配的TU。已完成的固定输入若已变化会拒绝恢复，请从工程配置发起新扫描。</p><p v-else>恢复会重新检查源码、编译器、宏与依赖。缓存损坏或输入变化时重新提取；不会复用旧安全结论。</p>
    </template>
  </section><section class="panel task-log-panel"><h2>真实资源与日志</h2><template v-if="detail"><p class="resource-summary">工作集 {{size(detail.resources?.working_set_bytes)}} · 峰值提交 {{size(detail.resources?.peak_job_commit_bytes)}} · 可用磁盘 {{size(detail.resources?.disk_free_bytes)}}</p><button class="resource-details-button" @click="resourcesOpen=true">完整资源采样与趋势</button><WorkspaceDialog :error="pollError" v-if="resourcesOpen" title="真实资源采样与趋势" @close="resourcesOpen=false"><p>进程树工作集：{{size(detail.resources?.working_set_bytes)}}</p><p>进程树私有提交：{{size(detail.resources?.private_bytes)}}</p><p>进程树峰值提交：{{size(detail.resources?.peak_job_commit_bytes)}}</p><p>系统可用物理内存：{{size(detail.resources?.system_physical_available_bytes)}}</p><p>系统提交：{{size(detail.resources?.system_commit_bytes)}} / {{size(detail.resources?.system_commit_limit_bytes)}}</p><p>工作盘可用空间：{{size(detail.resources?.disk_free_bytes)}}</p><p v-if="detail.resource_notice" class="banner warning">{{detail.resource_notice}}</p><p>本任务目录逻辑占用：{{size(detail.task_disk_bytes)}}</p><p>进程数 {{detail.resources?.processes ?? '尚未采样'}} · 内存预算 {{size(detail.budget_bytes)}}</p>
    <p>工作集趋势纵轴：0–{{size(chartMax)}}</p><svg v-if="detail.samples?.length" class="resource-chart" viewBox="0 0 480 100" role="img" aria-label="进程树真实工作集趋势"><polyline fill="none" stroke="#2563eb" stroke-width="2" :points="detail.samples.map((s:any,i:number)=>`${i*480/Math.max(1,detail.samples.length-1)},${100-100*(s.working_set_bytes||0)/chartMax}`).join(' ')" /></svg>
    </WorkspaceDialog><label>检索当前日志段<input v-model="search" aria-label="检索任务日志" placeholder="阶段 / TU / 失败原因"></label><pre class="task-log" tabindex="0">{{lines.join('\n')||'等待真实日志…'}}</pre><div class="task-log-footer"><p>日志字节 {{detail.log.offset}}–{{detail.log.next_offset}} / {{detail.log.total}}，按段完整读取</p><div class="actions"><button :disabled="!logOffset" @click="logOffset=Math.max(0,logOffset-65536);poll()">上一段</button><button :disabled="detail.log.next_offset>=detail.log.total" @click="logOffset=detail.log.next_offset;poll()">下一段</button></div></div>
  </template><p v-else>选择任务后显示真实进程和诊断数据。</p></section></div>
  </div>
</template>
