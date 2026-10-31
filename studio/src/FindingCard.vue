<script setup lang="ts">
import { ref,onMounted } from 'vue'
import { api,field } from './api'
import EvidenceNode from './EvidenceNode.vue'
import ConflictPairs from './ConflictPairs.vue'
const props=defineProps<{scan:string,node:number,summary:any}>(),emit=defineEmits(['source'])
const fields=ref<any[]>([]),error=ref('')
onMounted(async()=>{try{fields.value=(await api('/scans/'+props.scan+'/nodes/'+props.node+'?limit=200')).items}catch(e:any){error.value=e.message}})
</script>
<template><article class="finding-card"><p class="finding-reason">{{summary.concurrency_reason || '该发现没有简短并发理由，请核对下方完整静态证据。'}}</p><p>{{summary.protection_note}}</p><p v-if="error" class="banner error">{{error}}</p><template v-for="item in fields" :key="item.id+item.key"><ConflictPairs v-if="item.key==='conflict_pairs'" :scan="scan" :node="item.id" @source="emit('source',$event)"/><EvidenceNode v-else-if="['uncertainties','coverage_reasons','blocking_evidence','protection_details','configured_preemption','configured_concurrency','multi_field_coherence'].includes(item.key)" :scan="scan" :node="item.id" :title="field(item.key)+' · '+item.total+' 项'"/></template><EvidenceNode :scan="scan" :node="node" title="本项静态发现的全部原始字段"/></article></template>
