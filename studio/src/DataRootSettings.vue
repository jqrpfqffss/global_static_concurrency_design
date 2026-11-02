<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { api } from './api'
import DirectoryBrowser from './DirectoryBrowser.vue'
import StoragePolicySettings from './StoragePolicySettings.vue'
const props=defineProps<{busy:boolean}>()
const state=ref<any>(null),path=ref(''),plan=ref<any>(null),working=ref(false),error=ref(''),notice=ref(''),repair=ref(false),browsing=ref(false)
const browseButton=ref<HTMLButtonElement|null>(null)
const origins:Record<string,string>={STARTUP_ARGUMENT:'启动参数指定',ENVIRONMENT:'ECRA_DATA_ROOT指定',GUI_DEFAULT:'GUI保存的默认目录',SYSTEM_DEFAULT:'系统默认目录',RECOVERY_DEFAULT:'启动设置恢复目录'}
async function read(){state.value=await api('/settings/data-root')}
async function check(){
 if(working.value||props.busy)return
 working.value=true;error.value='';notice.value='';plan.value=null
 try{await read();plan.value=await api('/settings/data-root/preview','POST',{path:path.value})}catch(e:any){error.value=e.message}finally{working.value=false}
}
async function save(){
 if(working.value||props.busy||!plan.value)return
 working.value=true;error.value='';notice.value=''
 try{
  const result=await api('/settings/data-root','PUT',{path:plan.value.path,plan_id:plan.value.plan_id,revision:plan.value.revision,repair:repair.value})
  notice.value=result.activation+' '+result.retention;plan.value=null;repair.value=false;await read()
 }catch(e:any){error.value=e.message;plan.value=null}finally{working.value=false}
}
async function closeBrowser(){browsing.value=false;await nextTick();browseButton.value?.focus()}
async function selected(value:{path:string,relative:string|null}){path.value=value.path;await closeBrowser()}
watch(path,()=>{plan.value=null;notice.value=''})
onMounted(async()=>{working.value=true;try{await read();path.value=state.value.selected_root||state.value.current_root}catch(e:any){error.value=e.message}finally{working.value=false}})
</script>
<template>
 <section class="panel data-root-settings" aria-label="独立数据根设置">
  <h2>独立数据根</h2>
  <template v-if="state">
   <p>当前使用：<span class="identity">{{state.current_root}}</span><br>来源：{{origins[state.source]||state.source}}</p>
   <p>下次保存的默认目录：<span class="identity">{{state.selected_root||'尚未设置，使用系统默认'}}</span></p>
   <p class="muted">{{state.precedence}}</p>
   <p v-if="state.explicit_override" class="banner warning">本次启动的参数或环境变量优先。保存默认目录不会覆盖显式启动位置。</p>
   <p v-if="state.error" role="alert" class="banner error">{{state.error}}</p>
  </template>
  <p>选择后下次启动生效。旧工程、扫描和人工记录保留在原目录；已有旧格式结果请从“数据与共享”迁移。</p>
  <label>下次启动数据目录（绝对路径）<input v-model="path" :disabled="working||busy" placeholder="例如 D:/ECRA-data"></label>
  <div class="actions"><button ref="browseButton" :disabled="working||busy" @click="browsing=true">浏览数据目录</button><button v-if="!plan" class="primary" :disabled="working||busy||!path" @click="check">检查数据目录</button></div>
  <div v-if="plan" class="data-root-plan">
   <p class="identity">{{plan.path}}</p><p>{{plan.description}}</p><p>{{plan.activation}}</p><p>{{plan.retention}}</p>
   <label v-if="state?.preference_status==='INVALID'" class="data-root-repair"><input type="checkbox" v-model="repair" :disabled="working||busy">备份损坏启动设置后保存新目录</label>
   <button class="primary" :disabled="working||busy||(state?.preference_status==='INVALID'&&!repair)" @click="save">保存为下次启动目录</button>
  </div>
  <p v-if="working" role="status">正在核对数据目录与启动设置…</p>
  <p v-if="error" role="alert" class="banner error">数据目录未保存：{{error}}</p>
  <p v-if="notice" role="status" class="banner">{{notice}}</p>
  <DirectoryBrowser v-if="browsing" title="选择下次启动数据目录" purpose="data" :start="path" @selected="selected" @close="closeBrowser"/>
  <StoragePolicySettings :busy="busy||working"/>
 </section>
</template>
<style scoped>
.data-root-settings .identity{overflow-wrap:anywhere}.data-root-plan{margin-top:16px;padding:16px;border:1px solid #d9e1ed;border-radius:4px}.data-root-repair{display:flex;gap:8px;align-items:flex-start}.data-root-repair input{width:20px;height:20px;flex-shrink:0}
</style>
