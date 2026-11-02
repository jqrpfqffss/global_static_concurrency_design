<script setup lang="ts">
defineProps<{storage:any}>()
const groups=[['scans','扫描归档'],['projects','工程与构建'],['cache','共享缓存'],['work','工作与诊断'],['exports','导出'],['settings','设置']]
function size(value:any){return typeof value==='number'&&Number.isFinite(value)?`${(value/1024/1024).toFixed(2)} MiB`:'未测量'}
</script>
<template>
 <div v-if="storage" class="storage-usage" aria-label="真实数据占用明细">
  <p v-if="storage.sampling_partial" role="status" class="banner warning">采样不完整：部分目录变化或不可读取，未知分配量未按0计算。请稍后重试。</p>
  <table><colgroup><col class="category"><col><col></colgroup><thead><tr><th scope="col">类别</th><th scope="col">逻辑大小</th><th scope="col">实际文件分配</th></tr></thead><tbody><tr v-for="[key,name] in groups" :key="key"><th scope="row">{{name}}</th><td>{{size(storage.bytes?.[key])}}<small v-if="typeof storage.bytes?.[key]==='number'">{{storage.bytes[key]}} B</small></td><td>{{size(storage.allocated_bytes?.[key])}}<small v-if="typeof storage.allocated_bytes?.[key]==='number'">{{storage.allocated_bytes[key]}} B</small></td></tr></tbody></table>
  <p class="muted">{{storage.reason}}</p>
 </div>
</template>
<style scoped>
.storage-usage table{width:100%;border-collapse:collapse;font-size:14px}.storage-usage th,.storage-usage td{text-align:left;padding:8px 4px;border-bottom:1px solid #d9e1ed;overflow-wrap:anywhere}.storage-usage th{font-weight:600}.storage-usage .category{width:5.5em}.storage-usage th[scope=row]{white-space:nowrap}.storage-usage small{display:block;font-size:12px;color:#5e708c}
</style>
