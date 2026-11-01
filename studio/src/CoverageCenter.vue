<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, field } from './api'
import EvidenceNode from './EvidenceNode.vue'
import SourceViewer from './SourceViewer.vue'
const props=defineProps<{scan:string,roots:any[]}>()
const emit=defineEmits<{symbol:[id:string]}>()
const base=`/scans/${encodeURIComponent(props.scan)}/coverage`
const tabs=[['blockers','变量覆盖阻断'],['issues','解析/别名/硬件记录'],['tus','编译单元'],['build','构建与范围']]
const tab=ref('blockers'),stats=ref<any>(null),rows=ref<any>(null),groups=ref<any>(null),related=ref<any>(null)
const selected=ref<any>(null),busy=ref(false),error=ref(''),kind=ref(''),status=ref(''),search=ref(''),zero=ref(false)
const showSource=ref(false)
const detailFields:Record<string,string>={diagnostics:'解析诊断（完整原文）',diagnostic:'原始诊断',original_arguments:'原始真实编译命令',arguments:'实际解析参数',system_include_dirs:'系统头文件路径',includes:'实际包含的头文件',relevance_proofs:'全部对象关联证明'}
const offsets=ref<Record<string,number>>({blockers:0,issues:0,tus:0}),groupOffset=ref(0)
const descriptions:Record<string,[string,string]>={
 PARSE_FAILED:['解析失败','核对本TU的完整编译命令、工具链、头文件与宏，再按原构建重新扫描。'],
 PARTIAL_PARSE_REGION:['局部解析不完整','打开原始诊断，核对出错位置及其编译参数；修复后重扫并核对受影响对象。'],
 POINTER_DEREFERENCE:['指针解引用','核对实际指向对象、调用上下文和别名传播证据；不能将未解析指针视为无访问。'],
 POINTER_SUBSCRIPT:['指针下标访问','核对基址、下标范围及实际缓冲区，结合调用与访问证据确认影响。'],
 UNRESOLVED_POINTEE:['指向对象未解析','核对指针赋值、参数传递和对象生命周期，补充实际工程证据。'],
 UNRESOLVED_DMA_BUFFER:['DMA缓冲区未解析','核对DMA配置、启动调用、缓冲区身份及完成中断，保留硬件异步访问的影响。'],
 INLINE_ASSEMBLY:['内联汇编','查看原汇编及操作数、约束和屏障语义，人工核对对内存和中断状态的影响。'],
 ADDRESS_ESCAPE:['地址逸出','核对接收地址的函数、回调或外设用途；不能用缺少后续访问记录证明安全。'],
 TYPE_VARIANT:['类型存在变体','核对各TU的宏、头文件与类型布局，确认实际构建变体。'],
 FUNCTION_ADDRESS:['函数地址使用','核对回调注册、间接调用和上下文归属，保留未解析调用的可能影响。'],
 DEFINITION_MISSING:['缺少定义','核对定义是否位于排除目录、未入构建文件或解析失败TU；按原构建补齐证据。']
}
function kindTitle(raw:any){return typeof raw==='string'?(descriptions[raw]?.[0]||'未识别缺口类型：'+raw):'缺口类型未提供或不是短文本'}
function hint(raw:any){return descriptions[raw]?.[1]||'查看完整原始记录及关联证明，核对真实源码与构建输入；当前没有足够信息给出专用修复步骤。'}
function tuTitle(raw:any){return ({PARSED:'解析成功',PARTIAL:'局部解析',FAILED:'解析失败'} as Record<string,string>)[raw]||(raw===null||raw===undefined?'TU状态未归档或不是短文本':'未识别TU状态：'+raw)}
function state(){return {tab:tab.value,kind:kind.value,status:status.value,search:search.value,zero:zero.value,offsets:offsets.value,groupOffset:groupOffset.value,selected:selected.value?{node:selected.value.node,source:selected.value.source}:null}}
async function persist(){await api(base+'/position','PUT',state())}
async function perform(task:()=>Promise<any>){if(busy.value)return;busy.value=true;error.value='';try{await task()}catch(e:any){error.value=e.message}finally{busy.value=false}}
async function loadGroups(){groups.value=await api(base+'/groups?offset='+groupOffset.value)}
async function loadRows(){
 if(tab.value==='build'){rows.value=null;return}
 const params=new URLSearchParams({offset:String(offsets.value[tab.value]),limit:'50'})
 if(tab.value==='issues'&&kind.value){if(kind.value==='missing')params.set('missing_kind','true');else params.set('kind_node',kind.value)}
 if(tab.value==='tus'){params.set('search',search.value);params.set('zero_only',String(zero.value));if(status.value==='missing')params.set('status_missing','true');else if(status.value)params.set('status_node',status.value)}
 rows.value=await api(base+'/'+tab.value+'?'+params)
}
async function changeTab(value:string){await perform(async()=>{tab.value=value;rows.value=null;selected.value=null;related.value=null;if(value==='issues')await loadGroups();await loadRows();await persist()})}
async function filterRows(){await perform(async()=>{offsets.value[tab.value]=0;selected.value=null;related.value=null;rows.value=null;await loadRows();await persist()})}
async function page(delta:number){await perform(async()=>{offsets.value[tab.value]=Math.max(0,offsets.value[tab.value]+delta*50);rows.value=null;selected.value=null;related.value=null;await loadRows();await persist()})}
async function groupPage(delta:number){await perform(async()=>{groupOffset.value=Math.max(0,groupOffset.value+delta*50);await loadGroups();await persist()})}
async function chooseGroup(item:any){kind.value=item.node===null?'missing':String(item.node);await filterRows()}
async function loadRelated(offset=0){related.value=await api(base+`/related?node=${selected.value.node}&offset=${offset}`)}
async function choose(item:any){await perform(async()=>{selected.value={...item,source:tab.value};showSource.value=false;related.value=null;if(tab.value!=='tus')await loadRelated();await persist()})}
async function relatedPage(offset:number){await perform(()=>loadRelated(offset))}
async function openSymbol(id:string){await perform(async()=>{await persist();emit('symbol',id)})}
onMounted(()=>perform(async()=>{
 stats.value=await api(base)
 const saved=await api(base+'/position')
 if(saved){
  if(tabs.some(x=>x[0]===saved.tab))tab.value=saved.tab
  for(const [target,key] of [[kind,'kind'],[status,'status'],[search,'search']] as const)if(typeof saved[key]==='string')target.value=saved[key]
  zero.value=!!saved.zero&&stats.value.zero_filter_available
  for(const key of ['blockers','issues','tus'])if(Number.isSafeInteger(saved.offsets?.[key])&&saved.offsets[key]>=0)offsets.value[key]=saved.offsets[key]
  if(Number.isSafeInteger(saved.groupOffset)&&saved.groupOffset>=0)groupOffset.value=saved.groupOffset
  if(saved.selected&&Number.isSafeInteger(saved.selected.node)&&saved.selected.source===tab.value)selected.value=saved.selected
 }
 if(tab.value==='issues')await loadGroups()
 await loadRows()
 if(selected.value){const item=rows.value?.items.find((item:any)=>item.node===selected.value.node);selected.value=item?{...item,source:tab.value}:null}
 if(selected.value&&tab.value!=='tus')await loadRelated()
}))
</script>
<template>
 <div class="page-heading"><div><h1>覆盖与诊断</h1><p>基于本归档的原始记录。解析成功不等于变量安全；缺少关联不等于零影响。</p></div></div>
 <p v-if="busy" role="status">正在读取覆盖证据…</p><div v-if="error" role="alert" class="banner error">{{error}} <button :disabled="busy" @click="perform(async()=>{stats=await api(base);await loadRows()})">重新读取覆盖诊断</button></div>
 <section v-if="stats" class="panel" aria-label="覆盖状态">
  <h2>本次归档的覆盖状态</h2><p>引擎分析状态：{{stats.analysis_status||'未归档 / 无法判断'}}；TU记录 {{stats.translation_units?.kind==='list'?stats.translation_units.length:'未归档 / 无法判断'}}；缺口记录 {{stats.unknowns?.kind==='list'?stats.unknowns.length:'未归档 / 无法判断'}}。</p>
  <div class="actions"><span v-for="item in stats.tu_statuses" :key="item.node??'missing'" class="tag">{{tuTitle(item.raw)}} {{item.count}}</span></div>
  <p v-if="stats.tu_status_types>stats.tu_statuses.length" class="muted">状态类型过多，仅列出前50种；全部TU与原始索引仍可分页读取。</p>
  <p v-if="stats.unprojected_unknowns||stats.unprojected_tus" class="banner warning">另有无法投影为对象的原始条目：缺口 {{stats.unprojected_unknowns??'未知'}}、TU {{stats.unprojected_tus??'未知'}}。请查看完整索引，不能将它们忽略为无影响。</p>
 </section>
 <div class="tabs" role="tablist" aria-label="覆盖诊断分组"><button v-for="[value,title] in tabs" :key="value" role="tab" :aria-selected="tab===value" :disabled="busy" @click="changeTab(value)">{{title}}</button></div>
 <section class="panel" :aria-label="tabs.find(x=>x[0]===tab)?.[1]">
  <template v-if="tab==='blockers'"><h2>变量覆盖阻断</h2><p>引擎关联来自报告中的 symbol_ids 与 relevance_proofs；不由界面推断传播范围。</p><p v-if="rows&&!rows.available">阻断集合未归档，无法判断；请查看完整静态报告。</p></template>
  <template v-if="tab==='issues'">
   <h2>解析、别名与硬件缺口</h2><p>直接对象数仅统计记录中可匹配清单的 symbol_id，不代替引擎传播后的影响对象数。</p>
   <div class="coverage-groups"><button :disabled="busy" :aria-pressed="kind===''" @click="kind='';filterRows()">全部原始缺口</button><button v-for="item in groups?.items" :key="item.node??'missing'" :disabled="busy" :aria-pressed="kind===(item.node===null?'missing':String(item.node))" @click="chooseGroup(item)">{{kindTitle(item.raw)}} · {{item.records}}条 / {{item.direct_symbols}}个直接对象 / {{item.unbound_records}}条无匹配身份</button></div>
   <div v-if="groups" class="page-controls"><button :disabled="busy||groupOffset===0" @click="groupPage(-1)">上一页类型</button><span>共 {{groups.total}} 种</span><button :disabled="busy||groups.next_offset===null" @click="groupPage(1)">下一页类型</button></div>
   <p v-if="stats&&stats.unknowns?.kind!=='list'">原始缺口集合未归档为列表，无法判断。</p>
  </template>
  <template v-if="tab==='tus'">
   <h2>全部编译单元</h2><p>关联对象数来自归档变量的 translation_units，含容器和非存储对象；不等于风险变量数。</p>
   <form class="filters" @submit.prevent="filterRows"><label>源文件包含<input v-model="search" :disabled="busy"></label><label>TU解析状态<select v-model="status" aria-label="TU解析状态" :disabled="busy" @change="filterRows"><option value="">全部TU状态</option><option v-for="item in stats?.tu_statuses" :key="item.node??'missing'" :value="item.node===null?'missing':String(item.node)">{{tuTitle(item.raw)}}（{{item.count}}）</option></select></label><button :disabled="busy">筛选编译单元</button></form>
   <label class="coverage-zero"><input type="checkbox" v-model="zero" :disabled="busy||!stats?.zero_filter_available" @change="filterRows">仅零归档关联对象TU</label>
   <p v-if="stats&&!stats.zero_filter_available" class="banner warning">当前不能证明零关联对象：缺少TU来源的对象 {{stats.objects_without_tu_origin}}；同名TU编译变体 {{stats.ambiguous_tu_source_names}}；未记录源文件的TU {{stats.tus_without_source_name}}；集合完整性 {{stats.association_collections_complete?'已记录':'不足'}}。请核对全部TU与编译参数。</p>
   <p v-if="stats&&stats.translation_units?.kind!=='list'">TU集合未归档，无法判断。</p>
  </template>
  <template v-if="tab==='build'"><h2>构建闭包与分析范围</h2><p>目录排除、未入构建文件、头文件和变量清单需分别核对；排除变量定义不能一并删除HAL调用与上下文恢复。</p><p v-if="stats&&!stats.build.length">构建与范围字段未归档；无法从空列表证明闭包完整。</p><EvidenceNode v-for="item in stats?.build" :key="item.key" :scan="scan" :node="item.id" :title="field(item.key)"/></template>
  <template v-else-if="rows">
   <p class="muted">匹配 {{rows.total}} 项；显示 {{rows.items.length?rows.offset+1:0}}–{{rows.offset+rows.items.length}}。空列表不构成安全证明。</p>
   <div class="coverage-table-wrap"><table class="coverage-table"><thead><tr><th>{{tab==='tus'?'源文件 / TU':'缺口类型 / 身份'}}</th><th>{{tab==='tus'?'解析与对象关联':'归档位置与关联'}}</th><th>证据</th></tr></thead><tbody>
    <tr v-for="item in rows.items" :key="item.ordinal" :class="{selected:selected?.node===item.node}"><td><template v-if="tab==='tus'"><strong>{{item.summary.source_file||'源文件未提供或需读取原文'}}</strong><p class="identity">{{item.summary.tu_id}}</p></template><template v-else><strong>{{kindTitle(item.summary.kind)}}</strong><p class="identity">{{item.summary.blocker_id||item.summary.symbol_id||'未提供对象身份'}}</p></template></td><td><template v-if="tab==='tus'"><span class="tag">{{tuTitle(item.summary.parse_status)}}</span><p>归档关联对象 {{item.associated_objects}}{{item.association_complete?'':'（来源不完整，不能认定零影响）'}}</p></template><template v-else><p>{{item.summary.file||'位置未提供或需读取原文'}}{{item.summary.line?':'+item.summary.line:''}}</p><p v-if="tab==='blockers'">报告关联计数 {{item.summary.blocker_fanout??'未提供'}}；身份列表 {{item.archived_symbol_ids_count??'未提供'}}</p><p v-if="tab==='blockers'&&item.archived_symbol_ids_count!==null&&item.summary.blocker_fanout!==undefined&&item.archived_symbol_ids_count!==item.summary.blocker_fanout" class="error">计数与身份列表不一致，请核对原始证明。</p></template></td><td><button :disabled="busy" @click="choose(item)">查看完整证据</button></td></tr>
   </tbody></table></div>
   <p v-if="!rows.items.length">没有符合当前筛选的归档记录。可清除筛选或核对完整索引。</p><div class="page-controls"><button :disabled="busy||rows.offset===0" @click="page(-1)">上一页记录</button><span>每页最多50项</span><button :disabled="busy||rows.next_offset===null" @click="page(1)">下一页记录</button></div>
  </template>
 </section>
 <section v-if="selected" class="panel" aria-label="当前覆盖证据">
  <h2>{{selected.source==='tus'?'编译单元原始证据':'缺口原始证据与关联对象'}}</h2><p v-if="selected.source!=='tus'">修复方向：{{hint(selected.summary?.kind)}}</p><p v-else>核对真实命令、编译器、宏、头文件及原诊断；解析状态仍以归档原值为准。</p>
  <template v-for="(title,key) in detailFields" :key="key"><EvidenceNode v-if="selected.fields?.[key]" :scan="scan" :node="selected.fields[key].id" :title="title"/></template>
  <template v-if="selected.summary?.source_file||selected.summary?.file"><button @click="showSource=!showSource">{{showSource?'收起归档位置代码':'查看归档位置代码'}}</button><SourceViewer v-if="showSource" :key="selected.node" :scan="scan" :file="selected.summary.source_file||selected.summary.file" :line="selected.summary.line||1"/></template>
  <EvidenceNode :key="selected.node" :scan="scan" :node="selected.node" title="当前记录的全部字段与证明"/>
  <template v-if="related"><h3>归档关联身份（{{related.total}}）</h3><p v-if="!related.total">该记录未提供关联身份；不能解释为无影响。</p><article v-for="item in related.items" :key="item.ordinal" class="history-row"><div><strong>{{item.symbol?.name||'对象身份未匹配'}}</strong><p class="identity">{{item.symbol_id}}</p><p v-if="!item.available">{{item.reason}}</p><p v-else>{{item.symbol.definition_file}}:{{item.symbol.definition_line}}</p></div><button v-if="item.available" :disabled="busy" @click="openSymbol(item.symbol_id)">打开关联变量</button></article><div class="page-controls"><button :disabled="busy||related.offset===0" @click="relatedPage(Math.max(0,related.offset-50))">上一页关联</button><span>{{related.offset+related.items.length}} / {{related.total}}</span><button :disabled="busy||related.next_offset===null" @click="relatedPage(related.next_offset)">下一页关联</button></div></template>
 </section>
 <section class="panel"><h2>归档全部事实与报告索引</h2><EvidenceNode v-for="root in roots" :key="root.name" :scan="scan" :node="root.id" :title="root.name==='facts'?'完整事实（调用图、全部TU、覆盖、指针、NVIC）':root.name==='report'?'静态报告与覆盖诊断':'输入与来源记录'"/></section>
</template>
<style scoped>
.coverage-groups{display:flex;flex-wrap:wrap;gap:8px}.coverage-groups [aria-pressed=true]{border-color:#245edb;background:#edf3f9}.coverage-table-wrap{overflow:auto}.coverage-table{width:100%;border-collapse:collapse;text-align:left}.coverage-table th,.coverage-table td{padding:16px 8px;border-bottom:1px solid #d9e1ed;vertical-align:top;overflow-wrap:anywhere}.coverage-table th{color:#667894;font-weight:600}.coverage-table td:first-child{width:43%}.coverage-table tr.selected{background:#edf3f9}.coverage-table p{margin:8px 0}.coverage-table td:last-child{white-space:nowrap}.tabs{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}.tabs [aria-selected=true]{background:#edf3f9;border-color:#245edb}.coverage-zero{display:flex;align-items:center;gap:8px;margin:16px 0}.coverage-zero input[type=checkbox]{width:16px;min-width:16px;margin:0}
</style>
