<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from './api'
const props=defineProps<{scan:string, projectId:string, canReview:boolean}>()
const emit=defineEmits<{tasks:[]}>()
const profiles=ref<any[]>([]), profile=ref(''), page=ref<any>(null), offset=ref(0), busy=ref(false), error=ref(''), artifact=ref<any>(null), artifactName=ref('')
const names:Record<string,string>={PENDING:'等待复核',RUNNING:'正在复核',DONE:'已通过答复与收据校验',TECH_FAILED:'技术失败',STALE:'证据已失效',CONFIRMED:'AI确认存在风险',LIKELY:'AI认为可能有风险',FALSE_POSITIVE:'AI认为静态误报',SAFE:'AI认为条件下安全',NEED_MORE_CONTEXT:'需要补充证据'}
async function refresh(){page.value=await api(`/scans/${props.scan}/ai?offset=${offset.value}`)}
async function start(mode:string){busy.value=true;error.value='';try{const p=profiles.value.find(p=>p.id===profile.value);if(!p)throw Error('请选择当前工程的复核配置');await api('/tasks','POST',{project_id:p.project_id,profile_id:p.id,revision:p.revision,mode,scan_id:props.scan});emit('tasks')}catch(e:any){error.value=e.message}finally{busy.value=false}}
async function readArtifact(name:string, position=0){error.value='';try{artifactName.value=name;artifact.value=await api(`/scans/${props.scan}/ai-artifact?name=${encodeURIComponent(name)}&offset=${position}`)}catch(e:any){error.value=e.message}}
function receipts(row:any){const names=new Set<string>();for(const record of [row,...(row.attempts||[])])for(const key of ['packet_file','prompt_file','stdout_file','stderr_file'])if(record[key])names.add(record[key]);return [...names]}
onMounted(async()=>{try{profiles.value=(await api('/profiles')).items.filter((p:any)=>p.project_id===props.projectId);profile.value=profiles.value[0]?.id||'';await refresh()}catch(e:any){error.value=e.message}})
</script>
<template>
  <h1>OpenCode 逐项复核</h1><p>静态分类、AI 答复和人工确认分别保留。打开本页不会调用模型或重新提取 TU。</p><div v-if="error" class="banner error" role="alert">{{error}}</div>
  <section class="panel"><h2>按当前证据发起复核</h2><p v-if="!canReview" class="banner warning">归档证据模式缺少本机恢复检查点或原源码，不能重新证明；已有答复与收据仍可查看。</p>
    <label>复核配置<select v-model="profile" aria-label="OpenCode复核配置"><option v-for="p in profiles" :value="p.id">{{p.project_root}} · {{p.id.slice(0,8)}}</option></select></label>
    <p>使用该配置中的 command、provider/model、Worker、超时和重试设置。发起后先验证原输入闭包；模型或工具不可用会记录“技术失败”。</p>
    <div class="actions"><button class="primary" :disabled="busy||!canReview||!profile" @click="start('review')">复核全部疑似与未知</button><button :disabled="busy||!canReview||!profile||!page?.states?.TECH_FAILED" @click="start('review-failed')">仅重试技术失败</button><button @click="emit('tasks')">任务日志与安全停止</button><button :disabled="busy" @click="refresh">刷新原始状态</button></div>
  </section>
  <section class="panel" v-if="page"><h2>原始状态与完整收据</h2><p>本扫描目标 {{page.total}} 项</p><p v-for="(count,state) in page.states">{{names[String(state)]||state}}：{{count}}</p><p v-if="!page.total">此结果没有独立 AI 账本；可在静态归档索引查看旧格式记录。未复核不能解释为安全。</p>
    <article v-for="row in page.items" :key="row.finding_id" class="history-event"><strong>{{row.finding_id}} · {{names[row.state]||row.state}}</strong><p v-if="row.status">{{names[row.status]||row.status}}</p><p v-if="row.error">{{row.failure_stage}}：{{row.error}}</p><p v-if="row.answer?.summary">{{row.answer.summary}}</p><details v-if="row.answer"><summary>原始合理化结论、证据与建议</summary><pre class="task-log">{{JSON.stringify(row.answer,null,2)}}</pre></details><p>尝试 {{row.attempt_count||0}} 次 · 格式修复 {{row.format_fix_count||0}} · 摘要修复 {{row.summary_fix_count||0}}</p><details><summary>Packet / 提示词 / 原始响应</summary><button v-for="name in receipts(row)" @click="readArtifact(name)">{{name}}</button></details></article>
    <div class="page-controls"><button :disabled="!offset" @click="offset=Math.max(0,offset-50);refresh()">上一页</button><p>显示 {{page.total?offset+1:0}}–{{Math.min(offset+50,page.total)}} / {{page.total}}</p><button :disabled="page.next_offset===null" @click="offset=page.next_offset;refresh()">下一页</button></div>
  </section><section class="panel" v-if="artifact"><h2>审计原件</h2><p class="identity">{{artifactName}} · 字节 {{artifact.offset}}–{{artifact.next_offset??artifact.total}} / {{artifact.total}}</p><pre class="task-log">{{artifact.text}}</pre><button :disabled="!artifact.offset" @click="readArtifact(artifactName)">回到开始</button><button :disabled="artifact.next_offset===null" @click="readArtifact(artifactName,artifact.next_offset)">继续完整读取</button></section>
</template>
