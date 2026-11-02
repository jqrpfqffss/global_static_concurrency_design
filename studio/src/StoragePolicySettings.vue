<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from './api'
defineProps<{busy:boolean}>()
const state=ref<any>(null),mode=ref('auto'),working=ref(false),error=ref(''),notice=ref(''),repair=ref(false),expanded=ref(false)
const names:Record<string,string>={auto:'自动节省存储空间',off:'保持普通文件'}
async function read(){state.value=await api('/storage/policy');mode.value=state.value.mode||'auto';if(!state.value.valid)expanded.value=true}
function toggle(event:Event){expanded.value=(event.currentTarget as HTMLDetailsElement).open}
async function refresh(){working.value=true;error.value='';notice.value='';try{await read()}catch(e:any){error.value=e.message}finally{working.value=false}}
async function save(){
 if(working.value||!state.value)return
 working.value=true;error.value='';notice.value=''
 try{
  const selected=mode.value,result=await api('/storage/policy','POST',{mode:selected,revision:state.value.revision,repair:repair.value})
  if(!result.saved)throw new Error('服务未返回保存收据，请重新读取')
  await read()
  if(state.value.mode!==selected||state.value.revision!==result.revision)throw new Error('设置已由另一窗口改变，请重新核对')
  repair.value=false;notice.value=result.activation
 }catch(e:any){error.value=e.message}finally{working.value=false}
}
onMounted(refresh)
</script>
<template>
 <details class="storage-policy-settings" :open="expanded" @toggle="toggle">
  <summary>新扫描空间策略：{{state ? state.valid ? names[state.mode]||'未识别策略' : '设置异常' : '正在读取'}}</summary>
  <p>应用于下一次扫描，空间整理可能增加收尾时间。自动策略仅无损压缩本次新建的封闭文件；不支持的文件系统会明确跳过。已有归档和人工记录保留。</p>
  <p v-if="state?.error" role="alert" class="banner warning">{{state.error}}</p>
  <label>新扫描空间策略<select v-model="mode" aria-label="新扫描空间策略" :disabled="busy||working"><option value="auto">自动节省存储空间</option><option value="off">保持普通文件</option></select></label>
  <label v-if="state?.valid===false" class="repair-policy"><input type="checkbox" v-model="repair" :disabled="busy||working">备份损坏空间设置后保存</label>
  <div class="actions"><button :disabled="busy||working||!state||(!state.valid&&!repair)" @click="save">保存空间策略</button><button :disabled="busy||working" @click="refresh">重新读取空间策略</button></div>
  <p v-if="working" role="status">正在读取或保存空间策略…</p><p v-if="error" role="alert" class="banner error">空间策略未保存：{{error}}</p><p v-if="notice" role="status" class="banner">{{notice}}</p>
 </details>
</template>
<style scoped>
.storage-policy-settings{margin-top:24px;border-top:1px solid #d9e1ed;padding-top:16px}.storage-policy-settings summary{cursor:pointer;font-weight:600}.storage-policy-settings .repair-policy{display:flex;gap:8px;align-items:flex-start}.repair-policy input{width:20px;height:20px;flex-shrink:0}
</style>
