<script setup lang="ts">
import { ref, watch } from 'vue'
const props=defineProps<{value:string[],label:string}>()
const emit=defineEmits<{ edit:[value:string] }>()
const draft=ref(props.value.join('\n'))
function lines(value:string){return value.split(/\r?\n/).filter(line=>line.length>0)}
watch(()=>props.value,value=>{
  // Keep the user's trailing newline while typing. Sibling field changes must
  // not reset an unblurred function edit, and a replaced row must still hydrate.
  if(JSON.stringify(value)!==JSON.stringify(lines(draft.value)))draft.value=value.join('\n')
})
function input(event:Event){draft.value=(event.target as HTMLTextAreaElement).value;emit('edit',draft.value)}
</script>

<template><textarea :aria-label="label" :value="draft" rows="2" @input="input"></textarea></template>
