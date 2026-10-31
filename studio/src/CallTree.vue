<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api } from './api'
import CallNode from './CallNode.vue'
const props=defineProps<{scan:string,symbol:string}>()
const page=ref<any>(null), direction=ref('upstream'), error=ref(''), fontSize=ref(14)
async function load(offset=0){try{error.value='';page.value=await api(`/scans/${props.scan}/symbol-functions?symbol_id=${encodeURIComponent(props.symbol)}&offset=${offset}`)}catch(e:any){error.value=e.message}}
onMounted(()=>load());watch(()=>props.symbol,()=>load())
</script>
<template>
  <section class="call-tree"><h3>从真实访问函数展开调用关系</h3><p>沿已恢复调用边追溯 main/ISR/回调入口。入口类别、能否抢占及保护是否有效，须结合执行上下文与 NVIC 证据核对。</p><label>查询方向<select v-model="direction" aria-label="调用查询方向"><option value="upstream">上游：回溯调用者与入口</option><option value="downstream">下游：展开被调用函数</option></select></label><button :disabled="fontSize<=12" @click="fontSize--">缩小调用树</button><button :disabled="fontSize>=20" @click="fontSize++">放大调用树</button>
    <p v-if="error" class="banner error">{{error}}</p><template v-if="page"><p>变量完整访问函数 {{page.total}} 个；当前显示 {{page.total?page.offset+1:0}}–{{Math.min(page.offset+page.items.length,page.total)}}</p><div :style="{fontSize:fontSize+'px'}"><CallNode v-for="row in page.items" :key="row.function_id+direction" :scan="scan" :id="row.function_id" :definitions="row.definitions" :direction="direction" :ancestors="[]"/></div><button :disabled="!page.offset" @click="load(Math.max(0,page.offset-50))">上一页函数</button><button :disabled="page.next_offset===null" @click="load(page.next_offset)">继续完整函数</button></template>
  </section>
</template>
