<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from './api'
import { createTask, taskCreationPending } from './taskLaunch'
import WorkspaceDialog from './WorkspaceDialog.vue'

const props=defineProps<{profile:any,disabled?:boolean}>()
const emit=defineEmits<{tasks:[id:string]}>()
const task=ref<any>(null),plan=ref<any>(null),planOpen=ref(false),offset=ref(0)
const busy=ref(false),planBusy=ref(false),error=ref(''),statusError=ref(''),planError=ref('')
const planRetryOffset=ref(0)
let timer:ReturnType<typeof setInterval>|undefined,polling=false,generation=0,lookup=false,needsDetail=false
const running=()=>['RUNNING','STOP_REQUESTED'].includes(task.value?.state)
const passed=()=>task.value?.state==='COMPLETE'&&task.value.preflight?.passed

async function readPlan(start:number){
  if(planBusy.value||!passed())return
  const id=task.value.id,epoch=generation
  planBusy.value=true
  planRetryOffset.value=start
  try{
    const value=await api(`/tasks/${id}/plan?offset=${start}`)
    if(epoch===generation){plan.value=value;offset.value=start;planError.value=''}
  }catch(e:any){if(epoch===generation)planError.value=e.message}
  finally{if(epoch===generation)planBusy.value=false}
}
async function poll(){
  const p=props.profile
  if(polling||!p)return
  if(!lookup&&(!task.value||(!needsDetail&&!running()&&!statusError.value)))return
  polling=true
  const epoch=generation
  try{
    if(lookup){
      const rows=(await api('/tasks')).items
      if(epoch!==generation)return
      task.value=rows.find((t:any)=>t.mode==='precheck'&&t.project_id===p.project_id&&t.profile_id===p.id&&t.profile_revision===p.revision)||null
      lookup=false
    }
    if(task.value){
      const value=await api('/tasks/'+task.value.id)
      if(epoch!==generation)return
      if(value.metadata_error)throw Error(value.error)
      task.value=value
      needsDetail=false
    }
    statusError.value=''
    if(passed()&&!plan.value&&!planError.value)await readPlan(0)
  }catch(e:any){if(epoch===generation)statusError.value=e.message}
  finally{polling=false}
}
async function action(fn:()=>Promise<void>){
  if(busy.value)return
  busy.value=true;error.value=''
  try{await fn()}catch(e:any){error.value=e.message}
  finally{busy.value=false}
}
function reset(findHistory:boolean){
  generation++;lookup=findHistory;needsDetail=false
  task.value=null;plan.value=null;planOpen.value=false;offset.value=0
  statusError.value='';planError.value='';planBusy.value=false
}
async function start(){
  const p=props.profile
  if(!p||props.disabled||taskCreationPending.value||running())return
  await action(async()=>{
    const epoch=generation
    const value=await createTask(p,'precheck',{preset:'auto'})
    if(epoch!==generation)return
    reset(false)
    task.value=value
    needsDetail=true
    await poll()
  })
}
function reopen(){reset(true);error.value='';void poll()}
watch(()=>props.profile?.project_id+'|'+props.profile?.id+'|'+props.profile?.revision,reopen)
onMounted(()=>{reopen();timer=setInterval(poll,1000)})
onUnmounted(()=>{generation++;if(timer)clearInterval(timer)})
</script>
<template>
  <section class="build-preflight" aria-label="真实构建预检查">
    <h3>真实构建检查与执行计划</h3>
    <p>实际配置/构建所选目标，并用全部TU的真实Clang参数检查编译输入。检查不会生成静态安全结论；OpenCode不参与此门禁。</p>
    <p v-if="!profile">保存当前独立配置后即可检查。</p>
    <button :disabled="disabled||busy||taskCreationPending||!profile||running()" @click="start">{{task?'重新检查真实构建':'检查真实构建'}}</button>
    <button v-if="running()" :disabled="busy||task.state==='STOP_REQUESTED'" @click="action(async()=>{await api('/tasks/'+task.id+'/stop','POST',{});await poll()})">安全停止检查</button>
    <button v-if="task" @click="emit('tasks',task.id)">查看检查日志与资源</button>
    <p v-if="error" class="banner error" role="alert">{{error}}</p>
    <p v-if="statusError" class="banner warning" role="alert">任务状态暂时无法读取，正在重试。{{statusError}}</p>
    <p v-if="running()" role="status">{{task.state==='STOP_REQUESTED'?'检查停止请求已发送':task.progress?.stage||'正在准备真实检查，剩余量未知'}}<span v-if="task.progress?.total_units"> · 已检查 {{task.progress.completed_units}} / {{task.progress.total_units}} TU</span></p>
    <div v-if="task&&['FAILED','INTERRUPTED'].includes(task.state)" class="banner error" role="alert"><strong>{{task.state==='FAILED'?'检查未通过':'检查已停止 / 上次中断'}}</strong><p>{{task.preflight?.error||task.error||'请查看本任务的日志与诊断。'}}</p><p v-if="task.preflight?.repair">{{task.preflight.repair}}</p></div>
    <p v-if="passed()" class="banner" role="status">真实构建与编译输入检查通过，尚未开始扫描。</p>
    <template v-if="passed()&&planError">
      <p class="banner warning" role="alert">检查已通过，编译计划暂时无法读取。{{planError}}</p>
      <button :disabled="planBusy" @click="readPlan(planRetryOffset)">重试读取编译计划</button>
    </template>
    <template v-if="passed()&&plan?.check?.passed">
      <button @click="planOpen=true">查看完整构建计划与逐 TU 参数</button><WorkspaceDialog v-if="planOpen" title="真实构建计划与完整编译参数" @close="planOpen=false"><p v-if="planError" class="banner warning" role="alert">编译计划暂时无法读取。{{planError}} <button :disabled="planBusy" @click="readPlan(planRetryOffset)">重试读取此页</button></p><p>工程：{{plan.check.project_root}}</p><p v-if="plan.check.analysis_root!==plan.check.project_root">固定版本分析根：{{plan.check.analysis_root}}</p>
      <p>目标：{{plan.check.target||'真实编译数据库闭包'}} · 变体：{{plan.check.variant||'以逐TU参数为准'}}</p>
      <p>独立数据：{{plan.check.data_root}}</p><p>编译数据库：{{plan.check.compile_database}}</p><p v-if="plan.check.build_root">独立构建：{{plan.check.build_root}}</p>
      <p v-if="plan.check.git">{{plan.check.git.base_ref}} → {{plan.check.git.current_ref}} · {{plan.check.git.base_sha}} → {{plan.check.git.head_sha}}</p>
      <p>全部 {{plan.total}} TU · 已校验 {{plan.check.input_files}} 个输入 · {{plan.check.snapshot_status}}</p>
      <details><summary>实际工具路径与版本 · {{plan.check.tools.length}} 项</summary><article v-for="tool in plan.check.tools"><strong>{{tool.field}}</strong><p>{{tool.path}}</p><pre>{{tool.version||tool.sha256}}</pre></article></details>
      <p>编译命令 {{plan.total?offset+1:0}}–{{Math.min(offset+plan.limit,plan.total)}} / {{plan.total}}，逐TU展开查看全部参数</p>
      <details v-for="unit in plan.items" :key="unit.ordinal"><summary>{{unit.ordinal+1}} · {{unit.source_file}}</summary><p>工作目录：{{unit.directory}}</p><h4>原始编译参数（顺序保留）</h4><pre>{{JSON.stringify(unit.original_arguments,null,2)}}</pre><h4>实际Clang参数（含宏、核心、include与ABI选项）</h4><pre>{{JSON.stringify(unit.arguments,null,2)}}</pre><p>引擎推断目标：{{unit.inferred_target||'以实际参数为准'}}</p></details>
      <div class="actions"><button :disabled="planBusy||!offset" @click="readPlan(Math.max(0,offset-plan.limit))">上一页编译命令</button><button :disabled="planBusy||plan.next_offset===null" @click="readPlan(plan.next_offset)">下一页编译命令</button></div></WorkspaceDialog>
    </template>
  </section>
</template>
<style scoped>
.build-preflight{min-width:0;overflow-wrap:anywhere}.build-preflight pre{white-space:pre-wrap;overflow-wrap:anywhere;overflow-x:auto}.build-preflight details{margin:8px 0}.build-preflight button{margin:4px 8px 4px 0}.build-preflight article{border-bottom:1px solid var(--border,#d7dee8);padding:8px 0}
</style>
