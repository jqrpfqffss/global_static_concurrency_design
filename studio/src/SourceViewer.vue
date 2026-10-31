<script setup lang="ts">
import { ref,watch } from 'vue'
import { api } from './api'
import EvidenceNode from './EvidenceNode.vue'
const props=defineProps<{scan:string,file:string,line:number}>()
const window=ref<any>(null),error=ref(''),loading=ref(false),target=ref(1)
async function load(line:number){loading.value=true;error.value='';try{window.value=await api('/scans/'+props.scan+'/source-window?file='+encodeURIComponent(props.file)+'&line='+line);target.value=line}catch(e:any){error.value=e.message}finally{loading.value=false}}
watch(()=>[props.scan,props.file,props.line],()=>load(Math.max(1,props.line||1)),{immediate:true})
</script>
<template><section aria-label="带行号的归档源码"><h3>归档代码定位 · {{file}}:{{line}}</h3><p v-if="loading" role="status">正在读取归档代码行…</p><p v-if="error" class="banner error" role="alert">{{error}}</p><template v-if="window"><p>{{window.reason}}</p><template v-if="window.available"><form class="source-jump" @submit.prevent="load(target)"><label>定位源码行<input type="number" min="1" v-model.number="target"></label><button :disabled="loading">跳转行</button><a v-if="window.ide?.available" :href="window.ide.uri">在本机 VS Code 打开</a></form><p class="muted">{{window.ide?.reason}}</p><div class="source-code" tabindex="0" aria-label="归档代码内容"><div v-for="(row,i) in window.lines" :key="i" :class="{highlight:row.selected}"><span class="source-line">{{row.line}}{{row.column>1?'续':''}}</span><code>{{row.text}}</code></div></div><p v-if="window.window_limited" class="muted">这里只显示当前行窗口。长行可能分段；下方可逐段读取完整归档文本。</p><div class="actions"><button :disabled="loading || window.start_line===1" @click="load(Math.max(1,window.start_line-30))">前一段代码</button><button :disabled="loading || !window.next_line || window.next_line<=window.start_line" @click="load(window.next_line)">后一段代码</button></div><EvidenceNode :scan="scan" :node="window.text_node" title="完整归档文本与证据引用"/></template></template></section></template>
