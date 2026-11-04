<script setup lang="ts">
import { onMounted,onUnmounted,ref,watch } from 'vue'
import { api } from './api'
import DirectoryBrowser from './DirectoryBrowser.vue'
const props=defineProps<{currentRoot:string,busy:boolean}>()
const source=ref(props.currentRoot),target=ref(''),restore=ref(false),plan=ref<any>(null),job=ref<any>(null),history=ref<any[]>([]),working=ref(false),error=ref(''),browser=ref<'source'|'target'|null>(null)
let timer:any=null,alive=true
const names:Record<string,string>={RUNNING:'准备复制',COPYING:'复制并校验文件',VALIDATING:'校验数据库与人工历史',PUBLISHING:'发布已校验副本',COMPLETE:'复制完成',FAILED:'失败，原数据保留',INTERRUPTED:'已中断，可重新校验后恢复'}
function state(value:string){return names[value]||'未识别状态：'+value}
function active(value:any){return value&&['RUNNING','COPYING','VALIDATING','PUBLISHING'].includes(value.state)}
function bytes(value:number){return new Intl.NumberFormat('zh-CN').format(value||0)+' 字节'}
async function read(){history.value=(await api('/data-transfers')).items;if(!job.value&&history.value.length)job.value=history.value[0]}
async function check(){working.value=true;error.value='';plan.value=null;try{plan.value=await api('/data-transfers/preview','POST',{source:restore.value?source.value:props.currentRoot,target:target.value})}catch(e:any){error.value=e.message}finally{working.value=false}}
async function start(){if(!plan.value)return;working.value=true;error.value='';try{const value=await api('/data-transfers','POST',{source:plan.value.source,target:plan.value.target,revision:plan.value.revision});job.value=await api('/data-transfers/'+value.id);plan.value=null}catch(e:any){error.value=e.message}finally{working.value=false}}
async function resume(value:any){working.value=true;error.value='';try{const result=await api('/data-transfers/'+encodeURIComponent(value.id)+'/resume','POST',{});job.value=await api('/data-transfers/'+result.id)}catch(e:any){error.value=e.message}finally{working.value=false}}
async function poll(){if(!alive)return;try{if(active(job.value)){job.value=await api('/data-transfers/'+job.value.id);if(!active(job.value))await read()}}catch(e:any){error.value=e.message}finally{if(alive)timer=setTimeout(poll,800)}}
watch([source,target,restore],()=>{plan.value=null})
onMounted(async()=>{try{await read()}catch(e:any){error.value=e.message}void poll()})
onUnmounted(()=>{alive=false;if(timer)clearTimeout(timer)})
</script>
<template>
 <section class="panel root-transfer" aria-label="整套数据复制与恢复">
  <h2>整套数据复制与恢复</h2>
  <p>复制全部工程、扫描、证据、人工记录与历史。复制期间来源目录暂停其他操作；成功后才发布新目录，原目录始终保留。</p>
  <label class="restore-option"><input type="checkbox" v-model="restore" :disabled="working||busy||active(job)">从另一完整Studio数据目录恢复副本</label>
  <template v-if="restore"><label>来源Studio数据根<input v-model="source" :disabled="working||busy||active(job)"></label><button :disabled="working||busy||active(job)" @click="browser='source'">浏览来源目录</button></template>
  <p v-else class="identity">来源：{{currentRoot}}</p>
  <label>整套复制的目标空目录<input v-model="target" :disabled="working||busy||active(job)" placeholder="例如 D:/ECRA-data-backup"></label>
  <div class="actions"><button :disabled="working||busy||active(job)" @click="browser='target'">浏览复制目标</button><button :disabled="working||busy||active(job)||!target" @click="check">检查整套复制计划</button></div>
  <div v-if="plan" class="banner"><p class="identity">{{plan.source}} → {{plan.target}}</p><p>文件 {{plan.files}} 个 · {{bytes(plan.bytes)}}。{{plan.retention}}</p><p>{{plan.activation}}</p><button class="primary" :disabled="working||busy||active(job)" @click="start">开始完整复制并校验</button></div>
  <p v-if="working" role="status">正在核对整套复制操作…</p>
  <section v-if="job" class="banner" aria-live="polite"><h3>{{state(job.state)}}</h3><p class="identity">{{job.source}} → {{job.target}}</p>
   <p v-if="job.total_files!==undefined">已校验 {{job.copied_files}} / {{job.total_files}} 个文件 · {{bytes(job.copied_bytes)}} / {{bytes(job.total_bytes)}}；恢复复用 {{job.reused_files||0}} 个。</p>
   <p v-if="job.state==='VALIDATING'">正在校验完整数据库、人工历史和活动配置路径；所需时间未知。</p>
   <p v-if="job.state==='COMPLETE'">新副本已发布。请在上方“独立数据根”中选择此目标并保存，关闭软件后重新启动。旧构建与Git工作树完整保留为历史，后续操作会重新校验输入。</p>
   <p v-if="job.error" role="alert">{{job.error}}</p><button v-if="['FAILED','INTERRUPTED','PUBLISHING'].includes(job.state)&&job.journal" :disabled="working||busy" @click="resume(job)">重新校验并恢复复制</button>
  </section>
  <p v-if="error" class="banner error" role="alert">整套复制未完成：{{error}}</p>
  <details v-if="history.length"><summary>复制与恢复历史（{{history.length}} 项）</summary><article v-for="item in history" :key="item.id"><p>{{item.started}} · {{state(item.state)}}</p><p class="identity">{{item.source}} → {{item.target}}</p><button @click="job=item" :disabled="active(job)||working">查看此操作</button></article></details>
  <DirectoryBrowser v-if="browser" :title="browser==='source'?'选择完整Studio来源目录':'选择复制目标空目录'" purpose="data" :start="browser==='source'?source:target||currentRoot" @selected="value=>{if(browser==='source')source=value.path;else target=value.path;browser=null}" @close="browser=null"/>
 </section>
</template>
<style scoped>
.root-transfer{margin-top:16px}.root-transfer .identity{overflow-wrap:anywhere}.restore-option{display:flex;gap:8px;align-items:center}.restore-option input{width:20px;height:20px;flex-shrink:0}.root-transfer article{padding:8px 0;border-top:1px solid #d9e1ed}
</style>
