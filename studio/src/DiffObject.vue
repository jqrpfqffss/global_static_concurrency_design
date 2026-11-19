<script setup lang="ts">
import EvidenceNode from './EvidenceNode.vue'
import {objectEvents, staticLabel} from './diffPresentation'
defineProps<{scan:string, change:any}>()
</script>
<template>
  <section class="diff-object" aria-label="双版本静态变化">
    <p><strong>{{change.impact_label}}</strong> · {{objectEvents[change.object_event] || change.object_event}}
      <span v-if="change.container"> · 容器（不重复计风险）</span></p>
    <p>{{staticLabel(change.base_classification)}} → {{staticLabel(change.head_classification)}}</p>
    <p>{{change.risk_case || ''}} {{change.risk_label}}</p>
    <small>影响分类与静态变化独立保存；AI 和人工处理遵循原确认规则。</small>
    <EvidenceNode :scan="scan" :node="change.impact_node" title="查看影响路径、双侧缺口和风险变化证明"/>
  </section>
</template>
<style scoped>.diff-object{border-left:3px solid #52769e;padding:4px 12px;margin:12px 0}.diff-object p{margin:6px 0}</style>
