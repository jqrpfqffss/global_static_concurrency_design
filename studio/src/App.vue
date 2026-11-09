<script setup lang="ts">
import { computed, provide, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, upload, download, label, field } from './api'
import EvidenceNode from './EvidenceNode.vue'
import CallTree from './CallTree.vue'
import CleanupCenter from './CleanupCenter.vue'
import SourceViewer from './SourceViewer.vue'
import FindingCard from './FindingCard.vue'
import TaskCenter from './TaskCenter.vue'
import ReviewCenter from './ReviewCenter.vue'
import SymbolAI from './SymbolAI.vue'
import MigrationCenter from './MigrationCenter.vue'
import MulticoreCenter from './MulticoreCenter.vue'
import LegacyArchive from './LegacyArchive.vue'
import CoverageCenter from './CoverageCenter.vue'
import GitVersions from './GitVersions.vue'
import ContextEditor from './ContextEditor.vue'
import DirectoryBrowser from './DirectoryBrowser.vue'
import WorkspaceDialog from './WorkspaceDialog.vue'
import BuildPreflight from './BuildPreflight.vue'
import ProfileOptions from './ProfileOptions.vue'
import FileExclusions from './FileExclusions.vue'
import ReviewMaterials from './ReviewMaterials.vue'
import ScanIdentity from './ScanIdentity.vue'
import HistoryCenter from './HistoryCenter.vue'
import DataRootSettings from './DataRootSettings.vue'
import StorageUsage from './StorageUsage.vue'
import EvidenceIdentity from './EvidenceIdentity.vue'
import { ReviewDrafts } from './reviewDrafts'
const navigation = [ ['overview','项目概览'], ['projects','工程配置'], ['tasks','扫描任务'], ['variables','变量与风险'], ['coverage','覆盖与诊断'], ['opencode','OpenCode 复核'], ['reviews','人工确认'], ['history','历史与对比'], ['sharing','数据与共享'] ]
const route = ref(location.hash.slice(2) || 'overview'), compact = ref(false)
const bootstrap = ref<any>(null), scans = ref<any[]>([]), scan = ref(localStorage.getItem('ecra-scan') || ''), summary = ref<any>(null)
const error = ref(''), notice = ref(''), busy = ref(false), loading = ref(false)
const summaryError = ref('')
provide('workspace-error',error)
const archiveCompression=ref('compact')
const multicoreRef=ref<InstanceType<typeof MulticoreCenter>|null>(null)
const items = ref<any[]>([]), total = ref(0), offset = ref(0), search = ref(''), classification = ref(''), humanFilter = ref(''), selected = ref<any>(null)
const defaultFilters=():Record<string,string>=>({handling_status:'',file:'',function:'',context:'',coverage:'',ai_state:'',current_result:'',diff:'',symbol_id:'',sort:'priority',order:'asc'})
const extra=ref<Record<string,string>>(defaultFilters())
const human = ref<any>(null), reviewer = ref(localStorage.getItem('ecra-reviewer') || ''), comment = ref(''), handling = ref('TODO')
const drafts=new ReviewDrafts(), draftCount=ref(0), draftWarning=ref('')
let editing:{scan:string,symbol:string,fingerprint:string,heads:string,savedHandling:string}|null=null
let selectionGeneration=0
const headsKey=(value:any)=>JSON.stringify((value.heads||[]).map((e:any)=>e.event_id).sort())
watch([comment,handling],()=>{
  if(!editing)return
  drafts.update(editing.scan,editing.symbol,{comment:comment.value,handling:handling.value,fingerprint:editing.fingerprint,heads:editing.heads},editing.savedHandling)
  draftCount.value=drafts.size
},{flush:'sync'})
function leavingWithDrafts(event:BeforeUnloadEvent){if(drafts.size){event.preventDefault();event.returnValue=''}}
const accesses = ref<any>(null), findings = ref<any>(null), staticFields = ref<any[]>([]), storage = ref<any>(null), fromCoverage=ref(false)
const sourceLocation=ref<any>(null), split=ref(Number(localStorage.getItem('ecra-split'))||38)
function resizeSplit(event:PointerEvent){const el=event.currentTarget as HTMLElement;if(event.type==='pointerdown')el.setPointerCapture(event.pointerId);if(event.buttons===1){const rect=el.parentElement!.getBoundingClientRect();split.value=Math.max(30,Math.min(46,100*(event.clientX-rect.left)/rect.width));localStorage.setItem('ecra-split',String(split.value))}}
function splitKey(event:KeyboardEvent){if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();split.value=Math.max(30,Math.min(46,split.value+(event.key==='ArrowLeft'?-1:1)));localStorage.setItem('ecra-split',String(split.value))}}
function openSource(location:any){sourceLocation.value=location;detailTab.value='source'}
const detailTab=ref('access'), sourceRef=ref<any>(null), priorityItems=ref<any[]>([])
const apiScan = computed(() => `/scans/${encodeURIComponent(scan.value)}`)
const currentScan = computed(() => scans.value.find(x => x.scan_id === scan.value))
const scanReady = computed(() => !!scan.value && summary.value?.binding?.scan_id === scan.value)
function requireScanReady(){if(!scanReady.value||summary.value.legacy_degraded)throw Error('当前结果尚未成功读取，无法查看变量或保存确认。请重试读取，或从历史与对比选择有效结果。')}
const isWorkbench = computed(() => route.value === 'variables' || route.value === 'reviews')
const reviewExpanded=ref(false)
const evidenceHints:Record<string,string>={protection_details:'核对关中断、锁和保护范围是否覆盖冲突访问。',protections:'已恢复的保护措施；是否有效须看作用范围。',concurrency_relations:'哪些入口可能交错执行，以及成立条件。',blocking_evidence:'这些条件阻止工具证明安全，需要优先核实。',unknowns:'当前分析缺少的事实；未知不能当作无风险。',initialization:'区分启动期初始化与运行期共享访问。',nvic:'核对中断优先级、分组和屏蔽状态。',multi_field_coherence:'多个字段是否必须作为整体保持一致。'}
const usefulEvidence=computed(()=>staticFields.value.filter(item=>(item.kind==='object'||item.kind==='list')&&item.total!==0&&evidenceHints[item.key]))
const filtersOpen=ref(false),diffOpen=ref(false),focusEvidence=ref(false),sharingTab=ref('exchange'),rangeTab=ref('directories')
const workbenchElement=ref<HTMLElement|null>(null),minimumPaneHeight=ref(600)
let paneObserver:ResizeObserver|null=null
watch([selected,workbenchElement,reviewExpanded],async()=>{
  paneObserver?.disconnect();await nextTick()
  const panel=workbenchElement.value?.querySelector('.detail-panel')
  if(!panel||!selected.value){minimumPaneHeight.value=600;return}
  const fixed=Array.from(panel.querySelectorAll<HTMLElement>(':scope > .detail-summary,:scope > .detail-tabs,:scope > .review-controls'))
  // Leave room for the signature buttons on laptop windows while the form is
  // open. The evidence pane still grows with the available window height.
  const measure=()=>{minimumPaneHeight.value=Math.ceil((reviewExpanded.value?160:302)+fixed.reduce((sum,element)=>sum+element.getBoundingClientRect().height,0))}
  paneObserver=new ResizeObserver(measure);fixed.forEach(element=>paneObserver!.observe(element));measure()
},{flush:'post'})
onUnmounted(()=>paneObserver?.disconnect())
const filterDescription=computed(()=>[listScope()==='pending'?'仅待人工确认':'',classification.value&&label(classification.value),humanFilter.value&&label(humanFilter.value),...Object.entries(extra.value).filter(([key,value])=>value&&!['sort','order','symbol_id'].includes(key)).map(([key,value])=>({file:'文件',function:'函数',context:'上下文',coverage:'覆盖',ai_state:'OpenCode',current_result:'当前结论',handling_status:'处理',diff:'Diff'}[key]||key)+'：'+(['file','function','context'].includes(key)?value:key==='diff'?({selected:'影响清单',direct:'确定依赖',conservative:'保守潜在影响'}[value]||value):label(value)))].filter(Boolean).join(' · ')||'全部对象')
const selectedIndex=computed(()=>items.value.findIndex(item=>item.symbol_id===selected.value?.symbol_id))
async function adjacent(direction:number){await run(async()=>{let index=selectedIndex.value+direction;if(index<0){if(!offset.value)return;offset.value=Math.max(0,offset.value-50);await loadList();index=items.value.length-1}else if(index>=items.value.length){if(offset.value+items.value.length>=total.value)return;offset.value+=50;await loadList();index=0}if(items.value[index])await loadSelection(items.value[index])})}
async function clearFilters(){search.value='';classification.value='';humanFilter.value='';extra.value=defaultFilters();await filter()}
function returnList(){selectionGeneration++;editing=null;selected.value=null;human.value=null;focusEvidence.value=false}
const pending = computed(() => summary.value?.pending_count || 0)
const confirmation=(item:any)=>label(item.confirmation_state||item.human?.decision||'PENDING')
const resultOrigin=(item:any)=>({OPENCODE:'OpenCode',STATIC:'静态证据',MIXED:'静态与OpenCode'}[String(item.result_source)]||'归档证据')
function listScope(){return route.value==='reviews'?(['CONFIRMED_RISK','CONFIRMED_SAFE','CONFLICT'].includes(humanFilter.value)?'all':'pending'):'all'}
const wizardStep = ref(1), projectName = ref(''), projectRoot = ref(''), projectCore=ref(''), buildMode = ref('cmake'), toolchain = ref(''), target = ref(''), variant = ref('Debug')
const include = ref(''), exclude = ref(''), baseRef = ref(''), currentRef = ref('HEAD'), yaml = ref(''), profileCheck = ref<any>(null), profileList = ref<any[]>([]), profileId = ref(''), profileRevision = ref('')
const includeUncommitted=ref(false)
const savedYaml=ref(''),profileError=ref(''),taskFocus=ref(sessionStorage.getItem('ecra-task-focus')||'')
const materialsRef=ref<InstanceType<typeof ReviewMaterials>|null>(null)
const preflightReady=ref(''),preflightRef=ref<InstanceType<typeof BuildPreflight>|null>(null),launchPending=ref(false),launchStatus=ref('')
let launchRequest:{id:string,revision:string,yaml:string}|null=null
const configInventory=ref<any[]>([])
const optionSpecs=ref<any[]>([]),options=ref<Record<string,any>>({}),optionErrors=ref<Record<string,string>>({})
function optionValidity(value:{path:string,message:string}){optionErrors.value[value.path]=value.message}
function assertOptions(){const value=Object.values(optionErrors.value).find(Boolean);if(value)throw Error(value)}
const formSnapshot=ref<Record<string,any>|null>(null),yamlBackup=ref<any>(null)
const initialContexts=()=>[{origin_id:null as string|null,id:'main',kind:'MAIN',functions:['main']}]
const contextRows=ref(initialContexts()),contextsEditable=ref(true),contextsReason=ref(''),systemHeaders=ref('on')
const directoryMode=ref<''|'project'|'include'|'exclude'|'database'|'toolchain'|'exclude-file'>('')
function excludedFilesSelected(values:{path:string,relative:string|null}[]){
 const existing=options.value['analysis.exclude_files'];if(existing!==null&&existing!==undefined&&(!Array.isArray(existing)||existing.some(x=>typeof x!=='string'))){error.value='请先修复排除文件列表的格式。';return}
 const files=[...(existing||[])];for(const value of values){if(!value.relative)continue;const relative=value.relative.replace(/\\/g,'/');if(!files.some((path:string)=>path.replace(/\\/g,'/')===relative))files.push(relative)}
 options.value={...options.value,'analysis.exclude_files':files};directoryMode.value='';notice.value='已加入文件排除；保存配置并开始新扫描后生效。'
}
function directorySelected(value:{path:string,relative:string|null}){
  if(directoryMode.value==='project')projectRoot.value=value.path
  else if(directoryMode.value==='database')target.value=value.path
  else if(directoryMode.value==='toolchain')toolchain.value=value.path
  else{
    const target=directoryMode.value==='include'?include:exclude,entry=value.relative||'.',lines=directoryLines(target.value)
    if(!lines.includes(entry))target.value=[...lines,entry].join('\n')
    notice.value='已选择相对工程目录 '+entry+'；仅在下一步同步、检查并保存后生效。'
  }
  directoryMode.value=''
}
const editedProfile=computed(()=>profileList.value.find(p=>p.id===profileId.value&&p.revision===profileRevision.value))
const savedProfileReady=computed(()=>!!editedProfile.value&&savedYaml.value===yaml.value)
const isSample=computed(()=>summary.value?.binding?.profile_id==='builtin-stm32-demo'||currentScan.value?.profile_id==='builtin-stm32-demo')
async function openSample(){const origin=route.value;await run(async()=>{const result=await api('/sample/open','POST',{});scan.value=result.scan_id;await refresh();if(route.value===origin)go('overview');notice.value='已打开内置教学示例；内容来自真实扫描归档，保留未知与覆盖缺口。'})}
async function openScan(id:string){const origin=route.value;await run(async()=>{scan.value=id;await refresh();if(route.value===origin)go('overview')})}
function newProject(){newProfile();go('projects')}
const repeatProfile=computed(()=>currentScan.value?.mode==='LOCAL_SNAPSHOT'?profileList.value.find(p=>p.project_id===summary.value?.binding.project_id&&p.id===summary.value?.binding.profile_id):null)
function rememberTask(id:string){taskFocus.value=id;sessionStorage.setItem('ecra-task-focus',id)}
function openTasks(id?:string){if(id)rememberTask(id);go('tasks')}
async function loadProfiles(){try{profileList.value=(await api('/profiles')).items;profileError.value=''}catch(e:any){profileList.value=[];profileError.value='本机配置读取失败：'+e.message}}
async function launchProfile(profile:any){await run(async()=>{
  if(!profile)throw Error('没有可启动的已保存配置；请检查并保存当前配置。')
  const task=await api('/tasks','POST',{project_id:profile.project_id,profile_id:profile.id,revision:profile.revision,resources:{preset:'auto'}})
  if(!task.id)throw Error('启动器未返回真实任务身份，请核对任务中心。')
  rememberTask(task.id);go('tasks')
})}
function go(path: string) { location.hash = '/' + path; route.value = path; compact.value = false; error.value = ''; notice.value = '' }
function hashed() { route.value = location.hash.slice(2) || 'overview' }
async function copyName() { if (selected.value) await navigator.clipboard.writeText(selected.value.name) }
async function run(task: () => Promise<any>) {
  if (busy.value) { error.value = '上一项操作仍在进行，请等待完成后重试。'; return }
  busy.value = true; error.value = ''; notice.value = ''
  try { return await task() } catch (e: any) { if (notice.value.startsWith('正在')) notice.value = ''; error.value = e.message } finally { busy.value = false }
}
async function readPage(task: () => Promise<any>) { const startedRoute=route.value; try { await task() } catch (e: any) { if(!busy.value && !error.value && route.value===startedRoute) error.value='页面信息读取失败：'+e.message } }
let refreshGeneration=0
async function refresh() {
  const generation=++refreshGeneration, result=await api('/scans')
  if(generation!==refreshGeneration)return
  scans.value = result.items
  if (!scans.value.some(x => x.scan_id === scan.value)) scan.value = scans.value.find(x=>x.state!=='FAILED'&&x.can_open!==false)?.scan_id || ''
  if (scan.value) {
    const id=scan.value,base=`/scans/${encodeURIComponent(id)}`
    let value
    try { value=await api(base+'/summary');if(!value.result_counts)throw Error('当前仍是旧版后台，请关闭原启动窗口并从新版 ECRA.cmd 重启。') }
    catch(e:any){if(generation===refreshGeneration&&scan.value===id){invalidateResult(e.message)}throw e}
    if(generation!==refreshGeneration||scan.value!==id)return
    summary.value=value;summaryError.value=''
    if(!localStorage.getItem('ecra-filters-'+id))extra.value.diff=value.diff?'selected':''
    const priorities=value.legacy_degraded?{items:[]}:await api(base+'/symbols?limit=5&review_scope=pending')
    if(generation!==refreshGeneration||scan.value!==id)return
    priorityItems.value=priorities.items;if(!value.legacy_degraded)await loadList()
  }
  else summary.value = null
  await loadProfiles()
}
let listRequest=0
async function loadList() {
  requireScanReady()
  const id=scan.value,mine=++listRequest
  loading.value = true
  try {
    const value = await api(apiScan.value + `/symbols?${new URLSearchParams({search:search.value,classification:classification.value,human_decision:humanFilter.value,offset:String(offset.value),limit:'50',...extra.value,review_scope:listScope()})}`)
    if(scan.value===id&&mine===listRequest){items.value=value.items;total.value=value.total}
  } finally { if(mine===listRequest)loading.value=false }
}
async function rememberList(){
  localStorage.setItem('ecra-filters-'+scan.value,JSON.stringify({search:search.value,classification:classification.value,human:humanFilter.value,extra:extra.value}))
  await api(apiScan.value+'/position','PUT',{symbol_id:selected.value?.symbol_id||'',search:search.value,classification:classification.value,human_filter:humanFilter.value,offset:offset.value,extra:extra.value})
}
function restoreFilters(id:string){
  search.value='';classification.value='';humanFilter.value='';extra.value=defaultFilters()
  try{const state=JSON.parse(localStorage.getItem('ecra-filters-'+id)||'null');if(state){search.value=state.search||'';classification.value=state.classification||'';humanFilter.value=state.human||'';extra.value={...defaultFilters(),...state.extra}}}catch{}
}
async function filter() { await run(async () => { offset.value = 0; await loadList(); await rememberList() }) }
async function searchList(){extra.value.symbol_id='';await filter()}
async function openCoverageSymbol(id:string){
  await run(async()=>{
    requireScanReady()
    const item=await api(apiScan.value+'/symbol?symbol_id='+encodeURIComponent(id))
    search.value='';classification.value='';humanFilter.value='';extra.value={...defaultFilters(),symbol_id:id};offset.value=0
    fromCoverage.value=true;go('variables');await loadList();await loadSelection(item)
  })
}
async function openHistorySymbol(id:string,symbol:string){
  await run(async()=>{
    scan.value=id;await refresh()
    if(summary.value?.binding?.scan_id!==id)throw Error('所选历史归档已不可用，请返回历史重新查询。')
    const item=await api(apiScan.value+'/symbol?symbol_id='+encodeURIComponent(symbol))
    search.value='';classification.value='';humanFilter.value='';extra.value={...defaultFilters(),symbol_id:symbol};offset.value=0
    fromCoverage.value=false;go('variables');await loadList();await loadSelection(item)
  })
}
async function select(item: any) {
  await run(() => loadSelection(item))
}
async function loadSelection(item: any) {
    requireScanReady()
    const generation=++selectionGeneration,id=scan.value,base=apiScan.value,symbol=encodeURIComponent(item.symbol_id)
    editing=null;selected.value=item;human.value=null;comment.value='';handling.value='TODO';draftWarning.value=''
    staticFields.value=[];accesses.value=null;findings.value=null;sourceRef.value=null
    sourceLocation.value={file:item.definition_file||'',line:item.definition_line||1}
    const [review,fields,access,found,source]=await Promise.all([
      api(base+'/human?symbol_id='+symbol),api(base+'/nodes/'+item.node+'?limit=200'),
      api(base+'/records/accesses?symbol_id='+symbol),api(base+'/records/findings?dataset=report&symbol_id='+symbol),
      api(base+'/source?file='+encodeURIComponent(item.definition_file||''))])
    if(generation!==selectionGeneration||scan.value!==id||selected.value?.symbol_id!==item.symbol_id)return
    human.value=review;staticFields.value=fields.items;accesses.value=access;findings.value=found;sourceRef.value=source
    detailTab.value=item.ai_answer_count?'ai':'access'
    const draft=drafts.get(id,item.symbol_id),heads=headsKey(review)
    comment.value=draft?.comment||'';handling.value=draft?.handling||review.handling_status
    if(draft&&(draft.fingerprint!==review.fingerprint||draft.heads!==heads))draftWarning.value='草稿对应的证据或人工记录已变化。文字已保留，请重新核对后再确认。'
    editing={scan:id,symbol:item.symbol_id,fingerprint:review.fingerprint,heads,savedHandling:review.handling_status}
    await rememberList()
}
async function saveDecision(decision: string, undo = false) {
  await run(async () => {
    requireScanReady()
    if(!human.value||!editing||editing.scan!==scan.value||editing.symbol!==selected.value?.symbol_id)throw Error('当前对象证据尚未读完，请重新选择对象后再确认。')
    const submittedComment=comment.value,submittedScan=scan.value,submittedSymbol=selected.value.symbol_id,base=apiScan.value
    const result = await api(base + '/human', 'POST', { symbol_id: submittedSymbol, fingerprint: human.value.fingerprint,
      decision, handling_status: handling.value, reviewer: reviewer.value, comment: submittedComment, expected_heads: human.value.heads.map((e: any) => e.event_id), resolve: human.value.conflict, undo })
    if (!result.saved) throw new Error('确认尚未提交')
    drafts.remove(submittedScan,submittedSymbol);draftCount.value=drafts.size
    if(scan.value===submittedScan&&selected.value?.symbol_id===submittedSymbol){editing=null;human.value=null;comment.value='';draftWarning.value=''}
    notice.value='已保存，静态分类保持独立。'
    localStorage.setItem('ecra-reviewer', reviewer.value)
    const saved=await api(base + '/human?symbol_id=' + encodeURIComponent(submittedSymbol))
    if(scan.value!==submittedScan)return
    if(selected.value?.symbol_id===submittedSymbol){human.value=saved;handling.value=saved.handling_status;editing={scan:submittedScan,symbol:submittedSymbol,fingerprint:saved.fingerprint,heads:headsKey(saved),savedHandling:saved.handling_status}}
    const [updated,priorities,meta]=await Promise.all([api(base+'/summary'),api(base+'/symbols?limit=5&review_scope=pending'),api(base+'/symbol?symbol_id='+encodeURIComponent(submittedSymbol))])
    if(scan.value!==submittedScan)return
    summary.value=updated;priorityItems.value=priorities.items
    if(selected.value?.symbol_id===submittedSymbol)selected.value={...selected.value,...meta}
    await loadList()
  })
}
async function continueReview(historyId?:unknown) {
  await run(async()=>{
    if(typeof historyId==='string'){scan.value=historyId;await refresh();if(scan.value!==historyId||summary.value?.binding?.scan_id!==historyId)throw Error('所选历史归档已不可用；请返回历史重新查询。')}
    requireScanReady()
    go('reviews');search.value='';classification.value='';humanFilter.value='';extra.value=defaultFilters();offset.value=0
    const position=await api(apiScan.value+'/position');await loadList()
    const item=items.value.find(x=>x.symbol_id===position?.symbol_id)||items.value[0]
    if(item)await loadSelection(item);else returnList()
  })
}
async function drillResult(result:string,manual=false){
  search.value='';classification.value='';humanFilter.value='';extra.value={...defaultFilters(),current_result:result};offset.value=0;returnList();go(manual?'reviews':'variables')
  await run(async()=>{await loadList();await rememberList()})
}
async function showHumanRecords(state:string){
  go('variables');await nextTick();search.value='';classification.value='';humanFilter.value=state;extra.value=defaultFilters();offset.value=0;returnList();await filter()
}
async function drill(state:string,humanState=''){search.value='';extra.value=defaultFilters();classification.value=state;humanFilter.value=humanState;offset.value=0;go(humanState?'reviews':'variables');await run(async()=>{await loadList();await rememberList()})}
async function page(delta: number) { offset.value = Math.max(0, offset.value + delta * 50); await run(async()=>{await loadList();await rememberList()}) }
async function importFile(event: Event, delta = false) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]
  if (!file) return
  await run(async () => {
    notice.value = '正在校验归档结构、完整证据与人工历史…'
    let result
    try { result=await upload(delta ? apiScan.value + '/delta/import' : '/import', file) }
    catch(e:any){throw Error((delta?'确认增量':'完整结果包')+'导入未完成。请核对'+(delta?'增量与当前归档的归属、':'')+'文件是否传输完整及数据盘可用空间，再重新选择文件重试；仍失败时请提供下方诊断信息。\n'+e.message)}
    scan.value=result.scan_id;notice.value=`导入已提交：${result.scan_id}；新增人工事件 ${result.imported_events}`;await refresh()
  })
  input.value = ''
}
async function exportFile(kind: string) {
  await run(async () => { const result = await api(apiScan.value + '/export', 'POST', { kind, ...(kind==='full'?{compression:archiveCompression.value}:{}) }); await download(result.download, result.filename); notice.value = result.compression_fallback?'已生成完整包并开始下载；为保证能正常导入，已使用快速压缩。':'已生成一致快照包并开始下载。' })
}
function buildYaml() {
  const q = (s: string) => JSON.stringify(s)
  yaml.value = `# 高级字段可在下方完整编辑\nversion: 1\nproject:\n  name: ${q(projectName.value)}\n  root: ${q(projectRoot.value)}\n${projectCore.value?'  core: '+q(projectCore.value)+'\n':''}analysis:\n  output: {location: user}\n  include_dirs: ${JSON.stringify(directoryLines(include.value))}\n  exclude_dirs: ${JSON.stringify(directoryLines(exclude.value))}\n`
  if (buildMode.value === 'cmake') yaml.value += `  cmake:\n    generator: Ninja\n    build: true\n    build_type: ${q(variant.value)}\n${toolchain.value ? '    toolchain_file: '+q(toolchain.value)+'\n' : ''}${target.value ? '    target: '+q(target.value)+'\n' : ''}`
  else yaml.value += `  compile_database: ${q(target.value || 'compile_commands.json')}\n`
  if(systemHeaders.value!=='default')yaml.value+=`  auto_system_includes: ${systemHeaders.value==='on'}\n`
  if (baseRef.value||includeUncommitted.value) yaml.value += `  git_diff:\n    enabled: ${Boolean(baseRef.value)}\n${baseRef.value?'    base_ref: '+q(baseRef.value)+'\n':''}    current_ref: ${q(currentRef.value)}\n    include_uncommitted: ${includeUncommitted.value}\n`
  yaml.value += `contexts: ${JSON.stringify(contextRows.value.map(({id,kind,functions})=>({id,kind,functions})))}\nreview:\n  enabled: false\n`
}
function directoryLines(value:string){return value.split(/\r?\n/).filter(line=>line.length>0)}
function currentForm(){return {project_name:projectName.value,project_root:projectRoot.value,project_core:projectCore.value,build_mode:buildMode.value,target:target.value,toolchain:toolchain.value,variant:variant.value,include_dirs:directoryLines(include.value),exclude_dirs:directoryLines(exclude.value),base_ref:baseRef.value,current_ref:currentRef.value,include_uncommitted:includeUncommitted.value,contexts:contextRows.value.map(row=>({...row,functions:[...row.functions]})),system_headers:systemHeaders.value,options:options.value}}
function changeBuildMode(){target.value=''}
async function previousStep(){if(wizardStep.value!==4){wizardStep.value--;return}await run(async()=>{
  const raw=yaml.value,state=await api('/profiles/form','POST',{yaml:raw})
  if(yaml.value!==raw)throw Error('配置已变化，请重新返回表单。')
  if(!state.editable)throw Error(state.reason)
  configInventory.value=state.inventory;const f=state.form;projectName.value=f.project_name;projectRoot.value=f.project_root;projectCore.value=f.project_core;buildMode.value=f.build_mode;target.value=f.target;toolchain.value=f.toolchain;variant.value=f.variant;include.value=f.include_dirs.join('\n');exclude.value=f.exclude_dirs.join('\n');baseRef.value=f.base_ref;currentRef.value=f.current_ref
  includeUncommitted.value=f.include_uncommitted
  contextRows.value=f.contexts;contextsEditable.value=state.contexts_editable;contextsReason.value=state.contexts_reason;systemHeaders.value=f.system_headers;options.value=f.options;optionErrors.value={}
  formSnapshot.value=f;wizardStep.value=3
})}
async function nextStep(){if(wizardStep.value<3){wizardStep.value++;return}await run(async()=>{
  assertOptions()
  if(!yaml.value){buildYaml();const values=Object.fromEntries(Object.entries(options.value).filter(([path,value])=>value!==null&&value!==undefined&&(buildMode.value==='cmake'||!path.startsWith('analysis.cmake.'))));if(Object.keys(values).length)yaml.value=(await api('/profiles/form-merge','POST',{yaml:yaml.value,changes:{options:values}})).yaml;formSnapshot.value=currentForm()}
  else{
    if(!formSnapshot.value)throw Error('请先从高级YAML返回，读取当前表单值。')
    const form=currentForm(),changes:Record<string,any>={}
    for(const [key,value] of Object.entries(form))if(JSON.stringify(value)!==JSON.stringify(formSnapshot.value[key]))changes[key]=value
    if(changes.options){changes.options=Object.fromEntries(Object.entries(form.options).filter(([path,value])=>JSON.stringify(value??null)!==JSON.stringify(formSnapshot.value!.options?.[path]??null)&&(form.build_mode==='cmake'||!path.startsWith('analysis.cmake.'))));if(!Object.keys(changes.options).length)delete changes.options}
    if(changes.build_mode){changes.target=form.target;if(form.build_mode==='cmake'){changes.toolchain=form.toolchain;changes.variant=form.variant}}
    if(form.build_mode==='database'){delete changes.toolchain;delete changes.variant}
    const raw=yaml.value,result=await api('/profiles/form-merge','POST',{yaml:raw,changes})
    if(yaml.value!==raw)throw Error('配置已变化；同步结果未应用，请重试。')
    if(result.backup)yamlBackup.value=result.backup
    yaml.value=result.yaml;formSnapshot.value=form
    notice.value=result.build_mode_changed?'已同步并切换构建方式；旧构建分支已保存到原文备份，可恢复后重新检查。':result.changed_paths.length?'已同步所改字段；完整原文备份可恢复。':'表单未修改，完整原文保持一致。'
  }
  configInventory.value=(await api('/profiles/form','POST',{yaml:yaml.value})).inventory;profileCheck.value=null;wizardStep.value=4
})}
async function restoreYaml(){await run(async()=>{const identity=yamlBackup.value.id,result=await api('/profiles/drafts/'+encodeURIComponent(identity));yaml.value=result.yaml;formSnapshot.value=null;profileCheck.value=null;wizardStep.value=4;notice.value='已恢复同步前完整原文；请重新检查并保存。'})}
async function checkProfile() { await run(async () => { const raw=yaml.value,result=await api('/profiles/check', 'POST', { yaml: raw });if(yaml.value===raw)profileCheck.value=result }) }
async function saveProfile() { await run(async () => { if(!profileCheck.value)throw Error('请重新检查当前配置。');const raw=yaml.value,anotherProject=editedProfile.value&&editedProfile.value.project_id!==profileCheck.value.project_id;const result = await api('/profiles', 'POST', { yaml: raw, id: anotherProject?undefined:profileId.value || undefined, revision: anotherProject?undefined:profileRevision.value || undefined }); profileId.value = result.id; profileRevision.value = result.revision; savedYaml.value=raw;await loadProfiles();notice.value = anotherProject?'已另存此工程配置；原工程配置仍保留。':'配置已保存。请检查真实构建并查看执行计划，再开始扫描；资源预算可在任务中心调整。' }) }
async function openProfile(profile: any) { if(busy.value)return;profileId.value = profile.id; profileRevision.value = profile.revision; yaml.value = profile.yaml;savedYaml.value=profile.yaml;formSnapshot.value=null;yamlBackup.value=null;wizardStep.value = 4; profileCheck.value = null;error.value='';notice.value='';try{configInventory.value=(await api('/profiles/form','POST',{yaml:profile.yaml})).inventory}catch(e:any){error.value=e.message} }
function newProfile(){if(busy.value)return;profileId.value='';profileRevision.value='';savedYaml.value='';yaml.value='';profileCheck.value=null;formSnapshot.value=null;yamlBackup.value=null;options.value={};optionErrors.value={};projectName.value='';projectRoot.value='';projectCore.value='';buildMode.value='cmake';target.value='';toolchain.value='';variant.value='Debug';include.value='';exclude.value='';baseRef.value='';currentRef.value='HEAD';includeUncommitted.value=false;contextRows.value=initialContexts();contextsEditable.value=true;contextsReason.value='';systemHeaders.value='on';wizardStep.value=1;notice.value='';error.value=''}
watch(yaml,()=>{profileCheck.value=null;savedYaml.value='';preflightReady.value='';launchRequest=null;launchPending.value=false;launchStatus.value=''},{flush:'sync'})
async function importProfile(event:Event){const input=event.target as HTMLInputElement,file=input.files?.[0];if(!file)return;await run(async()=>{if(file.size>4*1024**2)throw Error('配置文件不能超过4MiB');const raw=await file.text();const state=await api('/profiles/form','POST',{yaml:raw});newProfile();configInventory.value=state.inventory;yaml.value=raw;wizardStep.value=4;notice.value='已载入完整配置原文；可返回表单逐项调整，再检查并开始扫描。'});input.value=''}
async function configureMaterials(){await materialsRef.value?.show()}

async function prepareAndLaunch(){
 if(launchPending.value||busy.value)return
 launchStatus.value='检查配置…'
 await checkProfile();if(!profileCheck.value){launchStatus.value='配置检查未通过，请查看上方原因。';return}
 if(!savedProfileReady.value)await saveProfile()
 if(!savedProfileReady.value){launchStatus.value='配置未保存，请查看上方原因。';return}
 const p=editedProfile.value;launchRequest={id:p.id,revision:p.revision,yaml:yaml.value};launchPending.value=true;launchStatus.value='正在检查真实构建；通过后自动开始扫描，可在右侧查看进度。'
 await nextTick();await preflightRef.value?.start()
}
async function preflightChanged(id:string){
 preflightReady.value=id
 const request=launchRequest
 if(!id||!request)return
 if(route.value!=='projects'||request.yaml!==yaml.value||request.id!==editedProfile.value?.id||request.revision!==editedProfile.value?.revision){launchRequest=null;launchPending.value=false;return}
 launchRequest=null;launchPending.value=false;launchStatus.value='构建检查通过，正在提交扫描…';await launchProfile(editedProfile.value)
}
function preflightFailed(){launchRequest=null;launchPending.value=false;launchStatus.value='真实构建检查未通过，请查看右侧原因；修复后可重新开始。'}
function keydown(event: KeyboardEvent) { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f' && isWorkbench.value) { event.preventDefault(); document.getElementById('variable-search')?.focus() } if (event.key === 'Escape' && !document.querySelector('dialog[open]')) { compact.value = false;returnList() } }
function invalidateResult(message=''){summaryError.value=message;summary.value=null;items.value=[];total.value=0;priorityItems.value=[];returnList();listRequest++;loading.value=false}
watch(scan, () => { invalidateResult();localStorage.setItem('ecra-scan', scan.value);fromCoverage.value=false;offset.value=0;restoreFilters(scan.value) },{flush:'sync'})
let projectionPolling=false,projectionRefreshQueued=false,projectionTimer:ReturnType<typeof setInterval>|undefined
async function syncProjection(force=false){
  if(!scanReady.value||summary.value.legacy_degraded)return
  // A page change can arrive during an older refresh or a user submission.
  // Keep that forced refresh even if the committed result revision is equal.
  if(projectionPolling||busy.value){if(force)projectionRefreshQueued=true;return}
  force=force||projectionRefreshQueued;projectionRefreshQueued=false
  projectionPolling=true
  const id=scan.value,base=apiScan.value
  try{
    const revision=await api(base+'/result-revision')
    if(scan.value!==id||(!force&&revision.result_revision===summary.value?.result_revision))return
    let value
    try {value=await api(base+'/summary');if(!value.result_counts)throw Error('当前仍是旧版后台，请关闭原启动窗口并从新版 ECRA.cmd 重启。')}
    catch(e:any){if(scan.value===id)invalidateResult(e.message);throw e}
    const priorities=await api(base+'/symbols?limit=5&review_scope=pending')
    if(scan.value!==id)return
    summary.value=value;summaryError.value='';priorityItems.value=priorities.items
    await loadList()
    if(!items.value.length&&offset.value>0){offset.value=0;await loadList()}
    if(selected.value){
      const symbol=selected.value.symbol_id,meta=await api(base+'/symbol?symbol_id='+encodeURIComponent(symbol))
      if(scan.value===id&&selected.value?.symbol_id===symbol){
        selected.value={...selected.value,...meta}
        if(human.value&&headsKey(meta.human)!==headsKey(human.value))draftWarning.value='人工记录已在其它窗口变化。当前草稿和原提交依据已保留，请重新打开对象核对后保存。'
      }
    }
  }finally{
    projectionPolling=false
    if(projectionRefreshQueued&&!busy.value)queueMicrotask(()=>readPage(()=>syncProjection()))
  }
}
function resultChanged(id?:string){if(!id||id===scan.value)readPage(()=>syncProjection(true))}
watch(route,(value,previous)=>{
  if(value==='reviews'&&previous!=='reviews'){search.value='';classification.value='';humanFilter.value='';extra.value=defaultFilters();offset.value=0;listRequest++;items.value=[];total.value=0;returnList()}
  launchRequest=null;launchPending.value=false
  if(scan.value&&['overview','variables','reviews','opencode'].includes(route.value))readPage(()=>syncProjection(true))
  if(route.value==='sharing'||route.value==='settings')readPage(async()=>{storage.value=await api('/storage')})
  if(route.value==='projects')readPage(async()=>{profileList.value=(await api('/profiles')).items})
})

onMounted(async () => { window.addEventListener('beforeunload',leavingWithDrafts); window.addEventListener('hashchange', hashed); window.addEventListener('keydown', keydown); restoreFilters(scan.value); await run(async () => { bootstrap.value = await api('/bootstrap');optionSpecs.value=(await api('/profiles/options')).items; await refresh() });projectionTimer=setInterval(()=>{if(!document.hidden)readPage(()=>syncProjection())},2000) })
onUnmounted(() => { if(projectionTimer)clearInterval(projectionTimer);window.removeEventListener('beforeunload',leavingWithDrafts); window.removeEventListener('hashchange', hashed); window.removeEventListener('keydown', keydown) })
</script>

<template>
  <div class="shell">
    <aside :class="{ expanded: compact }"><div class="brand">ECRA <span>Studio</span></div><p class="brand-note">并发风险分析工作台</p>
      <nav aria-label="主导航"><a v-for="[id,title] in navigation" :key="id" :href="'#/'+id" :aria-current="route===id ? 'page' : undefined" @click="go(id)">{{ title }}</a></nav>
      <div class="sidebar-bottom"><a href="#/settings" @click="go('settings')">设置与验收状态</a><small>本地数据 · 中文<br>开发预览 · 发布门禁未通过</small></div>
    </aside>
    <div class="main-shell"><header><button class="menu" aria-label="展开导航" @click="compact=!compact">☰</button><ScanIdentity :key="scan" :scan="scan" :binding="summary?.binding?.scan_id===scan?summary.binding:null" :identity="summary?.binding?.scan_id===scan?summary.identity:null" :mode="currentScan?.mode||''" :unavailable="!!summaryError" /></header>
      <main :class="{'workbench-main':isWorkbench&&scanReady&&!summary?.legacy_degraded,'records-main':['coverage','history','opencode'].includes(route),'task-main':route==='tasks'}"><p v-if="bootstrap?.preference_warning" role="alert" class="banner warning">{{bootstrap.preference_warning}}</p><div v-if="isSample && ['overview','variables','coverage','opencode','reviews','sharing'].includes(route)" class="banner warning" role="note">{{bootstrap?.sample?.notice||'教学示例 · 真实扫描归档 · 非用户工程；未链接固件，无硬件验证。'}}</div><div v-if="error" class="banner error" role="alert">{{ error }}</div><div v-if="notice" class="banner" role="status">{{ notice }}</div><p v-if="busy" class="activity" role="status">正在提交或读取，请稍候…</p><p v-if="summary?.evidence_notice" class="banner warning" role="note">派生结果证据模式：{{summary.evidence_notice}}</p><div v-if="summary?.legacy_warning" class="banner warning" role="note">旧归档证据模式：{{summary.legacy_warning}} <button @click="go('sharing')">查看旧文件与复核历史</button></div>
        <template v-if="route==='overview'">
          <div class="page-heading"><div><h1>{{ summary?.legacy_degraded?'查看未验证的旧原件':scan ? '先处理需要核实的变量' : '开始使用 ECRA Studio' }}</h1><p>{{ scan ? '静态、AI 与人工结论分别保留；归档不能替代当前源码核对。' : '选择工程配置，或导入同事发来的完整结果包。' }}</p></div><button v-if="scanReady&&!summary?.legacy_degraded" class="primary" :disabled="busy" @click="pending?continueReview():drillResult('')">{{pending?'继续人工确认':'查看全部变量'}}</button></div>
          <section v-if="scan&&!scanReady" class="panel" role="status"><h2>{{summaryError?'当前结果未能读取':'正在读取结果'}}</h2><p>批次 {{scan}}。结果读取成功后才能查看变量和人工确认；已有数据和草稿保留。</p><p v-if="summaryError">{{summaryError}}</p><div class="actions"><button :disabled="busy" @click="run(refresh)">重试读取</button><button :disabled="busy" @click="go('history')">选择其他历史结果</button></div></section><section v-else-if="summary?.legacy_degraded" class="panel"><h2>未恢复可信静态证据，零可核验对象不等于零风险</h2><p>本归档只保存原有文件，不能生成变量安全结论、当前人工确认或重新复核。缺少内容不会从当前固件补造。</p><LegacyArchive :scan="scan" :degraded="true" /></section><template v-else-if="summary"><div class="banner warning">{{ label(summary.binding.state) }} · 原源码未重新验证。存在未知或待复核项时，不能形成全工程安全结论。</div>
            <div class="cards"><button :disabled="busy" @click="drillResult('RISK')"><span>风险 / 疑似</span><strong class="SUSPECT">{{(summary.result_counts.CONFIRMED||0)+(summary.result_counts.LIKELY||0)}}</strong><small>确认 {{summary.result_counts.CONFIRMED||0}} · 疑似 {{summary.result_counts.LIKELY||0}}</small></button><button :disabled="busy" @click="drillResult('UNKNOWN')"><span>无法判断</span><strong>{{summary.result_counts.UNKNOWN||0}}</strong></button><button :disabled="busy" @click="drillResult('SAFE')"><span>安全（静态 / OpenCode）</span><strong class="SAFE_PROVEN">{{summary.result_counts.SAFE||0}}</strong><small>OpenCode {{summary.safe_sources.OPENCODE||0}} · 静态 {{summary.safe_sources.STATIC||0}}<template v-if="summary.safe_sources.MIXED"> · 联合证据 {{summary.safe_sources.MIXED}}</template></small></button><button :disabled="busy" @click="drillResult('',true)"><span>人工待确认</span><strong>{{pending}}</strong></button></div>
            <p class="muted">当前结论综合最新静态与 OpenCode 证据；安全/误报不进入人工待办。原始静态分类和人工签署记录分别保留。</p><p v-if="summary.derived_static_classification_count" class="banner" role="note">此归档有 {{summary.derived_static_classification_count}} 项未记录容器分类，已按保存的对象类型单列，不重复进入人工待办；请在成员变量中核对风险，既有人工记录保留。</p><p v-if="summary.raw_human_counts.CONFIRMED_RISK||summary.raw_human_counts.CONFLICT" class="banner warning">另有独立人工记录：<button v-if="summary.raw_human_counts.CONFIRMED_RISK" @click="showHumanRecords('CONFIRMED_RISK')">人工确认有风险 {{summary.raw_human_counts.CONFIRMED_RISK}}</button> <button v-if="summary.raw_human_counts.CONFLICT" @click="showHumanRecords('CONFLICT')">人工记录冲突 {{summary.raw_human_counts.CONFLICT}}</button>。请核对原签署依据；OpenCode 不会撤销人工记录。</p>
            <div class="overview-columns"><section class="panel"><h2>按优先级查看与处理</h2><p v-if="!priorityItems.length">当前没有待人工确认的变量。</p><div v-for="item in priorityItems" :key="item.symbol_id" class="todo"><div><strong>{{ item.name }}</strong><p><span class="tag">{{label(item.current_result)}}</span> <small>{{resultOrigin(item)}}</small> {{ item.definition_file }}:{{ item.definition_line }}</p></div><button @click="go('variables'); select(item)">查看证据</button></div><p class="muted">{{ summary.counting_basis }}</p></section><section class="panel"><h2>覆盖与未完成任务</h2><p>本轮静态清单 {{ summary.total }} 项</p><p v-if="pending">当前仍有 {{pending}} 个变量需要人工核实。</p><p v-else>当前没有待人工确认的变量。安全项已退出待办，覆盖边界仍需查看。</p><button @click="go('coverage')">查看覆盖缺口</button><h3>{{summary.derived_static_classification_count?'静态分类与归档容器汇总（复核前）':'原始静态分类（复核前，独立保留）'}}</h3><p v-for="(count,state) in summary.static_counts" :key="state">{{ label(String(state)) }}：{{ count }}</p></section></div>
            <section class="panel"><h2>最近扫描与下一步</h2><p>当前归档 {{ scan }} · {{ currentScan?.profile_id }}</p><template v-if="repeatProfile"><p>按当前已保存配置启动新扫描：{{repeatProfile.id}} · 版本 {{repeatProfile.revision.slice(0,12)}}。扫描会重新核对真实输入，旧归档仍可打开。</p><button :disabled="busy" @click="launchProfile(repeatProfile)">按此配置重新扫描</button><p class="muted">使用自动预算；需要调整时进入扫描任务中心。</p></template><p v-else class="muted">{{profileError||'当前归档没有对应的本机已保存配置；可继续查看与确认，接入真实工程配置后才能启动扫描。'}}</p><p>查看证据 → 人工确认 → 导出标准包/增量 → 在其他电脑继续确认</p><button v-if="bootstrap?.sample?.available" :disabled="busy" @click="openSample">打开示例</button></section>
          </template><section v-else class="panel empty"><h2>选择开始方式</h2><p>新建工程后按四步确认真实构建；也可导入历史结果，或先从真实教学归档熟悉证据与人工确认。</p><div class="actions"><button class="primary" :disabled="busy" @click="newProject">新建工程</button><button :disabled="busy" @click="go('sharing')">导入历史结果</button><button v-if="bootstrap?.sample?.available" :disabled="busy" @click="openSample">打开示例</button></div><p class="muted" v-if="bootstrap?.sample?.available">{{bootstrap.sample.notice}}</p><p v-else class="muted">内置示例暂不可用：{{bootstrap?.sample?.reason||'正在读取程序资产…'}}</p></section>
        </template>
        <template v-else-if="route==='projects'">
          <div class="page-heading"><div><h1>接入工程 · 确认真实构建与范围</h1><p>配置保存在独立数据根。可逐项填写，也可导入已有 YAML 后调整。</p></div><button :disabled="busy" @click="newProfile">新建工程配置</button></div>
          <label class="profile-import">从现有 YAML 导入<input type="file" accept=".yaml,.yml" :disabled="busy||launchPending" @change="importProfile"></label><p class="muted">已有 semantics.yaml 时选它；不会自动覆盖工具的原配置文件。</p><div class="steps"><span v-for="(text,index) in ['选择工程','确认构建','分析范围','检查与保存']" :class="{current: wizardStep===index+1}">{{ index+1 }} {{ text }}</span></div>
          <div class="overview-columns project-config"><section class="panel wizard-panel"><h2>第 {{ wizardStep }} 步</h2><fieldset class="wizard-fields" :disabled="busy||launchPending"><div class="wizard-content">
            <template v-if="wizardStep===1"><label>工程名称<input v-model="projectName" placeholder="例如：电机控制 CM7"></label><label>固件目录（绝对路径）<input v-model="projectRoot" placeholder="D:/Firmware/MotorControl"></label><button type="button" @click="directoryMode='project'">选择固件目录</button><p class="muted">工程名称便于区分历史；固件目录选择包含工程构建文件的根目录。相对配置路径以此目录为准。</p><ProfileOptions v-model="options" :specs="optionSpecs" :groups="['工程']" :build-mode="buildMode" @validity="optionValidity"/></template>
            <template v-if="wizardStep===2"><label>核心标识<input v-model="projectCore" aria-label="核心标识" placeholder="保留默认，或填写工程实际核心标识"></label><p class="muted">对应既有project.core语义；真实CPU、宏与编译参数仍以实际构建为准。留空保持引擎默认，不修改旧配置。</p><label>真实构建方式<select v-model="buildMode" aria-label="真实构建方式" @change="changeBuildMode"><option value="cmake">CMake（外置构建）</option><option value="database">已有 compile_commands.json</option></select></label><label>{{ buildMode==='cmake' ? '目标名称' : '编译数据库路径' }}<input v-model="target"></label><button v-if="buildMode==='database'" type="button" @click="directoryMode='database'">选择编译数据库文件</button><p class="muted">固件构建目标填 CMake 中的实际名称（例如 app_elf）。Ninja 和 MinGW Makefiles 会构建该目标及依赖，并使用对应编译闭包。留空使用默认构建。变量排查范围在纳入与排除中另设。数据库模式请填写已生成的 compile_commands.json。</p><label v-if="buildMode==='cmake'">Toolchain 文件<input v-model="toolchain"></label><button v-if="buildMode==='cmake'" type="button" @click="directoryMode='toolchain'">选择 Toolchain 文件</button><p v-if="buildMode==='cmake'" class="muted">Toolchain填写真实交叉编译文件；工程已自行设置时可留空。</p><label v-if="buildMode==='cmake'">构建变体<input v-model="variant"></label><p v-else>宏、编译变体与工具链以真实编译数据库中的参数为准。</p><label>编译器标准头文件<select v-model="systemHeaders" aria-label="编译器标准头文件"><option value="default">按引擎默认（CMake 开启 / 数据库关闭）</option><option value="on">明确开启 · 从实际编译器探测</option><option value="off">明确关闭 · 使用已有参数</option></select></label><p class="muted">开启会调用真实编译器探测标准头文件目录；编译器缺失会明确失败。保持默认不会补写旧配置字段。</p><ProfileOptions v-if="buildMode==='cmake'" v-model="options" :specs="optionSpecs" :groups="['构建细节']" :build-mode="buildMode" @validity="optionValidity"/></template>
            <template v-if="wizardStep===3"><div class="section-tabs" role="tablist" aria-label="分析范围分组"><button v-for="[id,title] in [['directories','纳入与排除'],['contexts','执行入口'],['git','版本对比'],['analysis','解析与范围细节'],['review','OpenCode复核'],['semantics','扩展语义']]" type="button" role="tab" :aria-selected="rangeTab===id" @click="rangeTab=id">{{title}}</button></div><div v-show="rangeTab==='directories'"><label>变量定义纳入目录（每行一个，空表示全部）<textarea v-model="include" rows="3"></textarea></label><button type="button" :disabled="!projectRoot" @click="directoryMode='include'">从目录树纳入</button><label>排除变量清单目录（每行一个，仍参与调用恢复）<textarea v-model="exclude" rows="3"></textarea></label><button type="button" :disabled="!projectRoot" @click="directoryMode='exclude'">从目录树排除</button><p class="muted">目录树选择使用相对工程路径，“.”表示全部目录；排除仅影响变量清单，仍参与调用恢复。</p><FileExclusions :model-value="options['analysis.exclude_files']" :can-browse="!!projectRoot" @update:model-value="value=>options={...options,'analysis.exclude_files':value}" @browse="directoryMode='exclude-file'"/></div><div v-show="rangeTab==='analysis'"><ProfileOptions v-model="options" :specs="optionSpecs" :groups="['排查选项']" :build-mode="buildMode" @validity="optionValidity"/></div><div v-show="rangeTab==='review'"><ProfileOptions v-model="options" :specs="optionSpecs" :groups="['OpenCode']" :build-mode="buildMode" @validity="optionValidity"/><p class="muted">案例库和当前工程背景也是复核输入；可随时编辑 config 原文件，不需要先保存扫描配置。</p><button type="button" :disabled="busy" @click="configureMaterials">直接编辑案例库与工程背景</button></div><div v-show="rangeTab==='semantics'"><ProfileOptions v-model="options" :specs="optionSpecs" :groups="['扩展语义']" :build-mode="buildMode" @validity="optionValidity"/></div><div v-show="rangeTab==='contexts'"><ContextEditor v-model="contextRows" :editable="contextsEditable" :reason="contextsReason"/></div><div v-show="rangeTab==='git'"><GitVersions :build-mode="buildMode" :project-root="projectRoot" v-model:base-ref="baseRef" v-model:current-ref="currentRef" v-model:include-uncommitted="includeUncommitted"/><p>目录中的逗号与空格按原文保留。版本预览不能替代启动时的真实编译输入核对。</p></div></template>
            <template v-if="wizardStep===4"><h3>确认配置后检查并保存</h3><p>{{editedProfile?.name||projectName||'当前配置'}} · {{profileId||'新配置'}}</p><p class="muted">点击“开始此配置扫描”将依次检查、保存和验证真实构建；通过后自动扫描。可先返回上一步逐项调整。</p><details class="advanced-yaml"><summary>高级完整 YAML · 查看或编辑原文</summary><label>高级完整 YAML<textarea v-model="yaml" rows="9" spellcheck="false" @input="profileCheck=null"></textarea></label></details><details v-if="configInventory.length" class="configuration-inventory"><summary>核对全部已有配置项 · {{configInventory.length}} 项</summary><table><thead><tr><th>配置项</th><th>编辑位置 / 用途</th></tr></thead><tbody><tr v-for="item in configInventory" :key="item.path"><td>{{item.path}}</td><td>{{item.location}} · {{item.hint}}</td></tr></tbody></table></details><button :disabled="busy" @click="checkProfile">检查配置与工具路径</button><details v-if="profileCheck" class="profile-check" :open="profileCheck.checks.some((item:any)=>!item.available)"><summary>配置路径已检查 · 工具可用 {{profileCheck.checks.filter((item:any)=>item.available).length}} / {{profileCheck.checks.length}} · 展开详情</summary><p>工程：{{ profileCheck.project_root }}</p><p>独立数据：{{ profileCheck.data_root }}</p><p v-for="item in profileCheck.checks">{{ item.tool }}：{{ item.available ? '路径可用' : '缺失' }} · {{ item.path }} {{ item.repair }}</p><div class="banner warning">{{ profileCheck.note }}</div></details></template>
            <div v-if="yamlBackup && wizardStep===4" class="banner" role="note"><p>同步前原文已备份 · {{yamlBackup.bytes}} 字节 · {{yamlBackup.id.slice(0,12)}}</p><button @click="restoreYaml">恢复同步前原文</button></div>
            </div><div class="wizard-actions"><button v-if="wizardStep>1" @click="previousStep">上一步</button><button v-if="wizardStep<4" class="primary" @click="nextStep">下一步</button><button v-else :class="{primary:!savedProfileReady}" :disabled="!profileCheck || busy" @click="saveProfile">保存独立配置</button><button v-if="wizardStep===4" class="primary" :disabled="busy||launchPending||!yaml.trim()" @click="prepareAndLaunch">开始此配置扫描</button></div></fieldset><p v-if="launchStatus" role="status" class="launch-status">{{launchStatus}}</p>
          </section><section class="panel"><h2>构建与执行边界</h2><p>真实宏和目标必须来自实际编译命令，工程名称和芯片标签不替代编译参数。</p><p>开始扫描会先检查并保存，再验证真实构建。也可在此单独检查，查看目标、宏和逐文件编译参数。</p><BuildPreflight ref="preflightRef" :profile="savedProfileReady?editedProfile:null" @ready="preflightChanged" @failed="preflightFailed" @tasks="openTasks" /><ReviewMaterials ref="materialsRef"/><button @click="go('tasks')">进入扫描任务中心</button><p v-if="profileError" class="banner error" role="alert">{{profileError}}</p><h3>已保存配置</h3><button v-for="profile in profileList" class="profile" :disabled="busy" @click="openProfile(profile)">{{ profile.name || profile.id }} · 打开完整 YAML</button></section></div>
        </template>
        <template v-else-if="scan&&!scanReady&&['variables','coverage','opencode','reviews'].includes(route)"><section class="panel" role="status"><h2>{{summaryError?'当前结果未能读取':'正在读取结果'}}</h2><p>批次 {{scan}}。结果读取成功后才能查看变量和人工确认；已有数据和草稿保留。</p><p v-if="summaryError">{{summaryError}}</p><div class="actions"><button :disabled="busy" @click="run(refresh)">重试读取</button><button :disabled="busy" @click="go('history')">选择其他历史结果</button></div></section></template><template v-else-if="summary?.legacy_degraded&&['variables','coverage','opencode','reviews'].includes(route)"><h1>未恢复可信静态证据</h1><p>当前仅查看未验证原件；不能人工确认或重新复核，也不能从零对象推断安全。</p><LegacyArchive :scan="scan" :degraded="true" /></template>
        <template v-else-if="isWorkbench">
          <div class="page-heading"><div><h1>{{ route==='reviews' ? '人工确认工作台' : '变量与风险' }}</h1></div><div v-if="route==='reviews' && summary" class="human-counts"><span>待人工 {{summary.pending_count||0}}</span><span>无需人工 {{summary.human_counts.NOT_REQUIRED||0}}</span></div><button v-if="route==='reviews' && scan" :disabled="busy" @click="continueReview">继续上次位置</button></div>
          <div v-if="summary?.diff" class="diff-strip"><span :title="(summary.diff.pin?.base_ref||summary.diff.pin?.base_sha)+' → '+(summary.diff.pin?.current_ref||summary.diff.pin?.head_sha)">Git：{{summary.diff.pin?.base_ref || summary.diff.pin?.base_sha}} → {{summary.diff.pin?.current_ref || summary.diff.pin?.head_sha}} · 影响清单 {{summary.diff.selected_symbol_ids_count}} 项 · 保守潜在影响 {{summary.diff.conservative_symbol_ids_count}} 项</span><button @click="diffOpen=true">范围与完整证据</button></div>
          <WorkspaceDialog v-if="diffOpen&&summary?.diff" title="Git 差异范围与完整证据" @close="diffOpen=false"><p>影响清单 {{summary.diff.selected_symbol_ids_count}} 项；保守潜在影响 {{summary.diff.conservative_symbol_ids_count}} 项。两项分别计数，不表示包含关系；当前列表另受筛选条件限制。</p><p>{{summary.diff.impact_coverage==='COMPLETE'?'影响闭包记录完整':'存在未排除的潜在影响，请核对回退理由。'}} 未排除的潜在影响保留在覆盖证据中，不自动填满默认差异清单。</p><EvidenceNode :scan="scan" :node="summary.diff.node" title="完整基准、当前版本、可比性与影响理由"/></WorkspaceDialog>
          <WorkspaceDialog v-if="filtersOpen" title="筛选变量与风险" @close="filtersOpen=false"><div class="filter-grid"><label>当前分析结论<select aria-label="当前分析结论" v-model="extra.current_result" :disabled="busy" @change="filter"><option value="">全部当前结论</option><option v-for="state in ['CONFIRMED','LIKELY','UNKNOWN','SAFE','SHARED_NO_REVIEW','CONTAINER','OUT_OF_BUILD','NON_STORAGE','INVENTORY']" :value="state">{{label(state)}}</option></select></label><label>原始静态分类<select aria-label="静态分类" :disabled="busy" v-model="classification" @change="filter"><option value="">全部静态分类</option><option v-for="state in ['SUSPECT','UNKNOWN','SAFE_PROVEN','SHARED_NO_REVIEW','CONTAINER','OUT_OF_BUILD','NON_STORAGE']" :value="state">{{ label(state) }}</option></select></label><label>人工状态<select aria-label="人工状态" :disabled="busy" v-model="humanFilter" @change="filter"><option value="">全部人工状态</option><option v-for="state in ['PENDING','CONFIRMED_RISK','CONFIRMED_SAFE','NEED_MORE_EVIDENCE','RECHECK_REQUIRED','CONFLICT']" :value="state">{{ label(state) }}</option></select></label><label>定义文件包含<input v-model="extra.file" :disabled="busy" @change="filter"></label><label>访问函数身份包含<input v-model="extra.function" :disabled="busy" @change="filter"></label><label>执行上下文 / IRQ 身份<input v-model="extra.context" :disabled="busy" @change="filter" placeholder="例如 main、usart；精确身份"></label><label>AI 复核状态<select aria-label="AI 复核状态" v-model="extra.ai_state" :disabled="busy" @change="filter"><option value="">全部 AI 状态</option><option v-for="state in ['PENDING','DONE','TECH_FAILED','CONFIRMED','LIKELY','REVIEWED_SAFE','FALSE_POSITIVE','NEED_MORE_CONTEXT','NOT_QUEUED']" :value="state">{{label(state)}}</option></select></label><label>风险处理状态<select aria-label="风险处理状态" v-model="extra.handling_status" :disabled="busy" @change="filter"><option value="">全部处理状态</option><option v-for="state in ['TODO','FIXING','TO_VERIFY','CLOSED','ACCEPTED_RISK','CONFLICT']" :value="state">{{label(state)}}</option></select></label><label>对象覆盖状态<select aria-label="对象覆盖状态" v-model="extra.coverage" :disabled="busy" @change="filter"><option value="">全部覆盖状态</option><option v-for="state in ['COMPLETE','PARTIAL','FAILED','UNKNOWN']" :value="state">{{label(state)}}</option></select></label><label v-if="summary?.diff">Diff 影响范围<select aria-label="Diff 影响范围" v-model="extra.diff" :disabled="busy" @change="filter"><option value="">完整静态清单</option><option value="selected">全部影响项</option><option value="direct">确定依赖影响项</option><option value="conservative">保守扩大项</option></select></label><label>列表排序<select aria-label="列表排序" v-model="extra.sort" :disabled="busy" @change="filter"><option value="priority">风险优先</option><option value="name">变量名称（字典序）</option><option value="definition">定义位置</option><option value="review_priority">待办优先级</option></select></label><label>排序方向<select aria-label="排序方向" v-model="extra.order" :disabled="busy" @change="filter"><option value="asc">升序</option><option value="desc">降序</option></select></label></div><template #footer><span>匹配 {{total}} 项 · 修改条件后自动查询</span><div class="actions"><button :disabled="busy" @click="clearFilters">清空筛选</button><button class="primary" @click="filtersOpen=false">查看结果</button></div></template></WorkspaceDialog>
          <div v-if="scanReady" ref="workbenchElement" class="workbench" :class="{'has-selection':!!selected,'focus-detail':focusEvidence&&!!selected}" :style="{'--list-width':split+'%','--workbench-min-height':minimumPaneHeight+'px'}"><section class="list-panel panel"><button v-if="fromCoverage" :disabled="busy" @click="go('coverage')">返回覆盖诊断</button><p v-if="extra.symbol_id" class="identity">精确定位：{{extra.symbol_id}} <button :disabled="busy" @click="extra.symbol_id='';filter()">清除精确定位</button></p><div class="list-filters"><form @submit.prevent="searchList"><label for="variable-search" class="sr-only">查找变量、文件或规范身份</label><input id="variable-search" v-model="search" :disabled="busy" placeholder="变量 / 文件 / symbol_id"><button :disabled="busy">搜索</button><button type="button" @click="filtersOpen=true">筛选</button></form><div class="filter-summary"><span :title="filterDescription">{{filterDescription}}</span><button :disabled="busy" @click="clearFilters">清空</button></div></div><div class="symbol-list"><button v-for="item in items" :key="item.symbol_id" :class="{selected:selected?.symbol_id===item.symbol_id}" class="symbol" :disabled="busy" @click="select(item)"><strong>{{ item.name }}</strong><div><span class="tag" :class="item.current_result">{{label(item.current_result)}}</span><span class="tag" :class="item.confirmation_state">{{confirmation(item)}}</span><small>{{resultOrigin(item)}}<span v-if="item.human.decision!=='PENDING'"> · 人工记录：{{label(item.human.decision)}}</span></small></div><small>{{ item.definition_file ? item.definition_file+':'+(item.definition_line||'?') : '定义位置未记录' }}</small></button><p v-if="!loading && !items.length">没有匹配对象，请调整筛选。</p></div><div class="page-controls"><span role="status">{{loading?'读取中…':`匹配 ${total} 项 · ${total?offset+1:0}–${Math.min(offset+50,total)}`}}</span><button :disabled="offset===0 || busy" @click="page(-1)">上一页</button><button :disabled="offset+50>=total || busy" @click="page(1)">下一页</button></div>
          </section><div class="splitter" role="separator" aria-label="调整列表与证据宽度" aria-orientation="vertical" tabindex="0" :aria-valuenow="Math.round(split)" aria-valuemin="30" aria-valuemax="46" @pointerdown="resizeSplit" @pointermove="resizeSplit" @keydown="splitKey"></div><section class="detail-panel panel" :key="selected?.symbol_id || ''"><template v-if="selected"><div class="detail-summary"><div class="detail-heading"><h2 :title="selected.name">{{ selected.name }}</h2><div class="actions"><button class="pane-toggle" @click="returnList">返回列表</button><button :disabled="busy||(selectedIndex<=0&&offset===0)" @click="adjacent(-1)">上一项</button><button :disabled="busy||offset+selectedIndex+1>=total" @click="adjacent(1)">下一项</button><button @click="focusEvidence=!focusEvidence">{{focusEvidence?'恢复双栏':'专注阅读'}}</button><button @click="copyName">复制全名</button></div></div><details class="object-identity"><summary>定义位置与完整身份</summary><p>{{selected.definition_file}}:{{selected.definition_line}}</p><p class="identity">{{selected.symbol_id}}</p></details><p class="conclusion">当前分析：{{label(selected.current_result)}}（{{resultOrigin(selected)}}）；{{confirmation(selected)}}。<small><template v-if="selected.static_classification_derived">归档未记录本项静态分类；按已保存的对象类型显示容器汇总</template><template v-else>原始静态：{{label(selected.static_classification)}}</template>；人工记录：{{human?.decision==='PENDING'?'尚无人工记录':label(human?.decision||'PENDING')}}。归档证据不代表目标板实测。</small></p>
            </div><div class="detail-tabs" role="tablist" aria-label="证据分组"><button v-for="[id,title] in [['ai','OpenCode结论'],['access','时序与访问'],['relations','调用与保护'],['source','归档源码'],['history','人工历史']]" role="tab" :aria-selected="detailTab===id" @click="detailTab=id">{{ title }}</button></div>
            <div class="detail-evidence"><button v-if="selected.ai_answer_count&&detailTab!=='ai'" @click="detailTab='ai'">查看最新OpenCode结论</button><p v-if="!selected.requires_human_review" class="banner">该对象无需人工确认，已从人工待办中排除；原始证据与人工记录仍可查看。</p><SymbolAI v-if="detailTab==='ai'" :scan="scan" :symbol="selected.symbol_id" :revision="summary.result_revision" @source="openSource"/>
            <section v-show="detailTab==='access'" class="detail-group"><h3>潜在并发与判定条件</h3><p>展开静态理由查看成立前提；证据不足时保持未知。推断时序不是硬件采集。</p><FindingCard v-for="record in findings?.items" :key="record.node" :scan="scan" :node="record.node" :summary="record.summary" @source="openSource"/><p v-if="findings?.total===0">本对象没有独立finding；请核对变量覆盖状态。</p>
            <h3>访问证据 · 共 {{ accesses?.total || 0 }} 项</h3><article v-for="record in accesses?.items" :key="record.ordinal" class="access-row"><strong>{{ label(record.summary.access_kind || '') }} · {{ record.summary.file }}:{{ record.summary.line }}</strong><p><EvidenceIdentity :scan="scan" kind="function" :id="record.summary.function_id"/> · {{ record.summary.expression || record.summary.source_text }}</p><button @click="openSource({file:record.summary.file,line:record.summary.line||1})">定位此访问代码</button><EvidenceNode :scan="scan" :node="record.node" :title="'完整访问 #'+(record.ordinal+1)"/></article><button v-if="accesses?.next_offset!==null && accesses?.next_offset!==undefined" @click="run(async()=>{ const next=await api(apiScan+'/records/accesses?symbol_id='+encodeURIComponent(selected.symbol_id)+'&offset='+accesses.next_offset); accesses={...next,items:[...accesses.items,...next.items]} })">继续读取访问</button></section>
            <section v-show="detailTab==='relations'" class="detail-group"><h3>需要核对的调用与保护</h3><p class="muted">先核对谁访问、能否交错、保护是否覆盖；点击需要的部分查看。</p><details class="evidence-section"><summary>追溯调用入口 · 谁调用了这些访问函数</summary><CallTree :key="selected.symbol_id" :scan="scan" :symbol="selected.symbol_id"/></details><div v-for="item in usefulEvidence" :key="item.id" class="evidence-section"><p class="muted">{{evidenceHints[item.key]}}</p><EvidenceNode :scan="scan" :node="item.id" :title="field(item.key)"/></div><details class="advanced-evidence"><summary>更多技术证据与原始字段</summary><p class="muted">包含完整调用、别名、存储身份、空集合及未来字段；日常可先看判定理由与访问代码。</p><EvidenceNode :scan="scan" :node="selected.node" title="完整规范对象"/></details></section>
            <section v-if="detailTab==='source' && sourceLocation" class="detail-group"><SourceViewer :scan="scan" :file="sourceLocation.file" :line="sourceLocation.line"/></section>
            <section v-show="detailTab==='history'" class="detail-group"><h3>不可变确认历史 · {{ human?.history?.length || 0 }} 个本轮事件</h3><section v-if="human?.prior_reviews?.length" class="banner warning"><h4>{{ human?.inherited ? '完整输入与事实未变，沿用原人工确认' : human?.conflict ? '来源确认存在冲突，请显式解决' : '旧扫描确认保留为历史，当前证据须重新确认' }}</h4><details v-for="prior in human.prior_reviews"><summary>旧扫描 {{prior.binding.scan_id}} · {{prior.events.length}} 个原始事件</summary><article v-for="event in prior.events" class="history-event"><strong>{{label(event.decision)}}</strong><p>{{event.reviewer}} · {{event.timestamp}} · {{event.device}}</p><p>{{event.comment}}</p><small>旧证据指纹 {{event.fingerprint}}</small></article></details></section><article v-for="event in human?.history" class="history-event"><strong>{{ label(event.decision) }} · {{ label(event.handling_status) }}</strong><p>{{ event.reviewer }} · {{ event.timestamp }} · {{ event.device }}</p><p>{{ event.comment }}</p><small>{{ event.event_id }}</small></article></section>
            </div>
            <section class="review-controls"><p v-if="!selected.requires_human_review&&['CONFIRMED_RISK','CONFLICT','RECHECK_REQUIRED'].includes(selected.human_record_decision)" class="banner warning" role="alert">当前分析无需人工确认，但原人工记录为 {{label(selected.human_record_decision)}}；记录仍然有效保留，请查看人工历史，必要时填写依据后更正。</p><p v-if="!reviewExpanded&&draftWarning" class="banner warning" role="alert">{{draftWarning}}</p><p v-if="!reviewExpanded&&human?.conflict" class="banner error" role="alert">人工确认存在冲突，请展开填写区并核对人工历史。</p><div class="review-toggle"><button type="button" :aria-expanded="reviewExpanded" @click="reviewExpanded=!reviewExpanded">{{reviewExpanded?'收起填写区':selected.requires_human_review?'填写人工确认':'人工记录（无需确认）'}}</button><span class="review-subject" aria-label="当前确认对象"><strong>{{summary?.identity?.project_name||'工程名称未记录'}} · {{selected.name}}</strong><span>{{selected.definition_file||'定义位置未记录'}}{{selected.definition_line?':'+selected.definition_line:''}} · 人工：{{confirmation(selected)}}</span><span v-if="comment.trim()">当前对象有未提交依据</span></span></div><div v-show="reviewExpanded" class="review-content"><p v-if="draftCount" class="muted" role="status">本窗口 {{draftCount}} 份未提交草稿；切换对象保留，刷新/关闭前请提交。</p><p v-if="draftWarning" class="banner warning" role="alert">{{draftWarning}}</p><p v-if="!human" role="status">当前对象证据未就绪，请等待读取完成；失败后可重新点击左侧对象。</p><details v-if="human?.inherited" class="review-extra"><summary>已沿用原确认 · 展开来源</summary><p><strong>沿用：{{ label(human.decision) }}</strong><span v-for="origin in human.inherited_sources" :key="origin.event_id"> · {{ origin.reviewer }} · {{ origin.timestamp }} · 原扫描 {{ origin.scan_id }}</span>。可查看“人工历史”中的原依据，或填写理由撤销。</p></details><div v-if="human?.conflict" class="banner error">离线并行确认冲突：先核对“人工历史”，填写依据后显式合并全部分支。</div><div class="review-fields"><label>确认者<input aria-label="确认者" title="姓名或团队为未经认证的声明" v-model="reviewer" :disabled="busy || !human" placeholder="姓名或团队声明"></label><label>独立处理状态（不改变静态 / AI）<select v-model="handling" :disabled="busy || !human" aria-label="独立处理状态"><option v-for="state in ['TODO','FIXING','TO_VERIFY','CLOSED','ACCEPTED_RISK']" :value="state">{{ label(state) }}</option></select></label></div><label>依据 / 修改或撤销理由<textarea v-model="comment" :disabled="busy || !human" rows="3" placeholder="确认无风险必须填写依据或证据引用"></textarea></label></div><div v-show="reviewExpanded" class="decision-actions"><button :disabled="busy || !human || !reviewer.trim()" @click="saveDecision('CONFIRMED_RISK')">确认有风险</button><button :disabled="busy || !human || !reviewer.trim() || !comment.trim()" @click="saveDecision('CONFIRMED_SAFE')">确认无风险</button><button :disabled="busy || !human || !reviewer.trim()" @click="saveDecision('NEED_MORE_EVIDENCE')">暂无法确认</button><button :disabled="busy || !human || !comment.trim() || (!human?.heads?.length && !human?.inherited) || human?.conflict" @click="saveDecision('PENDING', true)">撤销上次确认</button></div></section>
          </template><div v-else class="empty"><h2>选择左侧对象查看完整证据</h2><p>支持同名static的独立身份。Ctrl+F查找，Esc返回列表。</p><p v-if="draftCount" role="status">本窗口保留 {{draftCount}} 份未提交草稿，重新选择对应对象可继续填写。刷新/关闭前请提交。</p></div></section></div><section v-else class="panel empty">尚无结果包。请先从“数据与共享”导入。</section>
        </template>
        <template v-else-if="route==='coverage'"><CoverageCenter v-if="scan&&summary" :key="scan" :scan="scan" :roots="summary.roots" @symbol="openCoverageSymbol"/><p v-else>{{scan?'正在读取当前归档；若读取失败，请查看上方诊断。':'尚无可查看的归档。'}}</p></template>
        <template v-else-if="route==='history'"><HistoryCenter v-if="bootstrap" :data-root="bootstrap.data_root" :busy="busy" @open="openScan" @continue="continueReview" @symbol="openHistorySymbol" /></template>
        <template v-else-if="route==='sharing'"><div class="page-heading"><div><h1>数据与共享</h1><p>完整包可在无原固件的电脑查看归档并继续确认。导出可能含敏感代码与备注，请按团队规则分享。</p></div><button :disabled="busy" @click="sharingTab='multicore';multicoreRef?.open()">合并已有多核结果</button></div><div class="section-tabs" role="tablist" aria-label="数据与共享分组"><button v-for="[id,title] in [['exchange','结果交接'],['migration','旧结果迁移'],['storage','空间与清理'],['multicore','多核合并']]" role="tab" :aria-selected="sharingTab===id" @click="sharingTab=id;if(id==='multicore')multicoreRef?.open()">{{title}}</button></div><div v-show="sharingTab==='exchange'" class="overview-columns"><section class="panel"><h2>导入完整结果</h2><p>校验ZIP路径、数据库结构、全部证据哈希与人工历史后原子发布；失败保留已有数据。</p><label>选择 .ecra-report<input type="file" accept=".ecra-report" :disabled="busy" @change="importFile($event)"></label><template v-if="scan"><h3>合并人工确认增量</h3><label>选择 .ecra-review-delta<input type="file" accept=".ecra-review-delta" :disabled="busy" @change="importFile($event,true)"></label><p>重复导入去重；并行决定保留双方事件，进入显式冲突。</p></template></section><section class="panel"><h2>导出当前归档</h2><p>{{ scan || '尚未选择归档' }}</p><template v-if="scan"><label>完整包压缩<select aria-label="完整包压缩" v-model="archiveCompression" :disabled="busy"><option value="compact">省空间（压缩较慢）</option><option value="deflate">快速（文件较大）</option></select></label><p class="muted">两种方式均包含相同的完整证据和人工记录；人工确认增量不受此选项影响。</p></template><div v-if="scan" class="actions"><button :disabled="busy" @click="exportFile('full')">导出标准完整包</button><button :disabled="busy" @click="exportFile('delta')">导出人工确认增量</button></div></section></div><div v-show="sharingTab==='multicore'"><MulticoreCenter ref="multicoreRef" :scans="scans" :busy="busy" @tasks="openTasks"/></div><div v-show="sharingTab==='migration'"><MigrationCenter @completed="readPage(async()=>{storage=await api('/storage');scans=(await api('/scans')).items})" @open="openScan" /><LegacyArchive v-if="summary?.legacy_warning" :key="scan" :scan="scan" :degraded="summary.legacy_degraded" @evidence="go('coverage')" /></div><div v-show="sharingTab==='storage'"><section class="panel"><h3>真实数据占用</h3><p class="muted">采样时间 {{storage?.sampled_at || '尚未读取'}}</p><button :disabled="busy" @click="run(async()=>{storage=await api('/storage')})">更新空间占用</button><StorageUsage :storage="storage"/></section><CleanupCenter /></div></template>
        <template v-else-if="route==='tasks'"><TaskCenter :focus-task="taskFocus" @focus="rememberTask" @open="openScan" @results-changed="resultChanged" /></template>
        <template v-else-if="route==='opencode'"><ReviewCenter v-if="scan&&summary" :key="scan" :scan="scan" :project-id="summary.binding.project_id" :profile-id="summary.binding.profile_id" :can-review="summary.can_review" :revision="summary.result_revision" @tasks="openTasks" @updated="resultChanged()"/><section v-else class="panel"><h1>OpenCode 复核</h1><p>先打开已保存的真实扫描或结果包。案例库与工程背景可以提前编辑。</p><ReviewMaterials/></section></template>
        <template v-else><h1>设置与验收状态</h1><p v-if="bootstrap?.preference_warning" role="alert" class="banner warning">{{bootstrap.preference_warning}}</p><DataRootSettings :busy="busy"/><section class="panel"><h2>明确的能力边界</h2><p v-for="item in bootstrap?.limits">{{ item }}</p><p>大型整轮 Diff/恢复、32GB 真机、干净离线电脑和人工 UAT 仍待验；其他 G2 工程按获准范围待验，不宣称完整发布。</p></section></template>
      </main>
    </div>
    <DirectoryBrowser v-if="directoryMode" :multiple="directoryMode==='exclude-file'" :kind="directoryMode==='exclude-file'?'project_file':directoryMode==='database'?'compile_database':directoryMode==='toolchain'?'toolchain':undefined" :title="directoryMode==='exclude-file'?'选择要排除变量的文件':directoryMode==='database'?'选择编译数据库文件':directoryMode==='toolchain'?'选择 Toolchain 文件':directoryMode==='project'?'选择固件目录':directoryMode==='include'?'选择变量纳入目录':'选择变量排除目录'" :start="projectRoot" :root="['include','exclude','exclude-file'].includes(directoryMode)?projectRoot:undefined" @selected="directorySelected" @selected-files="excludedFilesSelected" @close="directoryMode=''"/>
  </div>
</template>
