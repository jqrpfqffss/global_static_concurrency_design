<script setup lang="ts">
import { ref } from 'vue'
import { api, field } from './api'
const props = defineProps<{ scan: string, node: number, title: string }>()
const page = ref<any>(null), error = ref(''), busy = ref(false), text = ref('')
async function load(next = false) {
  busy.value = true; error.value = ''
  try {
    const path = `/scans/${props.scan}/nodes/${props.node}`
    const value = await api(path + (next ? `?offset=${page.value.next_offset}` : ''))
    if (next) page.value = { ...value, items: [...page.value.items, ...value.items] }
    else page.value = value
    if (value.segmented) await loadText(false)
  } catch (e: any) { error.value = e.message } finally { busy.value = false }
}
const textOffset = ref<number|null>(0)
async function loadText(next: boolean) {
  try {
    const value = await api(`/scans/${props.scan}/text/${props.node}?offset=${next ? textOffset.value : 0}`)
    text.value = next ? text.value + value.value : value.value; textOffset.value = value.next_offset
  } catch (e: any) { error.value = e.message }
}
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
          <div v-else class="fact-line"><strong>{{ item.key === null ? '第 '+(item.ordinal+1)+' 项' : field(item.key) }}</strong><span>{{ item.value === null ? '未提供/未知' : String(item.value) }}</span></div>
        </template>
        <div class="page-controls"><span>已显示 {{ page.items.length }} / {{ page.total }}</span><button v-if="page.next_offset !== null" :disabled="busy" @click="load(true)">继续读取证据</button></div>
      </template>
      <template v-else-if="page.segmented"><pre>{{ text }}</pre><button v-if="textOffset !== null" @click="loadText(true)">继续读取文本</button></template>
      <pre v-else>{{ page.value }}</pre>
    </div>
  </details>
</template>
