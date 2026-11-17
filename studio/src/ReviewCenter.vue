<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from './api'
import WorkspaceDialog from './WorkspaceDialog.vue'
import ReviewMaterials from './ReviewMaterials.vue'
import ReviewAnswer from './ReviewAnswer.vue'
import SourceViewer from './SourceViewer.vue'
const selected=ref<any>(null),configurationOpen=ref(false),artifactBusy=ref(false)
let artifactRequest=0
function closeArtifact(){artifactRequest++;artifact.value=null;artifactBusy.value=false}
const props=defineProps<{scan:string, projectId:string, profileId?:string,canReview:boolean}>()
const emit=defineEmits<{tasks:[taskId?:string]}>()
const profiles=ref<any[]>([]), profile=ref(''), page=ref<any>(null), offset=ref(0), busy=ref(false), error=ref(''), artifact=ref<any>(null), artifactName=ref('')
const outcome=ref(''),search=ref(''),source=ref<any>(null)
const appliedSearch=ref(''), pollError=ref(''),confirmAll=ref(false),starting=ref(false)
const progress=computed(()=>page.value?.progress)
const availability=ref<any>(null),checking=ref(false)
const runtime=computed(()=>availability.value||page.value?.opencode)
async function checkOpenCode(){if(checking.value)return;checking.value=true;error.value='';try{const p=profiles.value.find(p=>p.id===profile.value);if(!p)throw Error('请选择复核配置');availability.value=await api('/profiles/opencode-check','POST',{project_id:p.project_id,profile_id:p.id});if(!availability.value.ready)error.value=availability.value.error}catch(e:any){error.value=e.message}finally{checking.value=false}}
const percentage=computed(()=>progress.value?.total?(100*progress.value.done/progress.value.total).toFixed(1):'0.0')
const groups=[['confirmed','确认风险'],['likely','疑似风险'],['safe','确认安全 / 误报'],['unresolved','待复核 / 无法判断']]
const names:Record<string,string>={PENDING:'等待复核',RUNNING:'正在复核',DONE:'已通过答复与收据校验',TECH_FAILED:'技术失败',STALE:'证据已失效',CONFIRMED:'OpenCode确认存在风险',LIKELY:'OpenCode认为可能有风险',FALSE_POSITIVE:'OpenCode确认静态误报',REVIEWED_SAFE:'OpenCode确认条件下安全',NEED_MORE_CONTEXT:'需要补充证据'}
let pageRequest=0, timer:ReturnType<typeof setInterval>|undefined, polling=false
async function refresh(background=false){
  if(background&&(busy.value||polling||document.hidden))return
  const mine=++pageRequest
  if(background)polling=true
  else{busy.value=true;pollError.value=''}
  const params=new URLSearchParams({offset:String(offset.value),outcome:outcome.value,search:appliedSearch.value})
  if(background&&page.value)params.set('revision',String(page.value.revision))
  try{
    let value=await api(`/scans/${props.scan}/ai?`+params)
    if(mine!==pageRequest)return
    pollError.value=''
    if(value.unchanged){page.value={...page.value,opencode:value.opencode,initialization_error:value.initialization_error,configuration_error:value.configuration_error};return}
    if(offset.value&&offset.value>=value.total){
      offset.value=value.total?Math.floor((value.total-1)/50)*50:0
      params.set('offset',String(offset.value));params.delete('revision')
      value=await api(`/scans/${props.scan}/ai?`+params)
      if(mine!==pageRequest)return
    }
    page.value=value
    const fid=selected.value?.finding_id
    if(fid){
      const row=value.items.find((item:any)=>item.finding_id===fid)
      if(row)selected.value=row
      else if(background){
        const detail=await api(`/scans/${props.scan}/ai?limit=1&finding_id=`+encodeURIComponent(fid))
        if(mine===pageRequest&&selected.value?.finding_id===fid&&detail.items.length)selected.value=detail.items[0]
      }
    }
  }catch(e:any){if(mine===pageRequest)pollError.value='暂时无法更新已归档结果。'+e.message}
  finally{if(background)polling=false;else if(mine===pageRequest)busy.value=false}
}
function filter(value:string){outcome.value=value;offset.value=0;selected.value=null;refresh()}
function submitSearch(){appliedSearch.value=search.value;offset.value=0;refresh()}
function clearSearch(){search.value='';appliedSearch.value='';filter('')}
async function start(mode:string){if(starting.value)return;confirmAll.value=false;starting.value=true;error.value='';try{const p=profiles.value.find(p=>p.id===profile.value);if(!p)throw Error('请选择当前工程的复核配置');const task=await api('/tasks','POST',{project_id:p.project_id,profile_id:p.id,revision:p.revision,mode,scan_id:props.scan});emit('tasks',task.id)}catch(e:any){error.value=e.message}finally{starting.value=false}}
async function readArtifact(name:string, position=0){if(artifactBusy.value)return;const mine=++artifactRequest;artifactBusy.value=true;error.value='';try{const query=new URLSearchParams({name,offset:String(position),finding_id:selected.value?.finding_id||''});const value=await api(`/scans/${props.scan}/ai-artifact?`+query);if(mine===artifactRequest){artifactName.value=name;artifact.value=value}}catch(e:any){if(mine===artifactRequest)error.value=e.message}finally{if(mine===artifactRequest)artifactBusy.value=false}}
function receipts(row:any){const names=new Set<string>(row.state==='DONE'&&row.archived_files?[row.finding_id+'.result.json']:[]);for(const record of [row,...(row.attempts||[])])for(const key of ['packet_file','prompt_file','stdout_file','stderr_file'])if(record[key])names.add(record[key]);return [...names]}
onMounted(async()=>{void refresh();timer=setInterval(()=>void refresh(true),1500);try{profiles.value=(await api('/profiles')).items.filter((p:any)=>p.project_id===props.projectId);profile.value=profiles.value.find(p=>p.id===props.profileId)?.id||profiles.value[0]?.id||''}catch(e:any){error.value=e.message}})
onUnmounted(()=>{clearInterval(timer);pageRequest++})
</script>
<template>
  <div class="records-page ai-center"><h1>OpenCode 逐项复核</h1><p>静态分类、AI 答复和人工确认分别保留。打开本页不会调用模型或重新提取 TU。</p><div v-if="error" class="banner error" role="alert">{{error}}</div>
  <p v-if="!canReview" class="banner warning">归档模式缺少本机检查点或原源码，不能重新复核；可查看已有答复与收据。</p><section class="ai-controls"><details :open="configurationOpen" @toggle="configurationOpen=($event.target as HTMLDetailsElement).open"><summary>复核配置与执行说明</summary>
    <label>复核配置<select v-model="profile" aria-label="OpenCode复核配置"><option v-for="p in profiles" :value="p.id">{{p.name}} · {{p.project_root}} · {{p.id.slice(0,8)}}</option></select></label>
    <button :disabled="checking||!profile" @click="checkOpenCode">{{checking?'正在检查本地配置…':'检查本地启动条件（不运行 OpenCode）'}}</button>
    <p v-if="runtime">OpenCode · 版本：{{runtime.version||'未查询'}} · 基础复核：{{runtime.capabilities?.review||'NOT_TESTED'}} · 存储身份：{{runtime.capabilities?.storage||'NOT_TESTED'}} · 清理：{{runtime.capabilities?.cleanup||'NOT_TESTED'}}</p>
    <p v-if="runtime" class="identity">实际入口：{{runtime.command?.join(' ')}}<br/>{{runtime.notice||''}}</p>
    <p v-if="runtime?.cleanup_error" class="banner warning">清理未完成，会话已保留：{{runtime.cleanup_error}}</p>
    <p v-if="page?.initialization_error" class="banner error" role="alert">{{page.initialization_error.error}}；未派发项保持待复核。</p>
    <p v-if="page?.configuration_error" class="banner error" role="alert">{{page.configuration_error.error}}</p>
    <p>使用该配置中的 command、provider/model、Worker、超时和重试设置。发起后先验证原输入闭包；模型或工具不可用会记录“技术失败”。</p>
    </details><ReviewMaterials/><div class="actions"><button class="primary" :disabled="starting||!canReview||!profile||!(progress?.pending||progress?.tech_failed)" @click="start('review-resume')">继续复核剩余项</button><button :disabled="starting||!canReview||!profile||!progress?.total" @click="confirmAll=true">重新复核全部</button><button :disabled="starting||!canReview||!profile||!progress?.tech_failed" @click="start('review-failed')">仅重试技术失败</button><button @click="emit('tasks')">任务日志与安全停止</button></div>
  </section>
  <p v-if="progress" class="ai-progress" role="status"><strong>OpenCode 复核进度 {{percentage}}%</strong> · 总复核对象 {{progress.total}} · 已完成 {{progress.done}} · 技术失败 {{progress.tech_failed}} · 待复核 {{progress.pending}}</p>
  <p v-if="pollError" class="banner warning" role="alert">{{pollError}} <button :disabled="busy" @click="refresh()">重试读取</button></p>
  <WorkspaceDialog v-if="confirmAll" title="重新复核全部疑似与未知" @close="confirmAll=false"><p>此操作会重新调用 OpenCode 复核所有疑似或未知项，包括已经归档的项目。历史收据保留。</p><template #footer><button @click="confirmAll=false">取消</button><button class="primary" @click="start('review')">确认重新复核</button></template></WorkspaceDialog>
  <template v-if="page"><div class="ai-outcomes" role="group" aria-label="OpenCode结论分类"><button :aria-pressed="!outcome" @click="filter('')">全部 {{page.all_total}}</button><button v-for="[key,title] in groups" :key="key" :aria-pressed="outcome===key" @click="filter(key)">{{title}} {{page.groups[key]||0}}</button></div><form class="ai-search" @submit.prevent="submitSearch"><label class="sr-only" for="ai-search">查找复核变量或文件</label><input id="ai-search" v-model="search" maxlength="256" placeholder="变量名、文件、存储身份或复核编号"><button :disabled="busy">搜索复核结果</button><button type="button" @click="clearSearch">清除筛选</button><details><summary>执行状态与统计说明</summary><p>按原报告规则分类：仅有效 DONE 结论进入风险、安全或误报；疑似风险和证据不足单列。计数为本轮复核对象，独立证据缺口也会明确标识，不等同于全部变量数。</p><span v-for="(count,state) in page.states" class="tag">{{names[String(state)]||state}}：{{count}}</span></details></form><p v-if="!page.all_total">此结果没有独立 AI 账本；可在静态归档索引查看旧格式记录。未复核不能解释为安全。</p>
  <div class="inspector-layout" :class="{'no-inspector':!selected}"><section class="panel inspector-list"><p v-if="page.all_total&&!page.total" role="status">没有符合当前筛选的复核对象。可切换分类或清除筛选。</p><table v-else class="data-table ai-table"><thead><tr><th>变量 / 复核对象</th><th>OpenCode结论</th><th>尝试</th></tr></thead><tbody><tr v-for="row in page.items" :key="row.finding_id" :class="{selected:selected?.finding_id===row.finding_id}"><td><button @click="selected=row">{{row.name||row.finding_id}}</button><small>{{row.definition_file?row.definition_file+':'+row.definition_line:row.symbol_id?'存储对象':'独立证据缺口'}}</small></td><td>{{row.state==='DONE'?(names[row.status]||'无法判断'):(names[row.state]||row.state)}}<small v-if="row.state==='DONE'">已归档</small><span v-if="row.error" class="ai-note" :title="row.error"> · 说明</span></td><td>{{row.attempt_count||0}}</td></tr></tbody></table></section>
  <section v-if="selected" class="panel inspector-detail"><div class="page-heading"><h2>{{selected.name||'独立证据缺口'}}</h2><button @click="selected=null">关闭详情</button></div><p>{{selected.state==='DONE'?(names[selected.status]||'无法判断'):(names[selected.state]||selected.state)}}<span v-if="selected.state==='DONE'"> · 已归档</span></p><button v-if="selected.definition_file" @click="source={file:selected.definition_file,line:selected.definition_line||1}">查看定义 · {{selected.definition_file}}:{{selected.definition_line}}</button><p v-if="selected.error" class="banner" :class="{error:selected.state==='TECH_FAILED'}">{{selected.failure_stage?selected.failure_stage+'：':'执行说明：'}}{{selected.error}}</p><ReviewAnswer v-if="selected.state==='DONE'&&selected.answer" :answer="selected.answer" @source="source=$event"/><p v-else>本项尚无当前有效的复核结论，不能判定安全。</p><details v-if="selected.state!=='DONE'&&selected.answer"><summary>历史答复（不作为当前结论）</summary><pre>{{JSON.stringify(selected.answer,null,2)}}</pre></details><details><summary>复核身份、执行与阅读收据</summary><p class="identity">{{selected.finding_id}} · {{selected.symbol_id}}</p><p>尝试 {{selected.attempt_count||0}} 次 · 格式修复 {{selected.format_fix_count||0}} · 摘要修复 {{selected.summary_fix_count||0}}</p><h3>Packet / 提示词 / 原始响应</h3><div class="receipt-files"><button v-for="name in receipts(selected)" @click="readArtifact(name)">{{name}}</button></div></details></section></div>
  <div class="page-controls"><button :disabled="busy||!offset" @click="offset=Math.max(0,offset-50);refresh()">上一页</button><p>显示 {{page.total?offset+1:0}}–{{Math.min(offset+50,page.total)}} / {{page.total}}</p><button :disabled="busy||page.next_offset===null" @click="offset=page.next_offset;refresh()">下一页</button></div></template>
  <WorkspaceDialog v-if="source" title="复核源码依据" @close="source=null"><SourceViewer :scan="scan" :file="source.file" :line="source.line||1"/></WorkspaceDialog><WorkspaceDialog v-if="artifact" title="AI 复核审计原件" @close="closeArtifact"><p v-if="error" class="banner error" role="alert">{{error}}</p><p class="identity">{{artifactName}} · 字节 {{artifact.offset}}–{{artifact.next_offset??artifact.total}} / {{artifact.total}}</p><pre>{{artifact.text}}</pre><template #footer><button :disabled="artifactBusy||!artifact.offset" @click="readArtifact(artifactName)">回到开始</button><button :disabled="artifactBusy||artifact.next_offset===null" @click="readArtifact(artifactName,artifact.next_offset)">继续完整读取</button></template></WorkspaceDialog></div>
</template>
<style scoped>.ai-progress{margin:0}.ai-controls{display:flex;flex-wrap:wrap;align-items:center;gap:8px}.ai-controls>details[open]{flex-basis:100%}.ai-controls summary{margin-bottom:0}.ai-controls :deep(.review-materials){margin-top:0}.ai-outcomes{display:flex;flex-wrap:wrap;gap:6px}.ai-outcomes [aria-pressed=true]{background:#eaf1ff;border-color:var(--accent);color:#194ebf}.ai-search{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.ai-search input{flex:1;min-width:180px;margin:0}.ai-search details{font-size:12px}.ai-search details[open]{flex-basis:100%}.ai-search details p{max-width:80em}.ai-center:has(.ai-controls details[open]){height:auto;flex:none}.ai-center:has(.ai-controls details[open]) .inspector-layout{min-height:480px}:global(main.records-main:has(.ai-controls details[open])){overflow:auto}.ai-table th:first-child{width:50%}.ai-table th:nth-child(2){width:38%}.ai-table th:last-child{width:12%}</style>
