<script setup lang="ts">
import { ref, watch } from 'vue'
import { api, field } from './api'
const props = defineProps<{ scan: string, node: number, title: string }>()
const page = ref<any>(null), error = ref(''), busy = ref(false), textPage = ref<any>(null)
const scalar=(item:any)=>item.value===null?'未提供/未知':item.display_json??item.exact_value??String(item.value)
async function load(offset = 0) {
  busy.value = true; error.value = ''
  try {
    const path = `/scans/${props.scan}/nodes/${props.node}`
    page.value = await api(path + `?offset=${offset}`)
    if (page.value.segmented) await loadText(0)
  } catch (e: any) { error.value = e.message } finally { busy.value = false }
}
async function loadText(offset: number) {
  busy.value=true;error.value=''
  try {
    textPage.value = await api(`/scans/${props.scan}/text/${props.node}?offset=${offset}`)
  } catch (e: any) { error.value = e.message } finally{busy.value=false}
}
watch(()=>[props.scan,props.node],()=>{page.value=null;textPage.value=null;error.value=''})
</script>
<template>
  <details class="evidence-node" @toggle="(event: Event) => { if ((event.target as HTMLDetailsElement).open && !page && !busy) load() }">
    <summary>{{ title }} <small v-if="page">{{ page.kind === 'str' ? '文本证据' : `共 ${page.total} 项` }}</small></summary>
    <p v-if="busy" role="status">正在读取证据…</p><p v-if="error" role="alert" class="error">{{ error }}</p>
    <div v-if="page" class="node-content">
      <div class="reference">证据引用 #{{ page.id }} · SHA-256 {{ page.hash }}</div>
      <template v-if="page.items">
        <template v-for="item in page.items" :key="item.ordinal">
          <EvidenceNode v-if="item.kind === 'list' || item.kind === 'object' || (item.kind === 'str' && item.value === null)" :scan="scan" :node="item.id" :title="`${item.key === null ? '第 '+(item.ordinal+1)+' 项' : field(item.key)} (${item.total})`" />
          <div v-else class="fact-line"><strong>{{ item.key === null ? '第 '+(item.ordinal+1)+' 项' : field(item.key) }}</strong><span :title="item.display_json ? '未配对UTF-16代码单元，以JSON转义精确显示；原值保留' : item.binary_value ? '浮点精确编码 '+item.binary_value : undefined">{{ scalar(item) }}</span></div>
        </template>
        <div class="page-controls"><button v-if="page.offset>0" :disabled="busy" @click="load(Math.max(0,page.offset-50))">上一页证据</button><span>显示 {{page.items.length ? page.offset+1 : 0}}–{{page.offset+page.items.length}} / {{page.total}}</span><button v-if="page.next_offset !== null" :disabled="busy" @click="load(page.next_offset)">继续读取证据</button></div>
      </template>
      <template v-else-if="page.segmented&&textPage"><p>UTF-8字节 {{textPage.offset}}–{{textPage.next_offset??textPage.total}} / {{textPage.total}}</p><p v-if="textPage.display_json">该段有未配对UTF-16代码单元，以JSON转义精确显示。</p><pre>{{ textPage.display_json??textPage.value }}</pre><button v-if="textPage.previous_offset!==null" :disabled="busy" @click="loadText(textPage.previous_offset)">上一段文本</button><button v-if="textPage.next_offset !== null" :disabled="busy" @click="loadText(textPage.next_offset)">继续读取文本</button></template>
      <pre v-else>{{ scalar(page) }}</pre>
    </div>
  </details>
</template>
