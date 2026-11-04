<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { api, upload } from './api'
import EvidenceNode from './EvidenceNode.vue'
const props=defineProps<{scans:any[],busy:boolean}>()
const emit=defineEmits<{tasks:[id:string]}>()
const expanded=ref(false),step=ref(1),working=ref(false),error=ref(''),notice=ref(''),plan=ref<any>(null),preset=ref('auto')
const panelRef=ref<HTMLElement|null>(null),catalog=ref<any[]>([]),catalogTotal=ref(0),nextOffset=ref<number|null>(0)
const rows=ref([{variant:'CM7',scan_id:'',elf_id:'',file:''},{variant:'CM4',scan_id:'',elf_id:'',file:''}])
const regions=ref([{start:'',size:''}])
const disabled=computed(()=>working.value||props.busy)
const eligible=computed(()=>catalog.value.filter(scan=>scan.can_confirm&&scan.identity?.config_sha256))
function choiceLabel(scan:any){return `${scan.identity?.project_name||scan.project_id} · ${scan.identity?.project_core||'核心未记录'} · ${scan.identity?.configured_target||scan.profile_id} · ${scan.scan_id}`}
const duplicate=computed(()=>rows.value.some((row,i)=>row.scan_id&&rows.value.some((other,j)=>{
 if(i===j||!other.scan_id)return false
 const a=props.scans.find(scan=>scan.scan_id===row.scan_id),b=props.scans.find(scan=>scan.scan_id===other.scan_id)
 return other.scan_id===row.scan_id||(typeof a?.facts_hash==='string'&&a.facts_hash===b?.facts_hash)
})))
watch(()=>JSON.stringify([rows.value,regions.value]),()=>{plan.value=null;notice.value=''})
async function focusStep(){await nextTick();panelRef.value?.scrollIntoView({block:'start'});panelRef.value?.focus({preventScroll:true})}
async function loadChoices(){
 if(nextOffset.value===null||disabled.value)return
 working.value=true;error.value=''
 try{const value=await api('/history?limit=50&offset='+nextOffset.value);const known=new Set(catalog.value.map(item=>item.scan_id));catalog.value.push(...value.items.filter((item:any)=>!known.has(item.scan_id)));catalogTotal.value=value.total;nextOffset.value=value.next_offset}catch(e:any){error.value=e.message}finally{working.value=false}
}
async function open(){expanded.value=true;if(!catalog.value.length)await loadChoices();await focusStep()}
async function move(value:number){step.value=value;error.value='';await focusStep()}
defineExpose({open})
async function selectElf(index:number,event:Event){
 const file=(event.target as HTMLInputElement).files?.[0];if(!file||disabled.value)return
 working.value=true;error.value='';notice.value='正在上传所选ELF并记录完整校验和…';plan.value=null
 rows.value[index].elf_id='';rows.value[index].file=''
 try{const result=await upload('/multicore/elf?name='+encodeURIComponent(file.name),file);rows.value[index].elf_id=result.id;rows.value[index].file=file.name;notice.value='ELF已上传，继续选择其余输入。'}catch(e:any){error.value=e.message;notice.value=''}finally{working.value=false}
}
async function check(){
 if(disabled.value)return;working.value=true;error.value='';notice.value='';plan.value=null
 try{plan.value=await api('/multicore/preview','POST',{inputs:rows.value.map(({variant,scan_id,elf_id})=>({variant,scan_id,elf_id})),regions:regions.value});step.value=3;await focusStep()}catch(e:any){error.value=e.message}finally{working.value=false}
}
async function start(){
 if(disabled.value||!plan.value)return;working.value=true;error.value=''
 try{const result=await api('/multicore/start','POST',{id:plan.value.id,revision:plan.value.revision,resources:{preset:preset.value}});emit('tasks',result.id)}catch(e:any){error.value=e.message;plan.value=null}finally{working.value=false}
}
</script>
<template>
 <section ref="panelRef" tabindex="-1" class="panel multicore-center" aria-label="多核已有结果合并">
  <h2>合并已有多核结果</h2>
  <p>使用各核心的已保存扫描、对应链接ELF和真实共享RAM进行派生合并。结果不代表新的多核原生扫描。</p>
  <button :disabled="disabled" :aria-expanded="expanded" @click="expanded?expanded=false:open()">{{expanded?'收起多核输入':'选择多核输入'}}</button>
  <template v-if="expanded">
   <ol class="steps multicore-steps" aria-label="多核合并步骤"><li v-for="(title,index) in ['选择核心输入','共享区域与预算','核对并提交']" :key="title" :class="{current:step===index+1}" :aria-current="step===index+1?'step':undefined">{{index+1}}. {{title}}</li></ol>
   <template v-if="step===1">
    <p class="muted">输入归档的人工记录保留在各自扫描；派生对象按合并后的证据独立确认。使用归档时的原始配置，不读取后来修改的profile。</p>
    <p v-if="!eligible.length&&!working">当前页没有可核对配置的核心归档，可读取更早批次，或先扫描/导入完整结果。</p>
    <fieldset v-for="(row,index) in rows" :key="index" :disabled="disabled" class="multicore-input">
     <legend>核心输入 {{index+1}}</legend>
     <label>核心别名<input :aria-label="'核心别名 '+(index+1)" v-model="row.variant" placeholder="例如 CM7"></label>
     <label>已保存扫描<select :aria-label="'多核扫描 '+(index+1)" v-model="row.scan_id"><option value="">请选择确切扫描批次</option><option v-for="scan in eligible" :key="scan.scan_id" :value="scan.scan_id">{{choiceLabel(scan)}}</option></select><span v-if="row.scan_id" class="identity">{{row.scan_id}}</span></label>
     <label>对应链接ELF<input type="file" accept=".elf,.axf" :aria-label="'多核ELF '+(index+1)" @change="selectElf(index,$event)"><span v-if="row.file" class="identity">已上传：{{row.file}}</span></label>
     <button v-if="rows.length>2" @click="rows.splice(index,1)">移除此核心输入</button>
    </fieldset>
    <div class="actions"><button :disabled="disabled" @click="rows.push({variant:'',scan_id:'',elf_id:'',file:''})">添加核心输入</button><button v-if="nextOffset!==null" :disabled="disabled" @click="loadChoices">读取更早扫描批次</button></div>
    <p class="muted">已读取历史 {{catalog.length}} / {{catalogTotal}} 批次；其中 {{eligible.length}} 项记录了可核对配置。完整校验在后续受控任务执行。</p>
    <p v-if="duplicate" class="banner warning">所选批次或完整事实根重复；同源归档的不同别名不能作为真实多核工程证明。</p>
    <div class="multicore-actions"><button class="primary" :disabled="disabled||rows.some(row=>!row.scan_id||!row.elf_id||!row.variant)" @click="move(2)">下一步：共享区域</button></div>
   </template>
   <template v-else-if="step===2">
    <h3>真实共享RAM区域</h3><p class="muted">按链接脚本填写起始地址与字节长度；支持十进制或0x十六进制，不会自动猜测。</p>
    <div v-for="(region,index) in regions" :key="index" class="multicore-region"><label>起始地址<input :aria-label="'共享RAM起始地址 '+(index+1)" v-model="region.start" :disabled="disabled" placeholder="按真实链接脚本填写"></label><label>长度（字节）<input :aria-label="'共享RAM长度 '+(index+1)" v-model="region.size" :disabled="disabled"></label><button v-if="regions.length>1" :disabled="disabled" @click="regions.splice(index,1)">移除此区域</button></div>
    <button :disabled="disabled" @click="regions.push({start:'',size:''})">添加共享区域</button>
    <label>合并资源预设<select aria-label="多核资源预设" v-model="preset" :disabled="disabled"><option value="auto">自动（峰值预算16GiB）</option><option value="low">低内存（峰值预算8GiB）</option><option value="high">高性能（峰值预算16GiB）</option></select></label>
    <div class="multicore-actions"><button :disabled="disabled" @click="move(1)">返回核心输入</button><button class="primary" :disabled="disabled" @click="check">检查多核输入</button></div>
   </template>
   <template v-else>
    <section v-if="plan" aria-label="多核输入检查计划"><h3>核对已固定的输入</h3><article v-for="row in plan.inputs" :key="row.variant"><strong>{{row.variant}} · {{row.name}} · 归档核心 {{row.core}}</strong><p class="identity">扫描 {{row.scan_id}} · 配置 {{row.profile_id}}</p><p>目标 {{row.target||'未记录'}} · 变体 {{row.build_variant||'未记录'}} · ELF {{row.elf_name}}</p></article><p>共享RAM：{{plan.regions.map((region:number[])=>'0x'+region[0].toString(16)+' / 0x'+region[1].toString(16)+'字节').join('；')}}</p><p>进程树峰值预算：{{preset==='low'?8:16}} GiB</p><details><summary>查看归档配置来源指纹</summary><div v-for="row in plan.inputs" :key="row.variant"><p class="identity">{{row.variant}} · 配置SHA-256 {{row.config_sha256}}</p><p class="identity">ELF SHA-256 {{row.expected.elf_sha256}} · {{row.elf_bytes}} 字节</p><EvidenceNode v-if="row.config_node" :scan="row.scan_id" :node="row.config_node" title="扫描时完整配置原文"/></div><p class="identity">{{plan.project_root}}</p></details><p class="muted">{{plan.note}}</p></section>
    <div class="multicore-actions"><button :disabled="disabled" @click="move(2)">返回共享区域</button><button v-if="plan" class="primary" :disabled="disabled" @click="start">开始派生合并</button></div>
   </template>
  </template>
  <p v-if="working" role="status">正在处理真实多核输入，剩余量未知…</p><p v-if="notice" role="status">{{notice}}</p><p v-if="error" role="alert" class="banner error">多核操作未完成：{{error}}</p>
 </section>
</template>
<style scoped>
.multicore-input{display:grid;grid-template-columns:minmax(100px,1fr) minmax(0,3fr) minmax(0,2fr);gap:16px;border:1px solid #d9e1ed;border-radius:4px;margin:16px 0;padding:16px;min-width:0}.multicore-input label{min-width:0}.multicore-input input[type=file]{width:100%}.multicore-region{display:flex;align-items:center;gap:16px;flex-wrap:wrap}.multicore-region label{flex:1;min-width:160px}.multicore-center article{border-bottom:1px solid #d9e1ed;padding:8px 0}.multicore-center .identity{overflow-wrap:anywhere}.multicore-steps{list-style:none;padding:12px;gap:16px;margin-top:16px}.multicore-actions{display:flex;gap:8px;justify-content:space-between;position:sticky;bottom:0;background:#fff;padding:12px 0 0;border-top:1px solid #d9e1ed;margin-top:16px}@media(max-width:850px){.multicore-input{grid-template-columns:1fr}}
</style>
