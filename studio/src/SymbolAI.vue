<script setup lang="ts">
import { ref,watch,onBeforeUnmount } from 'vue'
import { api,label } from './api'
import ReviewAnswer from './ReviewAnswer.vue'
const props=defineProps<{scan:string,symbol:string,revision:string}>(),emit=defineEmits<{source:[location:any]}>()
const page=ref<any>(null),offset=ref(0),loading=ref(false),error=ref('')
let request=0
async function load(){const mine=++request;loading.value=true;error.value='';try{const value=await api(`/scans/${props.scan}/symbol-ai?`+new URLSearchParams({symbol_id:props.symbol,offset:String(offset.value),limit:'20'}));if(mine===request)page.value=value}catch(e:any){if(mine===request)error.value=e.message}finally{if(mine===request)loading.value=false}}
watch(()=>[props.scan,props.symbol,props.revision],()=>{offset.value=0;load()},{immediate:true})
onBeforeUnmount(()=>request++)
const states:Record<string,string>={PENDING:'尚未复核',RUNNING:'正在复核',TECH_FAILED:'技术失败，不能判定安全',STALE:'旧结论失效'}
</script>
<template><section aria-label="当前对象的OpenCode结论"><p v-if="error" class="banner error" role="alert">{{error}}</p><p v-if="loading" role="status">正在读取当前复核结论…</p><template v-if="page"><p v-if="!page.total">本对象没有独立 OpenCode 复核项，当前判断来自静态证据与覆盖状态。</p><article v-for="row in page.items" :key="row.finding_id"><h3>{{row.state==='DONE'?label(row.status):(states[row.state]||row.state)}}</h3><ReviewAnswer v-if="row.state==='DONE'&&row.answer" :answer="row.answer" @source="emit('source',$event)"/><p v-else>本项没有当前有效的模型结论。{{row.error}}</p><details><summary>复核编号与原始执行状态</summary><p class="identity">{{row.finding_id}} · {{row.state}}</p></details></article><div v-if="page.total>20" class="actions"><button :disabled="loading||!offset" @click="offset=Math.max(0,offset-20);load()">上一段复核结论</button><button :disabled="loading||page.next_offset===null" @click="offset=page.next_offset;load()">下一段复核结论</button></div></template></section></template>
