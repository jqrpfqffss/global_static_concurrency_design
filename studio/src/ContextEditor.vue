<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import FunctionNames from './FunctionNames.vue'
type Entry = { origin_id:string|null, id:string, kind:string, functions:string[] }
const props=defineProps<{modelValue:Entry[],editable:boolean,reason:string}>()
const emit=defineEmits<{ 'update:modelValue':[value:Entry[]] }>()
const kinds=[['MAIN','主入口'],['ISR','中断服务'],['TASK','RTOS任务'],['CALLBACK','回调'],['DMA','DMA'],['CORE','核心'],['FOREGROUND','前台'],['IRQ','IRQ'],['EXTERNAL_ASYNC','外部异步'],['UNKNOWN_CONTEXT','未知上下文']]
const page=ref(0),newKind=ref('TASK'),size=8
const shown=computed(()=>props.modelValue.slice(page.value*size,(page.value+1)*size))
watch(()=>props.modelValue.length,()=>{page.value=Math.min(page.value,Math.max(0,Math.ceil(props.modelValue.length/size)-1))})
function update(index:number,key:'id'|'kind'|'functions',value:string){
  const rows=props.modelValue.map(row=>({...row,functions:[...row.functions]}))
  const row=rows[page.value*size+index]
  if(key==='functions')row.functions=value.split(/\r?\n/).filter(line=>line.length>0)
  else row[key]=value
  emit('update:modelValue',rows)
}
function add(){
  const prefix=newKind.value.toLowerCase();let suffix=1
  while(props.modelValue.some(row=>row.id===prefix+'_'+suffix))suffix++
  emit('update:modelValue',[...props.modelValue,{origin_id:null,id:prefix+'_'+suffix,kind:newKind.value,functions:[]}])
  page.value=Math.floor(props.modelValue.length/size)
}
function remove(index:number){emit('update:modelValue',props.modelValue.filter((_,i)=>i!==page.value*size+index))}
</script>

<template>
  <section class="context-editor" aria-label="执行入口配置">
    <h3>执行入口 · main / ISR / 任务</h3>
    <p class="muted">补充实际入口函数；普通表单只修改ID、类型与函数，高级优先级、正则和其他字段保留。不会根据类型编造抢占或并发关系。</p>
    <p v-if="!editable" class="banner warning" role="note">{{reason}}。本部分请在下一步高级完整 YAML 编辑，其他普通字段仍可修改。</p>
    <template v-else>
      <p v-if="!modelValue.length" class="muted">没有手工配置入口；自动识别仍按现有分析配置执行。</p>
      <article v-for="(row,index) in shown" :key="page*size+index" class="context-row" :aria-label="'入口 '+(page*size+index+1)">
        <div class="context-identity"><label>入口ID<input :aria-label="'入口ID '+(page*size+index+1)" :value="row.id" @input="update(index,'id',($event.target as HTMLInputElement).value)"></label><label>类型<select :aria-label="'入口类型 '+(page*size+index+1)" :value="row.kind" @change="update(index,'kind',($event.target as HTMLSelectElement).value)"><option v-for="[value,title] in kinds" :value="value">{{title}} · {{value}}</option></select></label></div>
        <label>函数名（每行一个，保留重复项）<FunctionNames :label="'入口函数 '+(page*size+index+1)" :value="row.functions" @edit="value=>update(index,'functions',value)"/></label>
        <button type="button" :aria-label="'移除入口 '+(page*size+index+1)" @click="remove(index)">移除此入口</button>
      </article>
      <div class="page-controls" v-if="modelValue.length>size"><button type="button" :disabled="page===0" @click="page--">上一页入口</button><span>第 {{page+1}} / {{Math.ceil(modelValue.length/size)}} 页 · 共 {{modelValue.length}} 项</span><button type="button" :disabled="(page+1)*size>=modelValue.length" @click="page++">下一页入口</button></div>
      <div class="context-add"><label>新增入口类型<select v-model="newKind" aria-label="新增入口类型"><option v-for="[value,title] in kinds" :value="value">{{title}} · {{value}}</option></select></label><button type="button" @click="add">添加执行入口</button></div>
      <p class="muted">移除会删除该入口整段配置，包括其高级字段。同步后可在下一步恢复原文；ID变化不会自动改写高级并发关系，须重新检查并保存。</p>
    </template>
  </section>
</template>

<style scoped>
.context-editor{border-top:1px solid #d9e1ed;margin-top:20px;padding-top:4px}.context-row{border:1px solid #d9e1ed;border-radius:4px;padding:12px;margin-bottom:12px}.context-identity{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}.context-row label{margin-bottom:8px}.context-add{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;margin-top:12px}.context-add label{flex:1;min-width:180px;margin-bottom:0}.context-add button{flex-shrink:0}@media(max-width:600px){.context-identity{grid-template-columns:1fr}}
</style>
