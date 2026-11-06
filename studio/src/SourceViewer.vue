<script setup lang="ts">
import { nextTick,onBeforeUnmount,ref,watch } from 'vue'
import { api } from './api'
import EvidenceNode from './EvidenceNode.vue'
const props=defineProps<{scan:string,file:string,line:number}>()
const window=ref<any>(null),error=ref(''),loading=ref(false),target=ref(1)
const code=ref<HTMLElement|null>(null)
let request=0
function revealTarget(){
  const row=code.value?.querySelector<HTMLElement>('.highlight')
  if(!row||!code.value)return
  for(const pane of [code.value,code.value.closest<HTMLElement>('.detail-evidence')]){
    if(!pane||pane.scrollHeight<=pane.clientHeight)continue
    const item=row.getBoundingClientRect(),bounds=pane.getBoundingClientRect()
    pane.scrollTop+=item.top-bounds.top-pane.clientTop-Math.max(0,(pane.clientHeight-Math.min(item.height,pane.clientHeight))/2)
  }
}
async function load(line:number){
  const mine=++request;loading.value=true;error.value=''
  try{const value=await api('/scans/'+props.scan+'/source-window?file='+encodeURIComponent(props.file)+'&line='+line);if(mine===request){window.value=value;target.value=line}}
  catch(e:any){if(mine===request)error.value=e.message}
  finally{if(mine===request){loading.value=false;await nextTick();if(mine===request)revealTarget()}}
}
watch(()=>[props.scan,props.file,props.line],(value,previous)=>{if(!previous||value[0]!==previous[0]||value[1]!==previous[1])window.value=null;load(Math.max(1,props.line||1))},{immediate:true})
onBeforeUnmount(()=>{request++})
</script>
<template><section aria-label="带行号的归档源码"><h3>归档代码定位 · {{file}}:{{line}}</h3><p v-if="loading" role="status">正在读取归档代码行…</p><p v-if="error" class="banner error" role="alert">{{error}}</p><template v-if="window"><p>{{window.reason}}</p><template v-if="window.available"><form class="source-jump" @submit.prevent="load(target)"><label>定位源码行<input type="number" min="1" v-model.number="target"></label><button :disabled="loading">跳转行</button><a v-if="window.ide?.available" :href="window.ide.uri">在本机 VS Code 打开</a></form><p class="muted">{{window.ide?.reason}}</p><div ref="code" class="source-code" tabindex="0" aria-label="归档代码内容"><div v-for="(row,i) in window.lines" :key="i" :class="{highlight:row.selected}"><span class="source-line">{{row.line}}{{row.column>1?'续':''}}</span><code>{{row.text}}</code></div></div><p v-if="window.window_limited" class="muted">这里只显示当前行窗口。长行可能分段；下方可逐段读取完整归档文本。</p><div class="actions"><button :disabled="loading || window.start_line===1" @click="load(Math.max(1,window.start_line-30))">前一段代码</button><button :disabled="loading || !window.next_line || window.next_line<=window.start_line" @click="load(window.next_line)">后一段代码</button></div><EvidenceNode :scan="scan" :node="window.text_node" title="完整归档文本与证据引用"/></template></template></section></template>
