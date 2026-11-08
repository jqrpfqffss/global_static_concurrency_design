<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from './api'
import EvidenceNode from './EvidenceNode.vue'
const props=defineProps<{scan:string, id:string, definitions?:any[], direction:string, ancestors:string[]}>()
const open=ref(false), page=ref<any>(null), error=ref(''), busy=ref(false)
let generation=0
const requestedOffset=ref(0)
function name(){const summary=props.definitions?.[0]?.summary;return summary?.qualified_name||summary?.name||props.id}
function isAlias(edge:any){return edge.summary?.call_kind==='GNU_FUNCTION_ALIAS'}
function relationship(edge:any){return isAlias(edge)?(props.direction==='upstream'?'函数别名 → 当前实现':'当前别名 → 实现函数'):(props.direction==='upstream'?'调用者 → 当前函数':'当前函数 → 被调用者')}
async function load(offset=0){const request=++generation;requestedOffset.value=offset;busy.value=true;error.value='';try{const value=await api(`/scans/${props.scan}/call-neighbors?function_id=${encodeURIComponent(props.id)}&direction=${props.direction}&offset=${offset}`);if(request===generation)page.value=value}catch(e:any){if(request===generation)error.value='调用边读取失败：'+e.message+'；请重试。'}finally{if(request===generation)busy.value=false}}
watch([()=>props.scan,()=>props.id,()=>props.direction],()=>{generation++;open.value=false;page.value=null;error.value='';busy.value=false;requestedOffset.value=0})
async function toggle(){open.value=!open.value;if(open.value&&!page.value)await load()}
</script>
<template>
  <div class="call-node"><button class="call-function" :disabled="busy||ancestors.includes(id)" :aria-expanded="open" @click="toggle">{{open?'▾':'▸'}} {{name()}}</button><span v-if="ancestors.includes(id)" class="tag">递归回边，关系完整保留</span>
    <p class="muted" v-for="definition in definitions">{{definition.summary?.file}}:{{definition.summary?.line}}</p><p v-if="error" class="banner error">{{error}}</p>
    <p v-if="busy" class="muted" role="status">正在读取调用边…</p>
    <button v-if="error" :disabled="busy" @click="load(requestedOffset)">重试读取调用边</button>
    <div v-if="open&&page" class="call-children"><p>{{direction==='upstream'?'已恢复的上游关系':'已恢复的下游关系'}}：{{page.total}} 条；当前显示 {{page.total?page.offset+1:0}}–{{Math.min(page.offset+page.items.length,page.total)}}。同一调用者的多处调用分别保留，函数别名单独标明。</p><p v-if="!page.total">没有已恢复的该方向调用或别名关系。外部入口或未知调用请核对上下文与覆盖证据。</p>
      <article v-for="edge in page.items" :key="edge.ordinal"><p class="muted">{{relationship(edge)}} · {{isAlias(edge)?'别名声明：':''}}{{edge.summary?.file}}:{{edge.summary?.line}}</p><p v-if="isAlias(edge)" class="muted">函数别名绑定到同一实现地址；此处源码位置指别名声明。</p><CallNode v-if="edge.neighbor_id" :scan="scan" :id="edge.neighbor_id" :definitions="edge.definitions" :direction="direction" :ancestors="[...ancestors,id]"/><EvidenceNode :scan="scan" :node="edge.node" :title="isAlias(edge)?'函数别名完整证据':'调用边完整证据'"/></article>
      <button :disabled="busy||!page.offset" @click="load(Math.max(0,page.offset-50))">上一段调用边</button><button :disabled="busy||page.next_offset===null" @click="load(page.next_offset)">继续完整调用边</button>
    </div>
  </div>
</template>
