<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api, label } from './api'
import WorkspaceDialog from './WorkspaceDialog.vue'
const identitiesOpen=ref(false)
const props=defineProps<{base:string,current:string,busy:boolean}>()
const emit=defineEmits<{close:[],symbol:[scan:string,symbol:string]}>()
const page=ref<any>(null),working=ref(false),error=ref(''),search=ref(''),change=ref('')
const disabled=computed(()=>working.value||props.busy)
const kinds=[['ADDED','本轮新增'],['NOT_OBSERVED','本轮未观察到'],['EVIDENCE_CHANGED','证据变化需核对'],['EVIDENCE_IDENTICAL','归档证据指纹相同']]
let needsInitial=true
function changeLabel(value:string){return kinds.find(row=>row[0]===value)?.[1]||'未识别变化：'+value}
async function load(offset=0){
 if(disabled.value)return
 needsInitial=false
 working.value=true;error.value=''
 try{
  const next=await api('/history/compare?'+new URLSearchParams({base:props.base,current:props.current,search:search.value,change:change.value,offset:String(offset),limit:'50'}))
  page.value=next
 }catch(e:any){error.value=e.message}finally{working.value=false}
}
onMounted(()=>load())
watch(()=>props.busy,value=>{if(!value&&needsInitial)load()})
</script>
<template>
 <section class="history-comparison" aria-label="历史对象对比">
  <div class="comparison-heading"><h2>基准 → 当前</h2><button :disabled="disabled" @click="emit('close')">返回历史检索</button></div>
  <p class="identity">基准批次 {{base}} → 当前批次 {{current}}</p>
  <p v-if="working" role="status">正在读取真实归档对比，保留上一页直到读取完成…</p>
  <p v-if="error" role="alert" class="banner error">对比未完成：{{error}}。原归档保留。<button :disabled="disabled" @click="load(page?.offset||0)">重试对比</button></p>
  <template v-if="page">
   <button class="comparison-identity-button" @click="identitiesOpen=true">查看双方构建身份与完整根摘要</button><WorkspaceDialog v-if="identitiesOpen" title="双方构建身份与完整根摘要" @close="identitiesOpen=false">
    <div class="comparison-sides"><section v-for="[key,title] in [['before','基准'],['after','当前']]" :key="key"><h3>{{title}} · {{page[key].identity.project_name||page[key].binding.project_id}}</h3><p>配置 {{page[key].binding.profile_id||'未记录'}} · 目标 {{page[key].identity.configured_target||'未记录'}} · 变体 {{page[key].identity.build_variant||'未记录'}}</p><p>核心 {{page[key].identity.project_core||'未记录'}} · 覆盖 {{page[key].identity.analysis_status?label(page[key].identity.analysis_status):'未记录'}}</p><p>Git {{page[key].identity.recorded_git_commit||'未记录'}}</p><p v-if="page[key].identity.diff">归档Diff：{{page[key].identity.diff.base_ref}} → {{page[key].identity.diff.current_ref}}</p></section></div>
    <div v-for="root in page.roots" :key="root.name" class="comparison-root"><strong>{{root.name}}：{{root.identical?'完整根指纹相同':'根指纹不同或缺失'}}</strong><p>基准 {{root.before?.hash||'未归档'}}</p><p>当前 {{root.after?.hash||'未归档'}}</p></div>
   </WorkspaceDialog>
   <p v-if="!page.profile_equal" class="banner warning">双方配置身份不同；请核对目标、宏、核心和构建闭包，不能将不同变体的变化直接当作修复结论。</p>
   <p class="banner warning">{{page.note}} 完整事实或报告任一变化时，所有共有对象均保守提示需核对。</p>
   <p class="comparison-counts"><span v-for="[key,title] in kinds" :key="key">{{title}} {{page.counts[key]||0}}； </span></p>
  </template>
  <form class="comparison-filters" aria-label="对比对象检索" @submit.prevent="load(0)">
   <label>对比变量 / canonical 身份<input v-model="search" maxlength="256" :disabled="disabled" placeholder="字面包含，区分大小写"></label>
   <label>对象变化类型<select v-model="change" :disabled="disabled"><option value="">全部变化类型</option><option v-for="[key,title] in kinds" :key="key" :value="key">{{title}}</option></select></label>
   <button type="submit" :disabled="disabled">查询对比</button>
  </form>
  <template v-if="page">
   <div class="history-pagination"><p role="status">匹配 {{page.total}} 个对象；显示 {{page.total?page.offset+1:0}}–{{Math.min(page.offset+page.limit,page.total)}}。</p><nav class="page-controls" aria-label="对象对比分页"><button :disabled="disabled||page.offset===0" @click="load(Math.max(0,page.offset-page.limit))">上一页</button><button :disabled="disabled||page.next_offset===null" @click="load(page.next_offset)">下一页</button></nav></div>
   <section class="panel comparison-rows" aria-label="对比对象列表" tabindex="0">
    <table class="data-table"><thead><tr><th>对象 / 变化</th><th>基准</th><th>当前</th></tr></thead><tbody><tr v-for="row in page.items" :key="row.symbol_id" :aria-label="'对比对象 '+row.symbol_id"><td><strong>{{row.after_name||row.before_name}}</strong><small class="identity">{{row.symbol_id}}</small><span>{{changeLabel(row.change)}}</span></td><td>{{row.before_node===null?'本批次未观察到':label(row.before_classification)}}<small>{{row.before_file||'定义未记录'}}{{row.before_line?':'+row.before_line:''}}</small><button :disabled="disabled||row.before_node===null" @click="emit('symbol',base,row.symbol_id)">查看基准证据</button></td><td>{{row.after_node===null?'本批次未观察到':label(row.after_classification)}}<small>{{row.after_file||'定义未记录'}}{{row.after_line?':'+row.after_line:''}}</small><button :disabled="disabled||row.after_node===null" @click="emit('symbol',current,row.symbol_id)">查看当前证据</button></td></tr></tbody></table><p v-if="!page.total">没有匹配对象；可清空检索或选择其他变化类型。</p>
   </section>
  </template>
 </section>
</template>
