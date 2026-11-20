<script setup lang="ts">
import { ref,watch,onBeforeUnmount } from 'vue'
import { api,label } from './api'
import ReviewAnswer from './ReviewAnswer.vue'
const props=defineProps<{scan:string,symbol:string,revision:string,pollCycle:number}>(),emit=defineEmits<{source:[location:any]}>()
const page=ref<any>(null),offset=ref(0),loading=ref(false),error=ref('')
let request=0
async function load(){
  const mine=++request
  loading.value=true
  try{
    const value=await api(`/scans/${props.scan}/symbol-ai?`+new URLSearchParams({symbol_id:props.symbol,offset:String(offset.value),limit:'20'}))
    if(mine!==request)return
    if(value.result_revision!==props.revision){error.value='复核结论待同步。';return}
    page.value=value;error.value=''
  }catch(e:any){if(mine===request)error.value='复核结论更新失败，待同步。'+e.message}
  finally{if(mine===request)loading.value=false}
}
watch(()=>[props.scan,props.symbol,props.revision],(now,previous)=>{
  if(!previous||now[0]!==previous[0]||now[1]!==previous[1]){page.value=null;offset.value=0}
  void load()
},{immediate:true})
watch(()=>props.pollCycle,()=>{if(error.value&&!loading.value)void load()})
onBeforeUnmount(()=>request++)
const states:Record<string,string>={PENDING:'尚未复核',RUNNING:'正在复核',TECH_FAILED:'技术失败，不能判定安全',STALE:'旧结论失效'}
</script>
<template><section aria-label="当前对象的OpenCode结论"><p v-if="error" class="banner error" role="alert">{{error}}</p><p v-if="loading" role="status">正在读取当前复核结论…</p><template v-if="page"><p v-if="!page.total">本对象没有独立 OpenCode 复核项，当前判断来自静态证据与覆盖状态。</p><article v-for="row in page.items" :key="row.finding_id"><h3>{{row.state==='DONE'?label(row.status):(states[row.state]||row.state)}}</h3><ReviewAnswer v-if="row.state==='DONE'&&row.answer" :answer="row.answer" @source="emit('source',$event)"/><p v-else>本项没有当前有效的模型结论。{{row.error}}</p><details><summary>复核编号与原始执行状态</summary><p class="identity">{{row.finding_id}} · {{row.state}}</p></details></article><div v-if="page.total>20" class="actions"><button :disabled="loading||!offset" @click="offset=Math.max(0,offset-20);load()">上一段复核结论</button><button :disabled="loading||page.next_offset===null" @click="offset=page.next_offset;load()">下一段复核结论</button></div></template></section></template>
