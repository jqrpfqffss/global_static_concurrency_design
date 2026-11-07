<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from './api'
import WorkspaceDialog from './WorkspaceDialog.vue'
const planOpen=ref(false)
const props=defineProps<{profile:any}>()
const emit=defineEmits<{ready:[id:string],tasks:[id:string]}>()
const task=ref<any>(null),plan=ref<any>(null),error=ref(''),busy=ref(false),offset=ref(0)
const admitted=ref('')
let timer:ReturnType<typeof setInterval>|undefined,polling=false,generation=0
const running=()=>['RUNNING','STOP_REQUESTED'].includes(task.value?.state)
async function page(start:number){const id=task.value?.id;if(!id)return;const value=await api(`/tasks/${id}/plan?offset=${start}`);if(task.value?.id===id){plan.value=value;offset.value=start}}
async function poll(){
  if(polling||!task.value?.id)return
  polling=true;const id=task.value.id,epoch=generation
  try{const value=await api('/tasks/'+id);if(epoch!==generation||task.value?.id!==id)return;task.value=value
    if(value.state==='COMPLETE'&&value.preflight?.passed){if(!plan.value)await page(0);if(epoch!==generation||task.value?.id!==id)return;emit('ready',admitted.value===id?id:'')}
    else emit('ready','')
    error.value=''
  }catch(e:any){if(epoch===generation){error.value=e.message;emit('ready','')}}finally{polling=false}
}
async function action(fn:()=>Promise<any>){if(busy.value)return;busy.value=true;error.value='';try{await fn()}catch(e:any){error.value=e.message;emit('ready','')}finally{busy.value=false}}
async function start(){await action(async()=>{const epoch=++generation;emit('ready','');admitted.value='';task.value=null;plan.value=null;offset.value=0;const p=props.profile
  if(!p)throw Error('请先检查并保存当前独立配置。')
  const value=await api('/tasks','POST',{project_id:p.project_id,profile_id:p.id,revision:p.revision,mode:'precheck',resources:{preset:'auto',workers:4}})
  if(epoch===generation&&props.profile?.revision===p.revision&&props.profile?.id===p.id){admitted.value=value.id;task.value=value;await poll()}
})}
async function reopen(){const epoch=++generation;emit('ready','');admitted.value='';task.value=null;plan.value=null;offset.value=0;error.value=''
  const p=props.profile;if(!p)return
  try{const rows=(await api('/tasks')).items;if(epoch!==generation)return;task.value=rows.find((t:any)=>t.mode==='precheck'&&t.project_id===p.project_id&&t.profile_id===p.id&&t.profile_revision===p.revision)||null;if(running())admitted.value=task.value.id;await poll()}catch(e:any){if(epoch===generation)error.value=e.message}
}
watch(()=>props.profile?.project_id+'|'+props.profile?.id+'|'+props.profile?.revision,reopen)
onMounted(()=>{reopen();timer=setInterval(poll,1000)})
onUnmounted(()=>{generation++;if(timer)clearInterval(timer)})
</script>
<template>
  <section class="build-preflight" aria-label="真实构建预检查">
    <h3>真实构建检查与执行计划</h3>
    <p>实际配置/构建所选目标，并用全部TU的真实Clang参数检查编译输入。检查不会生成静态安全结论；OpenCode不参与此门禁。</p>
    <p v-if="!profile">保存当前独立配置后即可检查。</p>
    <button :disabled="busy||!profile||running()" @click="start">{{task?'重新检查真实构建':'检查真实构建'}}</button>
    <button v-if="running()" :disabled="busy||task.state==='STOP_REQUESTED'" @click="action(async()=>{await api('/tasks/'+task.id+'/stop','POST',{});await poll()})">安全停止检查</button>
    <button v-if="task" @click="emit('tasks',task.id)">查看检查日志与资源</button>
    <p v-if="error" class="banner error" role="alert">{{error}}</p>
    <p v-if="running()" role="status">{{task.progress?.stage||'正在准备真实检查，剩余量未知'}}<span v-if="task.progress?.total_units"> · 已检查 {{task.progress.completed_units}} / {{task.progress.total_units}} TU</span></p>
    <div v-if="task&&['FAILED','INTERRUPTED'].includes(task.state)" class="banner error" role="alert"><strong>检查未通过，不能从向导启动扫描。</strong><p>{{task.preflight?.error||task.error||'检查已停止，请查看诊断后重试。'}}</p><p>{{task.preflight?.repair||'原有效结果与人工记录保留。'}}</p></div>
    <template v-if="plan?.check?.passed&&task?.state==='COMPLETE'">
      <div class="banner" role="status">真实构建与编译输入检查通过 · {{plan.check.finished}}。{{admitted===task.id?'正式扫描会重新检查。':'这是历史检查记录；请重新检查后从向导启动。'}}</div>
      <button @click="planOpen=true">查看完整构建计划与逐 TU 参数</button><WorkspaceDialog v-if="planOpen" title="真实构建计划与完整编译参数" @close="planOpen=false"><p>工程：{{plan.check.project_root}}</p><p v-if="plan.check.analysis_root!==plan.check.project_root">固定版本分析根：{{plan.check.analysis_root}}</p>
      <p>目标：{{plan.check.target||'真实编译数据库闭包'}} · 变体：{{plan.check.variant||'以逐TU参数为准'}}</p>
      <p>独立数据：{{plan.check.data_root}}</p><p>编译数据库：{{plan.check.compile_database}}</p><p v-if="plan.check.build_root">独立构建：{{plan.check.build_root}}</p>
      <p v-if="plan.check.git">{{plan.check.git.base_ref}} → {{plan.check.git.current_ref}} · {{plan.check.git.base_sha}} → {{plan.check.git.head_sha}}</p>
      <p>全部 {{plan.total}} TU · 已校验 {{plan.check.input_files}} 个输入 · {{plan.check.snapshot_status}}</p>
      <details><summary>实际工具路径与版本 · {{plan.check.tools.length}} 项</summary><article v-for="tool in plan.check.tools"><strong>{{tool.field}}</strong><p>{{tool.path}}</p><pre>{{tool.version||tool.sha256}}</pre></article></details>
      <p>编译命令 {{plan.total?offset+1:0}}–{{Math.min(offset+plan.limit,plan.total)}} / {{plan.total}}，逐TU展开查看全部参数</p>
      <details v-for="unit in plan.items" :key="unit.ordinal"><summary>{{unit.ordinal+1}} · {{unit.source_file}}</summary><p>工作目录：{{unit.directory}}</p><h4>原始编译参数（顺序保留）</h4><pre>{{JSON.stringify(unit.original_arguments,null,2)}}</pre><h4>实际Clang参数（含宏、核心、include与ABI选项）</h4><pre>{{JSON.stringify(unit.arguments,null,2)}}</pre><p>引擎推断目标：{{unit.inferred_target||'以实际参数为准'}}</p></details>
      <div class="actions"><button :disabled="busy||!offset" @click="action(()=>page(Math.max(0,offset-plan.limit)))">上一页编译命令</button><button :disabled="busy||plan.next_offset===null" @click="action(()=>page(plan.next_offset))">下一页编译命令</button></div></WorkspaceDialog>
    </template>
  </section>
</template>
<style scoped>
.build-preflight{min-width:0;overflow-wrap:anywhere}.build-preflight pre{white-space:pre-wrap;overflow-wrap:anywhere;overflow-x:auto}.build-preflight details{margin:8px 0}.build-preflight button{margin:4px 8px 4px 0}.build-preflight article{border-bottom:1px solid var(--border,#d7dee8);padding:8px 0}
</style>
