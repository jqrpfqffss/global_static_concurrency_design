<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from './api'
import EvidenceNode from './EvidenceNode.vue'
import WorkspaceDialog from './WorkspaceDialog.vue'
import DiffObject from './DiffObject.vue'
import {riskCases, objectEvents, publicationLabel, verificationLabel} from './diffPresentation'
const props = defineProps<{scan:string, diff:any, compact?:boolean, busy:boolean}>()
const emit = defineEmits<{impacts:[], select:[item:any]}>()
const open=ref(false), kind=ref('objects'), offset=ref(0), impact=ref(''), risk=ref(''), event=ref('')
const page=ref<any>(null), loading=ref(false), error=ref(''), retry=ref(0)
const pageSize=25
const direction=computed(()=>{
  const pin=props.diff.pin || {}
  const show=(name?:string,sha?:string)=>`${name || '未记录'}${sha?' ('+sha.slice(0,7)+')':''}`
  return `${show(pin.base_ref,pin.base_sha)} → ${show(pin.current_ref,pin.head_sha)}`
})
const counts=computed(()=>props.diff.impact_counts ?
  `明确影响 ${props.diff.impact_counts.DEFINITE} · 待核实 ${props.diff.impact_counts.UNCERTAIN} · 可排除 ${props.diff.impact_counts.EXCLUDED} · 区域性缺口 ${props.diff.regional_gap_count || 0}` :
  `当前差异变量 ${props.diff.selected_symbol_ids_count} · 基准侧 ${props.diff.deleted_variable_count || 0}`)
const tabs=computed(()=>[
  ...(props.diff.comparison_object_count!==undefined?[['objects','差异变量与风险变化']]:[['deleted','已删除变量']]),
  ['files','变更文件'], ...(props.diff.regional_gap_count!==undefined?[['regional_gaps','覆盖缺口']]:[]),
])
function choose(value:string){kind.value=value;offset.value=0}
function openDetails(){choose(tabs.value[0]![0]!);open.value=true}
watch([impact,risk,event],()=>{offset.value=0})
watch([open,kind,offset,impact,risk,event,retry,()=>props.scan],async(_,__,onCleanup)=>{
  page.value=null;error.value='';loading.value=false
  if(!open.value)return
  let active=true;onCleanup(()=>{active=false});loading.value=true
  try {
    const params=new URLSearchParams({kind:kind.value,offset:String(offset.value),limit:String(pageSize),
      ...(kind.value==='objects'?{impact:impact.value,risk:risk.value,event:event.value}:{})})
    const result=await api(`/scans/${encodeURIComponent(props.scan)}/diff-changes?${params}`)
    if(active)page.value=result
  } catch(exc){if(active)error.value=(exc as Error).message}
  finally{if(active)loading.value=false}
})
function showImpacts(){open.value=false;emit('impacts')}
function select(item:any){open.value=false;emit('select',item)}
</script>

<template>
  <div v-if="compact" class="diff-strip">
    <span :title="direction">Git 差异 · {{counts}} · {{publicationLabel(diff.publication?.state)}}</span>
    <button @click="openDetails">查看差异结果</button>
  </div>
  <section v-else class="panel" aria-label="Git 差异扫描">
    <h2>Git 差异扫描</h2><p class="identity">{{direction}}</p><p>{{counts}}</p>
    <p v-if="diff.identified_object_count!==undefined">三类归账覆盖 {{diff.identified_object_count}} 个已识别存储对象；{{diff.container_count || 0}} 个容器单列，不重复计风险。</p>
    <p>{{publicationLabel(diff.publication?.state)}} · {{verificationLabel(diff.full_verification?.state)}}</p>
    <p>当前打开批次 {{scan}}。可排除对象保留后台审计证据；变量列表仅包含明确影响和待核实对象。</p>
    <div class="actions"><button @click="openDetails">查看差异结果</button><button :disabled="busy" @click="showImpacts">查看差异变量</button></div>
  </section>
  <WorkspaceDialog v-if="open" title="Git 差异结果" :error="error" @close="open=false">
    <p class="identity">{{direction}}</p><p>{{counts}}</p>
    <p>{{publicationLabel(diff.publication?.state)}} · {{verificationLabel(diff.full_verification?.state)}}</p>
    <p v-if="!diff.real_object_inventory_complete" class="banner warning">存在未识别区域，三类计数仅覆盖已识别对象；没有待办不代表整体安全。</p>
    <p v-if="diff.risk_comparison_note" class="banner warning">{{diff.risk_comparison_note}}</p>
    <p v-if="diff.change_counts">静态差异（复核前） · 当前侧静态疑似 {{diff.change_counts.current_suspect || 0}} · 原风险未关闭 {{diff.change_counts.prior_risk_unclosed || 0}} · 确定新增疑似 {{diff.change_counts.counts_as_new_risk || 0}} · 有关闭证明 {{diff.change_counts.counts_as_risk_resolution || 0}}</p>
    <div class="section-tabs" aria-label="差异明细"><button v-for="[id,title] in tabs" :key="id" :aria-pressed="kind===id" @click="choose(id!)">{{title}}</button></div>
    <p v-if="kind==='files'" class="muted">结论对应两端实际构建中的活动代码。未入构建文件与失活宏分支只作为范围或声明记录，不作为运行访问或安全证明；文件范围可在“覆盖与诊断 → 构建与范围”中核对。</p>
    <div v-if="kind==='objects'" class="diff-filters">
      <label>影响归属<select v-model="impact"><option value="">全部差异</option><option value="DEFINITE">明确影响</option><option value="UNCERTAIN">待核实</option></select></label>
      <label>静态风险变化<select v-model="risk"><option value="">全部变化</option><option v-for="(title,id) in riskCases" :value="id">{{id}} · {{title}}</option><option value="EXEMPTION_GAINED">进入共享无需复核</option><option value="EXEMPTION_RETAINED">免复核依据保持</option><option value="EXEMPTION_LOST_SUSPECT">免复核失效，当前疑似</option><option value="EXEMPTION_LOST_UNKNOWN">免复核依据不足</option><option value="EXEMPTION_TO_SAFETY">免复核转独立安全证明</option><option value="EXEMPTION_UNVERIFIED">免复核证明缺失</option><option value="PROOF_INCOMPLETE">安全证明不完整</option><option value="NOT_COMPARABLE">变化依据不足或对象不可比</option><option value="PRIOR_RISK_UNCLOSED">基准风险未关闭（对象不可比）</option><option value="CURRENT_SUSPECT_UNMATCHED">当前疑似，对象不可比</option></select></label>
      <label>对象变化<select v-model="event"><option value="">全部对象变化</option><option v-for="(title,id) in objectEvents" :value="id">{{title}}</option></select></label>
    </div>
    <p v-if="loading" role="status">正在读取差异明细…</p><button v-if="error" @click="retry++">重试读取</button>
    <template v-if="page">
      <p v-if="!page.total">{{kind==='regional_gaps'?'未记录区域性缺口；仍需结合对象覆盖证据。':'此范围没有匹配项。'}}</p>
      <template v-for="item in page.items" :key="item.ordinal">
        <article v-if="kind==='objects'" class="comparison-row">
          <h3>{{item.name}} <small>{{item.evidence_side==='baseline'?'基准侧证据':'当前侧证据'}}</small></h3>
          <DiffObject :scan="scan" :change="item"/>
          <button :disabled="busy" @click="select(item)">查看该侧证据与人工记录</button>
        </article>
        <p v-else-if="kind==='files'" class="identity">{{item.status}} · {{item.old_path && item.old_path!==item.new_path?item.old_path+' → ':''}}{{item.new_path || item.old_path}} <small v-if="item.comment_only">仅注释变化</small></p>
        <EvidenceNode v-else :scan="scan" :node="item.node" :title="item.name || `${item.side==='base'?'基准':'当前'} · ${item.source_file || item.kind}`"/>
      </template>
      <div v-if="page.total" class="page-controls"><button :disabled="offset===0" @click="offset=Math.max(0,offset-pageSize)">上一页</button><span>{{offset+1}}–{{offset+page.items.length}} / {{page.total}}</span><button :disabled="page.next_offset===null" @click="offset=page.next_offset ?? offset">下一页</button></div>
    </template>
    <template #footer><span>{{diff.impact_coverage==='COMPLETE'?'已识别对象的影响归属完整':'仍有待核实影响或区域缺口'}}</span><button :disabled="busy" @click="showImpacts">查看差异变量</button></template>
  </WorkspaceDialog>
</template>
<style scoped>
.identity{overflow-wrap:anywhere}.comparison-row{border-bottom:1px solid #dce4ee;padding:10px 0}.diff-filters{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}.diff-filters label{flex:1;min-width:160px}.section-tabs button[aria-pressed=true]{background:#eaf1ff;border-color:#426fbe}
</style>
