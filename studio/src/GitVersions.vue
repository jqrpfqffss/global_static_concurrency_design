<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from './api'
const props=defineProps<{projectRoot:string,baseRef:string,currentRef:string}>()
const emit=defineEmits<{(e:'update:baseRef',value:string):void,(e:'update:currentRef',value:string):void}>()
const state=ref<any>(null), error=ref(''), loading=ref(false), search=ref(''), offset=ref(0)
let generation=0
watch(()=>props.projectRoot,()=>{generation++;state.value=null;error.value='';offset.value=0})
const current=computed(()=>state.value?.available&&state.value.base_ref===props.baseRef&&state.value.current_ref===props.currentRef)
function choose(event:Event,side:'baseRef'|'currentRef'){const value=(event.target as HTMLInputElement).value;if(side==='baseRef')emit('update:baseRef',value);else emit('update:currentRef',value)}
async function read(at=0){
  if(loading.value)return
  const request=++generation;loading.value=true;error.value=''
  try{const result=await api('/profiles/git-versions','POST',{project_root:props.projectRoot,base_ref:props.baseRef,current_ref:props.currentRef,search:search.value,offset:at,limit:50});if(request===generation){state.value=result;offset.value=at}}
  catch(e:any){if(request===generation){state.value=null;error.value=e.message}}
  finally{loading.value=false}
}
</script>
<template>
  <section aria-label="Git 版本选择">
    <h3>扫描版本 · 固定基准 → 当前</h3>
    <button type="button" :disabled="loading||!projectRoot" @click="read(0)">{{loading?'正在读取本地 Git…':'读取并核对本地 Git 版本'}}</button>
    <p v-if="error" role="alert">{{error}}</p><p v-if="state&&!state.available" role="status">{{state.message}}</p>
    <template v-if="state?.available">
      <p class="identity">仓库：{{state.repository}}<br>当前 {{state.branch||'分离 HEAD'}} · HEAD {{state.head}}</p>
      <p>未提交：已暂存 {{state.dirty.staged}} · 工作区修改 {{state.dirty.unstaged}} · 未跟踪 {{state.dirty.untracked}} · 冲突 {{state.dirty.conflicted}}</p>
      <p>{{state.notice}}</p>
      <label>筛选分支或标签<input v-model="search" :disabled="loading" @keydown.enter.prevent="read(0)"></label><button type="button" :disabled="loading" @click="read(0)">检索版本</button>
      <p>匹配 {{state.total}} 个真实引用 · 本页 {{state.items.length}} 项</p>
      <div class="actions"><button type="button" :disabled="loading||offset===0" @click="read(Math.max(0,offset-50))">上一批版本</button><button type="button" :disabled="loading||state.next_offset===null" @click="read(state.next_offset)">下一批版本</button></div>
      <label>选择基准分支或标签<select aria-label="选择基准分支或标签" :value="baseRef" :disabled="loading" @change="choose($event,'baseRef')"><option value="">全量扫描（不比较版本）</option><option value="HEAD">HEAD</option><option v-if="baseRef&&baseRef!=='HEAD'&&!state.items.some((x:any)=>x.ref===baseRef)" :value="baseRef">{{baseRef}}（自填或不在本页）</option><option v-for="item in state.items" :key="item.ref" :value="item.ref">{{item.ref}} · {{item.object_id.slice(0,12)}}</option></select></label>
      <label>选择当前分支或标签<select aria-label="选择当前分支或标签" :value="currentRef" :disabled="loading" @change="choose($event,'currentRef')"><option value="HEAD">HEAD</option><option v-if="currentRef&&currentRef!=='HEAD'&&!state.items.some((x:any)=>x.ref===currentRef)" :value="currentRef">{{currentRef}}（自填或不在本页）</option><option v-for="item in state.items" :key="item.ref" :value="item.ref">{{item.ref}} · {{item.object_id.slice(0,12)}}</option></select></label>
    </template>
    <label>Diff 基准 ref（空表示全量）<input :value="baseRef" :disabled="loading" @input="choose($event,'baseRef')"></label>
    <label>当前 ref<input :value="currentRef" :disabled="loading" @input="choose($event,'currentRef')"></label>
    <p v-if="current" class="identity">基准提交：{{state.base_sha||'全量扫描'}}<br>当前提交：{{state.current_sha}}</p>
    <p v-else-if="state?.available" role="status">所选引用已变更，请重新核对本地 Git 版本。</p>
  </section>
</template>
