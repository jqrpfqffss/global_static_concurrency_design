<script lang="ts">
import { api } from './api'
import { createEvidenceNames } from './evidenceNames'
const resolveName=createEvidenceNames(api)
</script>
<script setup lang="ts">
import { onBeforeUnmount,ref,watch } from 'vue'
import type { EvidenceName,IdentityKind } from './evidenceNames'
const props=defineProps<{scan:string,id?:string,kind:IdentityKind}>()
const value=ref<EvidenceName|null>(null),error=ref(''),loading=ref(false)
let generation=0
async function load(){
  const mine=++generation;value.value=null;error.value='';loading.value=true
  try{if(props.id){const result=await resolveName(props.scan,props.kind,props.id);if(mine===generation)value.value=result}}
  catch(e:any){if(mine===generation)error.value='名称读取失败：'+e.message}
  finally{if(mine===generation)loading.value=false}
}
watch(()=>[props.scan,props.id,props.kind],load,{immediate:true})
onBeforeUnmount(()=>{generation++})
</script>
<template><span class="evidence-identity"><strong :title="value?.detail">{{value?.name||(loading?'正在读取名称…':kind==='context'?'执行上下文待核实':'函数名称待核实')}}</strong><small v-if="id">原始身份：{{id}}</small><small v-else>归档未记录身份</small><span v-if="error" role="status">{{error}} <button @click="load">重试名称</button></span></span></template>
<style scoped>
.evidence-identity{display:inline-block;vertical-align:top;max-width:100%;overflow-wrap:anywhere}.evidence-identity small{display:block;color:#566579;font-size:11px}.evidence-identity button{font-size:12px;padding:2px 6px}
</style>
