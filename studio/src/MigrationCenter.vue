<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from './api'
const emit=defineEmits<{open:[id:string],completed:[]}>()
const source=ref(''),project=ref(''),plan=ref<any>(null),job=ref<any>(null),history=ref<any>(null)
const error=ref(''),checking=ref(false),busy=ref(false)
let timer:ReturnType<typeof setTimeout>|undefined
const phases:Record<string,string>={PREPARING:'核对来源',COPYING:'捕获与校验旧文件',CONVERTING:'转换完整事实与报告',VALIDATING:'校验证据与关系',COMPLETE:'迁移完成',FAILED:'迁移失败',RUNNING:'迁移执行中',INTERRUPTED:'上次迁移已中断'}
const title=(s:string)=>phases[s]||s
async function refresh(offset=0){try{history.value=await api('/migrations?offset='+offset)}catch(e:any){error.value=e.message}}
async function inspect(){checking.value=true;error.value='';plan.value=null;try{plan.value=await api('/migrations/preview','POST',{source:source.value,project_root:project.value})}catch(e:any){error.value=e.message}finally{checking.value=false}}
async function poll(){
  try{
    if(!job.value)return
    job.value=await api('/migrations/'+job.value.id)
    if(job.value.state==='RUNNING'){busy.value=true;timer=setTimeout(poll,1000)}
    else{busy.value=false;await refresh();if(job.value.state==='COMPLETE')emit('completed');if(job.value.error)error.value=job.value.error}
  }catch(e:any){error.value=e.message;busy.value=false}
}
async function start(){
  busy.value=true;error.value=''
  try{job.value=await api('/migrations','POST',{source:source.value,project_root:project.value,revision:plan.value.revision});plan.value=null;await poll()}
  catch(e:any){error.value=e.message;busy.value=false}
}
async function view(item:any){clearTimeout(timer);job.value=item;error.value='';await poll()}
watch([source,project],()=>plan.value=null)
onMounted(async()=>{try{await refresh();const live=history.value.items.find((item:any)=>item.state==='RUNNING');if(live)await view(live)}catch(e:any){error.value=e.message}})
onUnmounted(()=>clearTimeout(timer))
</script>
<template>
  <section class="panel" aria-label="旧结果只读迁移">
    <h2>迁移旧 .ecra / 工具 workspace</h2>
    <p>选择包含 run.json、scan_state.json、facts.json 和静态报告的旧结果目录。先核对归属，再在独立数据根转换；原目录保持不变。</p>
    <div v-if="error" class="banner error" role="alert">{{error}}</div>
    <div class="overview-columns">
      <label>旧结果目录（绝对路径）<input v-model="source" :disabled="busy" placeholder="D:/Firmware/Board/.ecra"></label>
      <label>旧记录中的原工程目录<input v-model="project" :disabled="busy" placeholder="D:/Firmware/Board"></label>
    </div>
    <button :disabled="busy||checking||!source.trim()||!project.trim()" @click="inspect">检查旧目录与归属</button>
    <p v-if="checking" role="status">正在核对身份与文件清单，剩余量未知…</p>
    <section v-if="plan" class="banner warning" aria-label="旧迁移计划">
      <h3>归属匹配 · 旧归档只读转换</h3><p class="identity">{{plan.source}}</p>
      <p>{{plan.files}} 个原文件 · {{(plan.logical_bytes/1024/1024).toFixed(2)}} MiB。转换时另需SQLite、证据与暂存空间，当前不承诺磁盘收益。</p>
      <p>{{plan.warning}}</p><button :disabled="busy" @click="start">开始只读迁移</button>
    </section>
    <section v-if="job" aria-label="旧迁移执行状态">
      <h3>{{title(job.state)}}<template v-if="job.stage!==job.state"> · {{title(job.stage)}}</template></h3><p class="identity">{{job.source}}</p><p>{{job.message}}</p>
      <p v-if="job.files!==undefined">已捕获 {{job.files}} / {{job.total}} 个文件（不是全流程百分比）</p>
      <p v-if="busy" role="status">任务在本地后台执行，可切换页面。校验结束前不会发布为完整结果，剩余量未知。</p>
      <template v-if="job.state==='COMPLETE'"><p>{{job.result.warning}}</p><p v-if="job.result.repeated">相同来源已导入：打开已有归档，原人工确认保留。</p><p v-for="warning in job.result.cleanup_warnings">{{warning}}</p><button @click="emit('open',job.scan_id)">打开迁移结果</button></template>
    </section>
    <details><summary>迁移历史与中断诊断</summary><button :disabled="checking" @click="refresh()">刷新迁移历史</button>
      <article v-for="item in history?.items" :key="item.id" class="history-row"><div><strong>{{title(item.state)}}</strong><p class="identity">{{item.source}}</p><p>{{item.started}} · {{item.error}}</p></div><button @click="view(item)">查看迁移记录</button></article>
      <div v-if="history" class="page-controls"><button :disabled="history.offset===0" @click="refresh(Math.max(0,history.offset-50))">上一页迁移</button><span>{{history.total}} 个记录</span><button :disabled="history.next_offset===null" @click="refresh(history.next_offset)">下一页迁移</button></div>
    </details>
  </section>
</template>
