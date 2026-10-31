<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api } from './api'
const props=defineProps<{scan:string}>()
const emit=defineEmits<{evidence:[]}>()
const files=ref<any>(null),text=ref<any>(null),selected=ref<any>(null),error=ref(''),busy=ref(false)
async function page(offset=0){busy.value=true;error.value='';try{files.value=await api(`/scans/${encodeURIComponent(props.scan)}/legacy-files?offset=${offset}`)}catch(e:any){error.value=e.message}finally{busy.value=false}}
async function open(item:any,offset=0){busy.value=true;error.value='';try{text.value=await api(`/scans/${encodeURIComponent(props.scan)}/legacy-file?ordinal=${item.ordinal}&offset=${offset}&limit=8192`);selected.value=item}catch(e:any){error.value=e.message}finally{busy.value=false}}
watch(()=>props.scan,()=>{selected.value=null;text.value=null;page()})
onMounted(()=>page())
</script>
<template>
  <section class="panel" aria-label="旧归档原文件与复核历史">
    <h2>旧归档原文件与复核历史</h2><p>旧文件按SHA-256保留；旧HTML、脚本和数据库只显示原字节。完整facts/report已转换为权威证据，字段类型、顺序和重复均保留。原文件不会作为代码执行。</p>
    <div v-if="error" class="banner error" role="alert">{{error}}</div>
    <p v-if="busy" role="status">正在读取归档文件清单或片段…</p>
    <article v-for="item in files?.items" :key="item.ordinal" class="history-row"><div><strong class="identity">{{item.file}}</strong><p>{{item.size}} 字节 · {{item.disposition==='CANONICAL_REENCODED'?'完整逻辑已入权威库':'原字节审计已保留'}}</p><small class="identity">SHA-256 {{item.sha256}}</small></div><button v-if="item.disposition==='OPAQUE_AUDIT_PRESERVED'" :disabled="busy" @click="open(item)">查看归档片段</button><button v-else @click="emit('evidence')">查看完整权威证据</button></article>
    <div v-if="files" class="page-controls"><button :disabled="busy||files.offset===0" @click="page(Math.max(0,files.offset-50))">上一页旧文件</button><span>{{files.total}} 个原文件</span><button :disabled="busy||files.next_offset===null" @click="page(files.next_offset)">下一页旧文件</button></div>
    <section v-if="text" aria-label="旧审计文件内容"><h3 class="identity">{{text.file}}</h3><p>{{text.source}}</p><p>{{text.encoding==='hex'?'十六进制原字节':'UTF-8文本'}} · 字节 {{text.offset}}–{{text.next_offset??text.total}} / {{text.total}}</p><pre class="legacy-preview">{{text.text}}</pre><div class="actions"><button :disabled="busy||text.offset===0" @click="open(selected)">返回文件开头</button><button :disabled="busy||text.next_offset===null" @click="open(selected,text.next_offset)">继续读取下一段</button></div></section>
  </section>
</template>
<style scoped>
.legacy-preview{white-space:pre-wrap;overflow-wrap:anywhere;max-height:30rem;overflow:auto;background:var(--surface-muted,#f4f6f8);padding:1rem;line-height:1.5}
</style>
