<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { api } from './api'
import WorkspaceDialog from './WorkspaceDialog.vue'
const props=defineProps<{title:string,start:string,root?:string,purpose?:'data',kind?:'compile_database'|'toolchain'|'project_file',multiple?:boolean}>()
const emit=defineEmits<{selected:[value:{path:string,relative:string|null}],close:[],selectedFiles:[value:{path:string,relative:string|null}[]]}>()
const state=ref<any>(null),pathText=ref(props.start),search=ref(''),error=ref(''),loading=ref(false),chosen=ref<any>(null)
const pageHistory=ref<(string|null)[]>([]),cursor=ref<string|null>(null),back=ref<string[]>([]),forward=ref<string[]>([])
const recent=ref<string[]>([]),pathInput=ref<HTMLInputElement|null>(null),list=ref<HTMLElement|null>(null)
const picked=ref<Record<string,{path:string,relative:string|null}>>({})
const pickedFiles=computed(()=>Object.values(picked.value))
const key='ecra-recent-directories'
const fileMode=computed(()=>!!props.kind)
const normalized=(p:string)=>p.replace(/\\/g,'/').replace(/\/$/,'').toLowerCase()
const allowed=(p:string)=>!props.root||normalized(p)===normalized(props.root)||normalized(p).startsWith(normalized(props.root)+'/')
const breadcrumbs=computed(()=>{
 const raw=(state.value?.path||'').replace(/\\/g,'/'),parts=raw.split('/').filter(Boolean),rows:{name:string,path:string}[]=[]
 let prefix=raw.startsWith('//')?'//':raw.startsWith('/')?'/':''
 for(const part of parts){prefix+=part+'/';if(allowed(prefix))rows.push({name:part,path:prefix})}
 return rows
})
async function read(path:string,after:string|null=null){
 if(loading.value)return false
 loading.value=true;error.value=''
 try{let result=await api('/profiles/directories','POST',{path,root:props.root,search:search.value,after,limit:50,kind:props.kind});const file=result.mode==='file'?{...result,kind:'file',selectable:true}:null;if(file)result=await api('/profiles/directories','POST',{path:file.parent,root:props.root,limit:50,kind:props.kind});state.value=result;pathText.value=result.path||'';cursor.value=after;chosen.value=file;return true}
 catch(e:any){error.value=e.message;return false}finally{loading.value=false}
}
async function navigate(path:string,record=true){
 if(loading.value)return
 const old=state.value?.path||'';search.value=''
 if(await read(path)){pageHistory.value=[];if(record&&old!==path){back.value.push(old);forward.value=[]}await focusList()}
}
async function focusList(){await nextTick();(list.value?.querySelector<HTMLButtonElement>('.directory-row:not(:disabled)')||pathInput.value)?.focus()}
async function travel(reverse=false){
 const from=reverse?forward:back,to=reverse?back:forward;if(!from.value.length||loading.value)return
 const old=state.value?.path||'',path=from.value[from.value.length-1];search.value=''
 if(await read(path)){from.value.pop();to.value.push(old);pageHistory.value=[];await focusList()}
}
async function filter(){if(await read(pathText.value))pageHistory.value=[]}
async function next(){const prior=cursor.value;if(await read(state.value.path,state.value.next_after))pageHistory.value.push(prior)}
async function previous(){if(await read(state.value.path,pageHistory.value[pageHistory.value.length-1]??null))pageHistory.value.pop()}
function choose(item:any,toggle=true){if(state.value.mode==='roots'||item.selectable){chosen.value=item;if(toggle&&props.multiple&&item.kind==='file'){if(picked.value[item.path])delete picked.value[item.path];else picked.value[item.path]={path:item.path,relative:item.relative}}}}
async function activate(item:any){if(item.kind==='file'){if(!props.multiple){choose(item);await accept()}}else await navigate(item.path)}
async function accept(){
 if(props.multiple){await acceptFiles();return}
 if(loading.value||!state.value||state.value.changed||error.value||(fileMode.value&&chosen.value?.kind!=='file'))return
 const path=chosen.value?.path||state.value.path;if(!path)return
 loading.value=true;error.value=''
 try{
  const result=await api('/profiles/directories','POST',{path,root:props.root,limit:1,kind:props.kind})
  if(result.mode!==(fileMode.value?'file':'directory')||result.changed)throw Error('目录已变化，请重新打开并核对后选择。')
  try{localStorage.setItem(key,JSON.stringify([result.parent&&fileMode.value?result.parent:result.path,...recent.value.filter(x=>x!==(fileMode.value?result.parent:result.path))].slice(0,8)))}catch{}
  emit('selected',{path:result.path,relative:result.relative})
 }catch(e:any){error.value=e.message}finally{loading.value=false}
}
async function acceptFiles(){
 if(loading.value||error.value||!pickedFiles.value.length)return
 loading.value=true;error.value=''
 try{
  const checked:{path:string,relative:string|null}[]=[]
  for(const item of pickedFiles.value){const result=await api('/profiles/directories','POST',{path:item.path,root:props.root,kind:'project_file',limit:1});if(result.mode!=='file')throw Error('选中的文件已变化，请重新选择。');checked.push({path:result.path,relative:result.relative})}
  emit('selectedFiles',checked)
 }catch(e:any){error.value=e.message}finally{loading.value=false}
}
function keyboard(event:KeyboardEvent){
 if(event.altKey&&['ArrowLeft','ArrowRight','ArrowUp'].includes(event.key)){event.preventDefault();event.stopPropagation();if(event.key==='ArrowUp'){if(state.value?.parent)navigate(state.value.parent)}else travel(event.key==='ArrowRight')}
 if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='l'){event.preventDefault();pathInput.value?.focus();pathInput.value?.select()}
}
async function rowKey(event:KeyboardEvent,index:number){
 if(event.key==='Enter'){event.preventDefault();const item=state.value.items[index];if(props.multiple&&item.kind==='file')choose(item);else activate(item);return}
 const delta=event.key==='ArrowDown'?1:event.key==='ArrowUp'?-1:0
 if(delta||['Home','End'].includes(event.key)){event.preventDefault();const i=event.key==='Home'?0:event.key==='End'?state.value.items.length-1:Math.max(0,Math.min(state.value.items.length-1,index+delta));choose(state.value.items[i],false);await nextTick();list.value?.querySelectorAll<HTMLButtonElement>('.directory-row')[i]?.focus()}
}
onMounted(()=>{try{recent.value=JSON.parse(localStorage.getItem(key)||'[]').filter((x:any)=>typeof x==='string'&&allowed(x)).slice(0,8)}catch{};read(props.start)})
</script>
<template>
 <WorkspaceDialog :title="title" @close="emit('close')" @keydown="keyboard">
  <div class="directory-browser">
   <form class="directory-path" @submit.prevent="navigate(pathText)"><div class="actions"><button type="button" aria-label="后退目录" :disabled="loading||!back.length" @click="travel()">←</button><button type="button" aria-label="前进目录" :disabled="loading||!forward.length" @click="travel(true)">→</button><button type="button" :disabled="loading||!state?.parent" @click="navigate(state.parent)">上一级</button></div><label class="sr-only" for="directory-path">要浏览的绝对目录</label><input id="directory-path" ref="pathInput" aria-label="要浏览的绝对目录" v-model="pathText" :disabled="loading"><button :disabled="loading">打开目录</button></form>
   <div class="directory-location"><button :disabled="loading" @click="navigate(root||'')">{{root?'工程根':'本机驱动器'}}</button><button v-for="crumb in breadcrumbs" :key="crumb.path" :disabled="loading" @click="navigate(crumb.path)">{{crumb.name}}</button></div>
   <div v-if="error" class="banner error" role="alert">{{error}}</div>
   <div class="directory-content">
    <nav class="directory-places" aria-label="常用目录"><strong>位置</strong><button :disabled="loading" @click="navigate(root||'')">{{root?'工程根目录':'本机驱动器'}}</button><strong v-if="recent.length">最近选择</strong><button v-for="path in recent" :key="path" :title="path" :disabled="loading" @click="navigate(path)">{{path}}</button></nav>
    <div class="directory-list-pane">
     <form class="directory-search" @submit.prevent="filter"><label class="sr-only" for="directory-search">筛选当前层目录</label><input id="directory-search" aria-label="筛选当前层目录" v-model="search" :disabled="loading||state?.mode==='roots'" placeholder="筛选当前目录，不递归搜索"><button :disabled="loading||state?.mode==='roots'">筛选目录</button></form>
     <div class="directory-column-heading">{{fileMode?'目录 / 文件名称':'目录名称'}} <span>{{loading?'读取中…':state?.total===null?'驱动器':`${state?.total??0} 项`}}</span></div>
     <div ref="list" class="directory-items" role="listbox" aria-label="当前层目录" :aria-multiselectable="multiple||undefined" :aria-busy="loading">
      <button v-for="(item,index) in state?.items" :key="item.name" class="directory-row" role="option" :aria-selected="multiple&&item.kind==='file'?!!picked[item.path]:chosen?.path===item.path" :disabled="loading||(state.mode!=='roots'&&!item.selectable)" @click="(!multiple||$event.detail<2)&&choose(item)" @dblclick="activate(item)" @keydown="rowKey($event,Number(index))"><span aria-hidden="true">{{item.kind==='file'?(multiple?(picked[item.path]?'☑':'☐'):'▤'):'▸'}}</span><span>{{item.name}}</span><small v-if="item.reason&&state.mode!=='roots'">{{item.reason}}</small></button>
      <p v-if="state&&!state.items.length">{{fileMode?'没有匹配的目录或文件。':'没有匹配的子目录。可以选择当前目录。'}}</p>
     </div>
     <div class="directory-status"><span v-if="state?.changed" class="error">目录已变化，请重新打开后选择。</span><span v-else>{{fileMode?'仅显示目录及'+(kind==='project_file'?'工程内文件（单击勾选，可跨目录选择）':kind==='compile_database'?' compile_commands.json':' .cmake 文件'):'单击选择，双击或 Enter 进入'}}</span><div v-if="pageHistory.length||state?.next_after" class="actions"><button :disabled="loading||!pageHistory.length" @click="previous">上一页目录</button><span>第 {{pageHistory.length+1}} 页</span><button :disabled="loading||!state?.next_after" @click="next">下一页目录</button></div></div>
    </div>
   </div>
  </div>
  <template #footer><div class="directory-selection"><strong>已选择：</strong><span>{{multiple?('已勾选 '+pickedFiles.length+' 个文件'):(fileMode?(chosen?.kind==='file'?chosen.path:'请选择文件'):chosen?.path||state?.path)||'请进入驱动器选择目录'}}</span><small>只读浏览；{{purpose==='data'?'确认后仍需检查并保存数据位置。':'仅登记路径，不创建文件或上传源码。'}}</small></div><div class="actions"><button v-if="multiple&&pickedFiles.length" @click="picked={}">清空勾选</button><button @click="emit('close')">取消选择</button><button class="primary" :disabled="loading||!!error||!state||state.changed||(multiple?!pickedFiles.length:fileMode?chosen?.kind!=='file':(!chosen&&state.mode!=='directory'))" @click="accept">{{multiple?'添加选中文件（'+pickedFiles.length+'）':fileMode?'使用此文件':'使用此目录'}}</button></div></template>
 </WorkspaceDialog>
</template>
<style scoped>
.directory-browser{height:100%;display:flex;flex-direction:column;gap:8px;min-height:0}.directory-path,.directory-search{display:flex;align-items:center;gap:8px;flex-shrink:0}.directory-path input,.directory-search input{margin:0;flex:1}.directory-path>button,.directory-path>.actions,.directory-search button{flex-shrink:0}.directory-location{display:flex;gap:4px;align-items:center;overflow-x:auto;flex-shrink:0}.directory-location button{padding:2px 8px;min-height:28px;white-space:nowrap}.directory-content{display:flex;gap:12px;flex:1;min-height:0}.directory-places{width:190px;flex-shrink:0;overflow:auto;border-right:1px solid #d9e1ed;padding-right:8px}.directory-places strong{padding:8px}.directory-places button{text-align:left;overflow-wrap:anywhere;border:0;padding:6px 8px}.directory-list-pane{flex:1;min-width:0;min-height:0;display:flex;flex-direction:column;gap:8px}.directory-column-heading{display:flex;justify-content:space-between;border-bottom:1px solid #d9e1ed;padding:4px 8px;color:#566579}.directory-items{flex:1;min-height:0;overflow:auto}.directory-row{width:100%;min-height:36px;display:flex;align-items:center;gap:8px;text-align:left;border:0;border-radius:2px;padding:6px 8px}.directory-row>span:nth-child(2){overflow-wrap:anywhere}.directory-row[aria-selected=true]{background:#eaf1ff;box-shadow:inset 3px 0 #245edb}.directory-row small{color:#667894}.directory-status{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px;min-height:24px;flex-shrink:0}.directory-status button{padding:2px 8px;min-height:28px}.directory-selection{min-width:0;flex:1;font-size:13px;overflow-wrap:anywhere}.directory-selection small{display:block;color:#667894}
@media(max-width:750px),(max-height:500px){.directory-places{display:none}.directory-location{display:none}.directory-status>span{display:none}.directory-path .actions{gap:2px}.directory-path .actions button{padding:4px}.directory-selection small{display:none}.directory-browser{gap:4px}}
</style>
