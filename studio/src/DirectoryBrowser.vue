<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from './api'
const props=defineProps<{title:string,start:string,root?:string}>()
const emit=defineEmits<{selected:[value:{path:string,relative:string|null}],close:[]}>()
const dialog=ref<HTMLDialogElement|null>(null),state=ref<any>(null),pathText=ref(props.start),search=ref(''),error=ref(''),loading=ref(false)
const history=ref<(string|null)[]>([]),cursor=ref<string|null>(null)
let generation=0
async function read(path:string,after:string|null=null){
  if(loading.value)return
  const request=++generation;loading.value=true;error.value=''
  try{
    const result=await api('/profiles/directories','POST',{path,root:props.root,search:search.value,after,limit:50})
    if(request===generation){state.value=result;pathText.value=result.path||'';cursor.value=after}
  }catch(e:any){if(request===generation){state.value=null;error.value=e.message}}
  finally{if(request===generation)loading.value=false}
}
function navigate(path:string){search.value='';history.value=[];cursor.value=null;read(path)}
function filter(){history.value=[];cursor.value=null;read(pathText.value)}
function next(){const after=state.value.next_after;history.value.push(cursor.value);read(pathText.value,after)}
function previous(){const after=history.value.pop()??null;read(pathText.value,after)}
onMounted(()=>{dialog.value!.showModal();read(props.start)})
onBeforeUnmount(()=>{generation++})
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="directory-dialog" :aria-label="title" @cancel.prevent="emit('close')">
      <h2>{{title}}</h2>
      <p class="muted">只读目录浏览，不上传源码、不创建文件夹。{{root?'范围选择限制在当前固件根内。':'选择后仅登记路径；构建仍须检查。'}}</p>
      <form class="directory-path" @submit.prevent="navigate(pathText)"><label>要浏览的绝对目录<input aria-label="要浏览的绝对目录" v-model="pathText" :disabled="loading"></label><button :disabled="loading">打开目录</button></form>
      <div class="actions"><button type="button" :disabled="loading" @click="navigate(root||'')">{{root?'返回工程根目录':'本机驱动器'}}</button><button type="button" :disabled="loading||!state?.parent" @click="navigate(state.parent)">返回父目录</button></div>
      <p v-if="error" class="banner error" role="alert">{{error}}</p>
      <p v-if="loading" role="status">正在读取当前层目录…</p>
      <template v-if="state">
        <p class="identity">当前：{{state.path||'本机驱动器'}}<br v-if="root"><span v-if="root">相对工程：{{state.relative}}</span></p>
        <form v-if="state.mode==='directory'" class="directory-search" @submit.prevent="filter"><label>筛选当前层目录<input aria-label="筛选当前层目录" v-model="search" :disabled="loading"></label><button :disabled="loading">筛选目录</button></form>
        <p class="muted" :class="{warning:state.changed}">{{state.notice}} <span v-if="state.total!==null">匹配 {{state.total}} 项 · 本页 {{state.items.length}} 项</span></p>
        <div class="directory-items" role="tree" aria-label="当前分支目录树">
          <div v-for="item in state.items" :key="item.name" role="treeitem" :aria-label="item.name" class="directory-item"><button type="button" :disabled="loading||(state.mode!=='roots'&&!item.selectable)" @click="navigate(item.path)">进入 {{item.name}}</button><small v-if="item.reason">{{item.reason}}</small></div>
          <p v-if="!state.items.length">当前层没有匹配的子目录。仍可选择当前目录。</p>
        </div>
        <div class="page-controls" v-if="state.mode==='directory'"><button type="button" :disabled="loading||!history.length" @click="previous">上一页目录</button><span>第 {{history.length+1}} 页</span><button type="button" :disabled="loading||!state.next_after" @click="next">下一页目录</button></div>
      </template>
      <footer><button type="button" @click="emit('close')">取消选择</button><button type="button" :disabled="loading||!state||state.mode!=='directory'||state.changed" class="primary" @click="emit('selected',{path:state.path,relative:state.relative})">使用此目录</button></footer>
    </dialog>
  </Teleport>
</template>

<style scoped>
.directory-dialog{width:min(760px,calc(100vw - 32px));max-height:calc(100dvh - 32px);border:1px solid #d9e1ed;border-radius:8px;padding:24px;color:#22344d;overflow:auto}.directory-dialog::backdrop{background:#17283d80}.directory-path,.directory-search{display:flex;gap:12px;align-items:flex-end;margin-bottom:12px}.directory-path label,.directory-search label{flex:1;min-width:0;margin:0}.directory-path button,.directory-search button{flex-shrink:0}.directory-dialog p{margin:8px 0}.directory-items{height:clamp(100px,24dvh,260px);overflow:auto;border:1px solid #d9e1ed;border-radius:4px;margin-top:12px;padding:0 12px}.directory-item{padding:8px 0;border-bottom:1px solid #e7edf4;min-width:0}.directory-item button{text-align:left;max-width:100%;overflow-wrap:anywhere}.directory-item small{display:block;color:#667894}.directory-dialog footer{display:flex;justify-content:space-between;gap:12px;border-top:1px solid #d9e1ed;padding-top:12px;margin-top:12px;position:sticky;bottom:-24px;background:white}.directory-dialog .identity{max-height:52px;overflow:auto}@media(max-height:790px){.directory-dialog{padding:16px}.directory-dialog .muted{font-size:12px}.directory-dialog h2{margin-bottom:8px}.directory-items{height:16dvh}.directory-dialog footer{bottom:-16px}}
</style>
