<script setup lang="ts">
import { ref } from 'vue'
import { api } from './api'
import EvidenceNode from './EvidenceNode.vue'
const props=defineProps<{scan:string, id:string, definitions?:any[], direction:string, ancestors:string[]}>()
const open=ref(false), page=ref<any>(null), error=ref(''), busy=ref(false)
function name(){const summary=props.definitions?.[0]?.summary;return summary?.qualified_name||summary?.name||props.id}
async function load(offset=0){busy.value=true;error.value='';try{page.value=await api(`/scans/${props.scan}/call-neighbors?function_id=${encodeURIComponent(props.id)}&direction=${props.direction}&offset=${offset}`)}catch(e:any){error.value=e.message}finally{busy.value=false}}
async function toggle(){open.value=!open.value;if(open.value&&!page.value)await load()}
</script>
<template>
  <div class="call-node"><button class="call-function" :disabled="busy||ancestors.includes(id)" :aria-expanded="open" @click="toggle">{{open?'▾':'▸'}} {{name()}}</button><span v-if="ancestors.includes(id)" class="tag">递归回边，关系完整保留</span>
    <p class="muted" v-for="definition in definitions">{{definition.summary?.file}}:{{definition.summary?.line}}</p><p v-if="error" class="banner error">{{error}}</p>
    <div v-if="open&&page" class="call-children"><p>{{direction==='upstream'?'调用此函数的边':'此函数调用的边'}}：{{page.total}} 条；当前显示 {{page.total?page.offset+1:0}}–{{Math.min(page.offset+page.items.length,page.total)}}。同一调用者的多处调用仍分别保留。</p><p v-if="!page.total">没有已恢复的该方向调用边。外部入口或未知调用请核对上下文与覆盖证据。</p>
      <article v-for="edge in page.items" :key="edge.ordinal"><p class="muted">{{direction==='upstream'?'调用者 → 当前函数':'当前函数 → 被调用者'}} · {{edge.summary?.file}}:{{edge.summary?.line}}</p><CallNode v-if="edge.neighbor_id" :scan="scan" :id="edge.neighbor_id" :definitions="edge.definitions" :direction="direction" :ancestors="[...ancestors,id]"/><EvidenceNode :scan="scan" :node="edge.node" title="调用边完整证据"/></article>
      <button :disabled="busy||!page.offset" @click="load(Math.max(0,page.offset-50))">上一段调用边</button><button :disabled="busy||page.next_offset===null" @click="load(page.next_offset)">继续完整调用边</button>
    </div>
  </div>
</template>
