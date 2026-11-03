<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api, download, label } from './api'
import './history.css'
import HistoryComparison from './HistoryComparison.vue'
const props=defineProps<{dataRoot:string,busy:boolean}>()
const emit=defineEmits<{open:[id:string],continue:[id:string],symbol:[scan:string,symbol:string]}>()
const defaults=()=>({project:'',profile:'',core:'',git:'',scan_mode:'',state:'',date_from:'',date_to:''})
const filters=ref(defaults()),offset=ref(0),page=ref<any>(null),working=ref(false),error=ref(''),notice=ref('')
const expanded=ref(false)
const baseline=ref(''),comparison=ref<{base:string,current:string}|null>(null)
const disabled=computed(()=>working.value||props.busy)
const key='ecra-history:'+props.dataRoot
let needsInitial=true
function remember(){try{sessionStorage.setItem(key,JSON.stringify({filters:filters.value,offset:offset.value,baseline:baseline.value,comparison:comparison.value}))}catch{notice.value='浏览器不允许保存检索位置；当前检索仍可使用。'}}
function setBaseline(id:string){if(disabled.value)return;baseline.value=id;comparison.value=null;remember()}
function compare(id:string){if(disabled.value||!baseline.value||baseline.value===id)return;comparison.value={base:baseline.value,current:id};remember()}
function closeComparison(){comparison.value=null;remember()}
async function load(){
 if(disabled.value)return
 needsInitial=false
 working.value=true;error.value='';notice.value='';page.value=null
 try{
  const params=new URLSearchParams({...filters.value,offset:String(offset.value),limit:'20'})
  page.value=await api('/history?'+params);offset.value=page.value.offset;remember()
 }catch(e:any){error.value=e.message}finally{working.value=false}
}
async function search(){offset.value=0;await load()}
async function clear(){filters.value=defaults();expanded.value=false;await search()}
async function move(delta:number){offset.value=Math.max(0,offset.value+delta*20);await load()}
async function exportRow(id:string,kind:string){
 if(disabled.value)return
 working.value=true;error.value='';notice.value=''
 try{
  const result=await api('/scans/'+encodeURIComponent(id)+'/export','POST',{kind})
  await download(result.download,result.filename);notice.value='已导出批次 '+id+' 的'+(kind==='full'?'标准完整包':'人工确认增量')+'。'
 }catch(e:any){error.value=e.message}finally{working.value=false}
}
function mode(value:string){return value==='FULL'?'全量':value==='DIFF'?'Git Diff':'模式未记录'}
function git(item:any){const identity=item.identity,pin=identity.diff;return pin?`${pin.base_ref||'未记录'} → ${pin.current_ref||'未记录'}\n${pin.base_sha||'未记录'} → ${pin.head_sha||'未记录'}`:identity.recorded_git_commit&&identity.recorded_git_commit!=='unknown'?identity.recorded_git_commit:'Git版本未记录'}
watch(()=>props.busy,value=>{if(!value&&needsInitial)load()})
onMounted(async()=>{
 try{
  const saved=JSON.parse(sessionStorage.getItem(key)||'null')
  if(saved){for(const name of Object.keys(defaults()) as (keyof ReturnType<typeof defaults>)[])if(typeof saved.filters?.[name]==='string')filters.value[name]=saved.filters[name];if(Number.isSafeInteger(saved.offset)&&saved.offset>=0)offset.value=saved.offset;expanded.value=Object.entries(filters.value).some(([name,value])=>!['project','profile'].includes(name)&&!!value);if(typeof saved.baseline==='string')baseline.value=saved.baseline;if(typeof saved.comparison?.base==='string'&&typeof saved.comparison?.current==='string')comparison.value=saved.comparison}
 }catch{notice.value='已忽略无法读取的浏览器检索位置；归档数据仍保留。'}
 await load()
})
</script>
<template>
 <section class="history-center">
  <h1>历史与对比</h1><p>检索保存的静态快照；发布状态不表示当前源码有效。“本轮未观察到”不等于已修复。</p>
  <HistoryComparison v-if="comparison" :key="comparison.base+':'+comparison.current" :base="comparison.base" :current="comparison.current" :busy="disabled" @close="closeComparison" @symbol="(id,symbol)=>emit('symbol',id,symbol)" />
  <template v-else>
  <p v-if="baseline" class="banner" role="status">当前对比基准：<span class="identity">{{baseline}}</span>。请选择另一归档的“与基准对比”。<button :disabled="disabled" @click="setBaseline('')">清除基准</button></p>
  <form class="panel" aria-label="历史检索" @submit.prevent="search">
   <div class="history-basic-filters">
    <label>工程名称 / ID<input v-model="filters.project" :disabled="disabled" maxlength="256" placeholder="字面包含"></label>
    <label>配置 / 目标 / 变体<input v-model="filters.profile" :disabled="disabled" maxlength="256" placeholder="例如 Release"></label>
    <button type="submit" class="primary" :disabled="disabled">查询历史</button><button type="button" :disabled="disabled" @click="clear">清空筛选</button>
   </div>
   <details :open="expanded" @toggle="expanded=($event.target as HTMLDetailsElement).open" class="history-advanced"><summary>核心、Git、模式、状态与日期筛选</summary><div class="history-filters">
    <label>核心声明<input v-model="filters.core" :disabled="disabled" maxlength="256" placeholder="只检索归档已记录声明"></label>
    <label>Git ref / 提交<input v-model="filters.git" :disabled="disabled" maxlength="256" placeholder="保留真实比较方向"></label>
    <label>历史扫描模式<select aria-label="历史扫描模式" v-model="filters.scan_mode" :disabled="disabled"><option value="">全部模式</option><option value="FULL">全量</option><option value="DIFF">Git Diff</option><option value="UNKNOWN">未记录</option></select></label>
    <label>归档发布状态<select aria-label="归档发布状态" v-model="filters.state" :disabled="disabled"><option value="">全部发布状态</option><option value="STATIC_VALIDATED">发布者记录：静态已校验</option><option value="UNVERIFIED">来源尚未验证</option><option value="LEGACY_READ_ONLY">旧格式只读</option><option value="FAILED">读取失败 / 损坏</option></select></label>
    <label>开始日期（UTC）<input type="date" v-model="filters.date_from" :disabled="disabled"></label>
    <label>结束日期（UTC）<input type="date" v-model="filters.date_to" :disabled="disabled"></label>
   </div><p class="muted">文本按字面包含匹配，区分大小写；日期包含两端。缺少时区或日期的归档不匹配日期筛选，不以文件修改时间代替。</p></details>
  </form>
  <p v-if="working" role="status">正在读取或导出真实归档，请稍候…</p>
  <p v-if="error" role="alert" class="banner error">历史操作未完成：{{error}}。原归档仍保留；请核对后重试。</p>
  <p v-if="notice" role="status" class="banner">{{notice}}</p>
  <template v-if="page">
   <div class="history-pagination"><p class="history-count" role="status">匹配 {{page.total}} 个归档；显示 {{page.total?page.offset+1:0}}–{{Math.min(page.offset+page.limit,page.total)}}。最新日期在前，未记录日期在末。</p><nav class="page-controls" aria-label="历史分页"><button :disabled="disabled||page.offset===0" @click="move(-1)">上一页</button><button :disabled="disabled||page.next_offset===null" @click="move(1)">下一页</button></nav></div>
   <section class="panel history-records" aria-label="历史归档列表" tabindex="0">
    <article v-for="item in page.items" :key="item.scan_id" class="history-row" :aria-label="'归档 '+item.scan_id">
     <div class="history-info">
      <strong>{{item.identity.project_name||item.project_id||'工程身份未记录'}}</strong><p class="identity">批次 {{item.scan_id}}</p>
      <p>配置 {{item.profile_id||'未记录'}} · 目标 {{item.identity.configured_target||'未记录'}} · 变体 {{item.identity.build_variant||'未记录'}} · 核心声明 {{item.identity.project_core||'未记录'}}</p>
      <p>{{mode(item.scan_mode)}} · {{item.mode==='LOCAL_SNAPSHOT'?'本机扫描快照':'归档证据模式'}} · {{label(item.state)}}</p>
      <p>静态覆盖：{{item.identity.analysis_status==='INCOMPLETE'?'部分覆盖（INCOMPLETE）':item.identity.analysis_status?label(item.identity.analysis_status):'未记录'}}</p>
      <p class="history-git">{{git(item)}}</p><p>{{item.date_source||'扫描时间'}}：{{item.recorded_at_utc||'未记录可用UTC日期'}}</p>
      <p v-if="item.error" class="banner error">读取失败：{{item.error}}</p>
      <p v-if="item.can_open&&!item.can_confirm" class="banner warning">缺证据旧原件模式；可查看原件，不生成可信人工确认。</p>
     </div>
     <div class="history-actions">
      <button :disabled="disabled||!item.can_open" @click="emit('open',item.scan_id)">打开结果</button>
      <button :disabled="disabled||!item.can_confirm" @click="setBaseline(item.scan_id)">{{baseline===item.scan_id?'已选为对比基准':'设为对比基准'}}</button>
      <button :disabled="disabled||!item.can_confirm||!baseline||baseline===item.scan_id" @click="compare(item.scan_id)">与基准对比</button>
      <button :disabled="disabled||!item.can_confirm" @click="emit('continue',item.scan_id)">继续人工确认</button>
      <button :disabled="disabled||!item.can_open" @click="exportRow(item.scan_id,'full')">导出标准完整包</button>
      <button :disabled="disabled||!item.can_confirm" @click="exportRow(item.scan_id,'delta')">导出人工确认增量</button>
     </div>
    </article>
    <p v-if="!page.total">没有匹配归档。可清空筛选；尚未扫描时请接入工程，或从数据与共享导入结果包。</p>
   </section>
  </template>
  <p class="muted">历史对象对比按归档canonical身份和完整事实/报告指纹保守关联；不替代重新扫描和源码核对。导出包可能包含敏感源码与备注，请按团队规则分享。</p>
  </template>
 </section>
</template>
