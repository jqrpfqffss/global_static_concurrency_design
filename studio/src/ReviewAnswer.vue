<script setup lang="ts">
import { computed } from 'vue'
const props=defineProps<{answer:any}>(),emit=defineEmits<{source:[location:any]}>()
const summary=computed(()=>props.answer.summary||props.answer.explanation?.summary||props.answer.reason)
const sections=[['reason','判定依据'],['interleaving','具体交错过程 / 不发生冲突的条件'],['protection','保护范围与成立条件'],['impact','影响及证据边界'],['fix','处理建议'],['verification','验证建议（尚未实测）']]
</script>
<template><article class="review-answer"><p class="review-verdict-summary">{{summary}}</p><p v-if="answer.missing_context?.length" class="banner warning">尚缺事实：{{Array.isArray(answer.missing_context)?answer.missing_context.join('；'):answer.missing_context}}</p><section v-for="[key,title] in sections.filter(([key])=>answer[key])" :key="key"><h3>{{title}}</h3><p class="review-prose">{{answer[key]}}</p></section><section v-if="answer.evidence?.length"><h3>源码依据</h3><article v-for="(item,index) in answer.evidence" :key="index" class="review-citation"><button @click="emit('source',item)">{{item.file}}:{{item.line}}</button><p class="review-prose">{{item.claim}}</p></article></section><details><summary>完整原始答复与附加字段</summary><pre>{{JSON.stringify(answer,null,2)}}</pre></details></article></template>
<style scoped>.review-prose{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.65}.review-verdict-summary{background:#edf3ff;padding:12px;font-weight:600}.review-citation{padding:6px 0;border-bottom:1px solid var(--border)}.review-citation button{text-align:left;overflow-wrap:anywhere}.review-answer pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>
