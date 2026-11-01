<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, upload, download, label, field } from './api'
import EvidenceNode from './EvidenceNode.vue'
import CallTree from './CallTree.vue'
import CleanupCenter from './CleanupCenter.vue'
import SourceViewer from './SourceViewer.vue'
import FindingCard from './FindingCard.vue'
import TaskCenter from './TaskCenter.vue'
import ReviewCenter from './ReviewCenter.vue'
import MigrationCenter from './MigrationCenter.vue'
import LegacyArchive from './LegacyArchive.vue'
import CoverageCenter from './CoverageCenter.vue'
import GitVersions from './GitVersions.vue'
import ContextEditor from './ContextEditor.vue'
const navigation = [ ['overview','项目概览'], ['projects','工程配置'], ['tasks','扫描任务'], ['variables','变量与风险'], ['coverage','覆盖与诊断'], ['opencode','OpenCode 复核'], ['reviews','人工确认'], ['history','历史与对比'], ['sharing','数据与共享'] ]
const route = ref(location.hash.slice(2) || 'overview'), compact = ref(false)
const bootstrap = ref<any>(null), scans = ref<any[]>([]), scan = ref(localStorage.getItem('ecra-scan') || ''), summary = ref<any>(null)
const error = ref(''), notice = ref(''), busy = ref(false), loading = ref(false)
const items = ref<any[]>([]), total = ref(0), offset = ref(0), search = ref(''), classification = ref(''), humanFilter = ref(''), selected = ref<any>(null)
const defaultFilters=():Record<string,string>=>({handling_status:'',file:'',function:'',context:'',coverage:'',ai_state:'',diff:'',symbol_id:'',sort:'priority',order:'asc'})
const extra=ref<Record<string,string>>(defaultFilters())
const human = ref<any>(null), reviewer = ref(localStorage.getItem('ecra-reviewer') || ''), comment = ref(''), handling = ref('TODO')
const accesses = ref<any>(null), findings = ref<any>(null), staticFields = ref<any[]>([]), storage = ref<any>(null), fromCoverage=ref(false)
const sourceLocation=ref<any>(null), split=ref(Number(localStorage.getItem('ecra-split'))||38)
function resizeSplit(event:PointerEvent){const el=event.currentTarget as HTMLElement;if(event.type==='pointerdown')el.setPointerCapture(event.pointerId);if(event.buttons===1){const rect=el.parentElement!.getBoundingClientRect();split.value=Math.max(30,Math.min(46,100*(event.clientX-rect.left)/rect.width));localStorage.setItem('ecra-split',String(split.value))}}
function splitKey(event:KeyboardEvent){if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();split.value=Math.max(30,Math.min(46,split.value+(event.key==='ArrowLeft'?-1:1)));localStorage.setItem('ecra-split',String(split.value))}}
function openSource(location:any){sourceLocation.value=location;detailTab.value='source'}
const detailTab=ref('access'), sourceRef=ref<any>(null), priorityItems=ref<any[]>([])
const apiScan = computed(() => `/scans/${encodeURIComponent(scan.value)}`)
const currentScan = computed(() => scans.value.find(x => x.scan_id === scan.value))
const isWorkbench = computed(() => route.value === 'variables' || route.value === 'reviews')
const pending = computed(() => summary.value?.human_counts?.PENDING || 0)
const wizardStep = ref(1), projectName = ref(''), projectRoot = ref(''), buildMode = ref('cmake'), toolchain = ref(''), target = ref(''), variant = ref('Debug')
const include = ref(''), exclude = ref(''), baseRef = ref(''), currentRef = ref('HEAD'), yaml = ref(''), profileCheck = ref<any>(null), profileList = ref<any[]>([]), profileId = ref(''), profileRevision = ref('')
const savedYaml=ref(''),profileError=ref(''),taskFocus=ref(sessionStorage.getItem('ecra-task-focus')||'')
const formSnapshot=ref<Record<string,any>|null>(null),yamlBackup=ref<any>(null)
const initialContexts=()=>[{origin_id:null as string|null,id:'main',kind:'MAIN',functions:['main']}]
const contextRows=ref(initialContexts()),contextsEditable=ref(true),contextsReason=ref(''),systemHeaders=ref('default')
const editedProfile=computed(()=>profileList.value.find(p=>p.id===profileId.value&&p.revision===profileRevision.value))
const savedProfileReady=computed(()=>!!editedProfile.value&&savedYaml.value===yaml.value)
const repeatProfile=computed(()=>currentScan.value?.mode==='LOCAL_SNAPSHOT'?profileList.value.find(p=>p.project_id===summary.value?.binding.project_id&&p.id===summary.value?.binding.profile_id):null)
function rememberTask(id:string){taskFocus.value=id;sessionStorage.setItem('ecra-task-focus',id)}
function openTasks(id?:string){if(id)rememberTask(id);go('tasks')}
async function loadProfiles(){try{profileList.value=(await api('/profiles')).items;profileError.value=''}catch(e:any){profileList.value=[];profileError.value='本机配置读取失败：'+e.message}}
async function launchProfile(profile:any){await run(async()=>{
  if(!profile)throw Error('没有可启动的已保存配置；请检查并保存当前配置。')
  const task=await api('/tasks','POST',{project_id:profile.project_id,profile_id:profile.id,revision:profile.revision,resources:{preset:'auto',workers:4}})
  if(!task.id)throw Error('启动器未返回真实任务身份，请核对任务中心。')
  rememberTask(task.id);go('tasks')
})}
function go(path: string) { location.hash = '/' + path; route.value = path; compact.value = false; error.value = ''; notice.value = '' }
function hashed() { route.value = location.hash.slice(2) || 'overview' }
async function copyName() { if (selected.value) await navigator.clipboard.writeText(selected.value.name) }
async function run(task: () => Promise<any>) {
  if (busy.value) { error.value = '上一项操作仍在进行，请等待完成后重试。'; return }
  busy.value = true; error.value = ''; notice.value = ''
  try { return await task() } catch (e: any) { error.value = e.message } finally { busy.value = false }
}
async function readPage(task: () => Promise<any>) { const startedRoute=route.value; try { await task() } catch (e: any) { if(!busy.value && !error.value && route.value===startedRoute) error.value='页面信息读取失败：'+e.message } }
async function refresh() {
  scans.value = (await api('/scans')).items
  if (!scans.value.some(x => x.scan_id === scan.value)) scan.value = scans.value[0]?.scan_id || ''
  if (scan.value) { summary.value = await api(apiScan.value + '/summary'); if(!localStorage.getItem('ecra-filters-'+scan.value))extra.value.diff=summary.value.diff?'selected':''; priorityItems.value=(await api(apiScan.value+'/symbols?limit=5')).items; await loadList() }
  else summary.value = null
  await loadProfiles()
}
async function loadList() {
  if (!scan.value) return
  loading.value = true
  try {
    const value = await api(apiScan.value + `/symbols?${new URLSearchParams({search:search.value,classification:classification.value,human_decision:humanFilter.value,offset:String(offset.value),limit:'50',...extra.value})}`)
    items.value = value.items; total.value = value.total
  } finally { loading.value = false }
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
    const item=await api(apiScan.value+'/symbol?symbol_id='+encodeURIComponent(id))
    search.value='';classification.value='';humanFilter.value='';extra.value={...defaultFilters(),symbol_id:id};offset.value=0
    fromCoverage.value=true;go('variables');await loadList();await loadSelection(item)
  })
}
async function select(item: any) {
  await run(() => loadSelection(item))
}
async function loadSelection(item: any) {
    selected.value = item; comment.value = ''; sourceLocation.value={file:item.definition_file||'',line:item.definition_line||1}
    human.value = await api(apiScan.value + '/human?symbol_id=' + encodeURIComponent(item.symbol_id))
    handling.value = human.value.handling_status
    staticFields.value = (await api(apiScan.value + '/nodes/' + item.node + '?limit=200')).items
    accesses.value = await api(apiScan.value + '/records/accesses?symbol_id=' + encodeURIComponent(item.symbol_id))
    findings.value = await api(apiScan.value + '/records/findings?dataset=report&symbol_id=' + encodeURIComponent(item.symbol_id))
    sourceRef.value = await api(apiScan.value + '/source?file='+encodeURIComponent(item.definition_file || ''))
    await rememberList()
}
async function saveDecision(decision: string, undo = false) {
  await run(async () => {
    const result = await api(apiScan.value + '/human', 'POST', { symbol_id: selected.value.symbol_id, fingerprint: human.value.fingerprint,
      decision, handling_status: handling.value, reviewer: reviewer.value, comment: comment.value, expected_heads: human.value.heads.map((e: any) => e.event_id), resolve: human.value.conflict, undo })
    if (!result.saved) throw new Error('确认尚未提交')
    localStorage.setItem('ecra-reviewer', reviewer.value)
    human.value = await api(apiScan.value + '/human?symbol_id=' + encodeURIComponent(selected.value.symbol_id))
    summary.value = await api(apiScan.value + '/summary'); await loadList(); notice.value = '已保存，静态分类保持独立。'; comment.value = ''
  })
}
async function continueReview() {
  await run(async()=>{
  go('reviews')
  const position = await api(apiScan.value + '/position')
  if (position) {
    search.value = position.search || ''; classification.value = position.classification || ''; humanFilter.value = position.human_filter || ''; offset.value = position.offset || 0; if(position.extra)extra.value={...extra.value,...position.extra}
    await loadList()
    const item = items.value.find(x => x.symbol_id === position.symbol_id)
    if (item) await loadSelection(item)
    else if (items.value.length) await loadSelection(items.value[0])
  } else {
    humanFilter.value = 'PENDING'; offset.value = 0; await loadList()
    if (items.value.length) await loadSelection(items.value[0])
  }
  })
}
async function drill(state: string, humanState = '') { search.value = ''; extra.value.symbol_id='';classification.value = state; humanFilter.value = humanState; offset.value = 0; go(humanState ? 'reviews' : 'variables'); await run(async()=>{await loadList();await rememberList()}) }
async function page(delta: number) { offset.value = Math.max(0, offset.value + delta * 50); await run(async()=>{await loadList();await rememberList()}) }
async function importFile(event: Event, delta = false) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]
  if (!file) return
  await run(async () => { notice.value = '正在校验归档结构、完整证据与人工历史…'; const result = await upload(delta ? apiScan.value + '/delta/import' : '/import', file); scan.value = result.scan_id; await refresh(); notice.value = `导入已提交：${result.scan_id}；新增人工事件 ${result.imported_events}` })
  input.value = ''
}
async function exportFile(kind: string) {
  await run(async () => { const result = await api(apiScan.value + '/export', 'POST', { kind }); await download(result.download, result.filename); notice.value = '已生成一致快照包并开始下载。' })
}
function buildYaml() {
  const q = (s: string) => JSON.stringify(s)
  yaml.value = `# 高级字段可在下方完整编辑\nversion: 1\nproject:\n  name: ${q(projectName.value)}\n  root: ${q(projectRoot.value)}\nanalysis:\n  output: {location: user}\n  include_dirs: ${JSON.stringify(directoryLines(include.value))}\n  exclude_dirs: ${JSON.stringify(directoryLines(exclude.value))}\n`
  if (buildMode.value === 'cmake') yaml.value += `  cmake:\n    generator: Ninja\n    build: true\n    build_type: ${q(variant.value)}\n${toolchain.value ? '    toolchain_file: '+q(toolchain.value)+'\n' : ''}${target.value ? '    target: '+q(target.value)+'\n' : ''}`
  else yaml.value += `  compile_database: ${q(target.value || 'compile_commands.json')}\n`
  if(systemHeaders.value!=='default')yaml.value+=`  auto_system_includes: ${systemHeaders.value==='on'}\n`
  if (baseRef.value) yaml.value += `  git_diff:\n    enabled: true\n    base_ref: ${q(baseRef.value)}\n    current_ref: ${q(currentRef.value)}\n    include_uncommitted: false\n`
  yaml.value += `contexts: ${JSON.stringify(contextRows.value.map(({id,kind,functions})=>({id,kind,functions})))}\nreview:\n  enabled: false\n`
}
function directoryLines(value:string){return value.split(/\r?\n/).filter(line=>line.length>0)}
function currentForm(){return {project_name:projectName.value,project_root:projectRoot.value,build_mode:buildMode.value,target:target.value,toolchain:toolchain.value,variant:variant.value,include_dirs:directoryLines(include.value),exclude_dirs:directoryLines(exclude.value),base_ref:baseRef.value,current_ref:currentRef.value,contexts:contextRows.value.map(row=>({...row,functions:[...row.functions]})),system_headers:systemHeaders.value}}
function changeBuildMode(){target.value=''}
async function previousStep(){if(wizardStep.value!==4){wizardStep.value--;return}await run(async()=>{
  const raw=yaml.value,state=await api('/profiles/form','POST',{yaml:raw})
  if(yaml.value!==raw)throw Error('配置已变化，请重新返回表单。')
  if(!state.editable)throw Error(state.reason)
  const f=state.form;projectName.value=f.project_name;projectRoot.value=f.project_root;buildMode.value=f.build_mode;target.value=f.target;toolchain.value=f.toolchain;variant.value=f.variant;include.value=f.include_dirs.join('\n');exclude.value=f.exclude_dirs.join('\n');baseRef.value=f.base_ref;currentRef.value=f.current_ref
  contextRows.value=f.contexts;contextsEditable.value=state.contexts_editable;contextsReason.value=state.contexts_reason;systemHeaders.value=f.system_headers
  formSnapshot.value=f;wizardStep.value=3
})}
async function nextStep(){if(wizardStep.value<3){wizardStep.value++;return}await run(async()=>{
  if(!yaml.value){buildYaml();formSnapshot.value=currentForm()}
  else{
    if(!formSnapshot.value)throw Error('请先从高级YAML返回，读取当前表单值。')
    const form=currentForm(),changes:Record<string,any>={}
    for(const [key,value] of Object.entries(form))if(JSON.stringify(value)!==JSON.stringify(formSnapshot.value[key]))changes[key]=value
    if(changes.build_mode){changes.target=form.target;if(form.build_mode==='cmake'){changes.toolchain=form.toolchain;changes.variant=form.variant}}
    if(form.build_mode==='database'){delete changes.toolchain;delete changes.variant}
    const raw=yaml.value,result=await api('/profiles/form-merge','POST',{yaml:raw,changes})
    if(yaml.value!==raw)throw Error('配置已变化；同步结果未应用，请重试。')
    if(result.backup)yamlBackup.value=result.backup
    yaml.value=result.yaml;formSnapshot.value=form
    notice.value=result.build_mode_changed?'已同步并切换构建方式；旧构建分支已保存到原文备份，可恢复后重新检查。':result.changed_paths.length?'已同步所改字段；完整原文备份可恢复。':'表单未修改，完整原文保持一致。'
  }
  profileCheck.value=null;wizardStep.value=4
})}
async function restoreYaml(){await run(async()=>{const identity=yamlBackup.value.id,result=await api('/profiles/drafts/'+encodeURIComponent(identity));yaml.value=result.yaml;formSnapshot.value=null;profileCheck.value=null;wizardStep.value=4;notice.value='已恢复同步前完整原文；请重新检查并保存。'})}
async function checkProfile() { await run(async () => { const raw=yaml.value,result=await api('/profiles/check', 'POST', { yaml: raw });if(yaml.value===raw)profileCheck.value=result }) }
async function saveProfile() { await run(async () => { if(!profileCheck.value)throw Error('请重新检查当前配置。');const raw=yaml.value,anotherProject=editedProfile.value&&editedProfile.value.project_id!==profileCheck.value.project_id;const result = await api('/profiles', 'POST', { yaml: raw, id: anotherProject?undefined:profileId.value || undefined, revision: anotherProject?undefined:profileRevision.value || undefined }); profileId.value = result.id; profileRevision.value = result.revision; savedYaml.value=raw;await loadProfiles();notice.value = anotherProject?'已另存此工程配置；原工程配置仍保留。':'配置已保存。可开始此配置扫描，或在任务中心调整资源预算。' }) }
function openProfile(profile: any) { if(busy.value)return;profileId.value = profile.id; profileRevision.value = profile.revision; yaml.value = profile.yaml;savedYaml.value=profile.yaml;formSnapshot.value=null;yamlBackup.value=null;wizardStep.value = 4; profileCheck.value = null;error.value='';notice.value='' }
function newProfile(){if(busy.value)return;profileId.value='';profileRevision.value='';savedYaml.value='';yaml.value='';profileCheck.value=null;formSnapshot.value=null;yamlBackup.value=null;projectName.value='';projectRoot.value='';buildMode.value='cmake';target.value='';toolchain.value='';variant.value='Debug';include.value='';exclude.value='';baseRef.value='';currentRef.value='HEAD';contextRows.value=initialContexts();contextsEditable.value=true;contextsReason.value='';systemHeaders.value='default';wizardStep.value=1;notice.value='';error.value=''}
watch(yaml,()=>{profileCheck.value=null;savedYaml.value=''},{flush:'sync'})
function keydown(event: KeyboardEvent) { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f' && isWorkbench.value) { event.preventDefault(); document.getElementById('variable-search')?.focus() } if (event.key === 'Escape') { compact.value = false; selected.value = null } }
watch(scan, () => { localStorage.setItem('ecra-scan', scan.value); summary.value=null;items.value=[];priorityItems.value=[];selected.value = null; human.value = null; fromCoverage.value=false;offset.value = 0; restoreFilters(scan.value) })
watch(route, () => { if(route.value==='overview' && scan.value) readPage(async()=>{priorityItems.value=(await api(apiScan.value+'/symbols?limit=5')).items}); if (route.value === 'sharing' || route.value === 'settings') readPage(async () => { storage.value = await api('/storage') }); if (route.value === 'projects') readPage(async () => { profileList.value = (await api('/profiles')).items }) })
onMounted(async () => { window.addEventListener('hashchange', hashed); window.addEventListener('keydown', keydown); restoreFilters(scan.value); await run(async () => { bootstrap.value = await api('/bootstrap'); await refresh() }) })
onUnmounted(() => { window.removeEventListener('hashchange', hashed); window.removeEventListener('keydown', keydown) })
</script>

<template>
  <div class="shell">
    <aside :class="{ expanded: compact }"><div class="brand">ECRA <span>Studio</span></div><p class="brand-note">并发风险分析工作台</p>
      <nav aria-label="主导航"><a v-for="[id,title] in navigation" :key="id" :href="'#/'+id" :aria-current="route===id ? 'page' : undefined" @click="go(id)">{{ title }}</a></nav>
      <div class="sidebar-bottom"><a href="#/settings" @click="go('settings')">设置与验收状态</a><small>本地数据 · 中文<br>开发预览 · 发布门禁未通过</small></div>
    </aside>
    <div class="main-shell"><header><button class="menu" aria-label="展开导航" @click="compact=!compact">☰</button><strong>{{ currentScan?.project_id?.slice(0,16) || '尚未选择工程结果' }}</strong><span class="header-scan">{{ scan || '未扫描' }}</span><span class="badge">{{ scan ? (currentScan?.mode==='LOCAL_SNAPSHOT'?'本机扫描快照':'归档证据模式') : '等待工程或结果包' }}</span></header>
      <main><div v-if="error" class="banner error" role="alert">{{ error }}</div><div v-if="notice" class="banner" role="status">{{ notice }}</div><p v-if="busy" class="activity" role="status">正在提交或读取，请稍候…</p><div v-if="summary?.legacy_warning" class="banner warning" role="note">旧归档证据模式：{{summary.legacy_warning}} <button @click="go('sharing')">查看旧文件与复核历史</button></div>
        <template v-if="route==='overview'">
          <div class="page-heading"><div><h1>{{ scan ? '先处理需要核实的变量' : '开始使用 ECRA Studio' }}</h1><p>{{ scan ? '静态、AI 与人工结论分别保留；归档不能替代当前源码核对。' : '选择工程配置，或导入同事发来的完整结果包。' }}</p></div><button class="primary" :disabled="busy" @click="scan ? continueReview() : go('projects')">{{ scan ? '继续人工确认' : '添加工程' }}</button></div>
          <template v-if="summary"><div class="banner warning">{{ label(summary.binding.state) }} · 原源码未重新验证。存在未知或待复核项时，不能形成全工程安全结论。</div>
            <div class="cards"><button v-for="[state,title] in [['SUSPECT','静态疑似'],['UNKNOWN','无法判断'],['SAFE_PROVEN','当前构建已证明安全']]" :key="state" :disabled="busy" @click="drill(state)"><span>{{ title }}</span><strong :class="state">{{ summary.static_counts[state] || 0 }}</strong></button><button :disabled="busy" @click="drill('', 'PENDING')"><span>人工待确认</span><strong>{{ pending }}</strong></button></div>
            <div class="overview-columns"><section class="panel"><h2>按优先级查看与处理</h2><div v-for="item in priorityItems" :key="item.symbol_id" class="todo"><div><strong>{{ item.name }}</strong><p><span class="tag">{{ label(item.static_classification) }}</span> {{ item.definition_file }}:{{ item.definition_line }}</p></div><button @click="go('variables'); select(item)">查看证据</button></div><p class="muted">{{ summary.counting_basis }}</p></section><section class="panel"><h2>覆盖与未完成任务</h2><p>本轮静态清单 {{ summary.total }} 项</p><p>OpenCode 未完成项仍需核实；不将未复核记录视为安全。</p><button @click="go('coverage')">查看覆盖缺口</button><h3>静态类别口径</h3><p v-for="(count,state) in summary.static_counts" :key="state">{{ label(String(state)) }}：{{ count }}</p></section></div>
            <section class="panel"><h2>最近扫描与下一步</h2><p>当前归档 {{ scan }} · {{ currentScan?.profile_id }}</p><template v-if="repeatProfile"><p>按当前已保存配置启动新扫描：{{repeatProfile.id}} · 版本 {{repeatProfile.revision.slice(0,12)}}。扫描会重新核对真实输入，旧归档仍可打开。</p><button :disabled="busy" @click="launchProfile(repeatProfile)">按此配置重新扫描</button><p class="muted">使用自动预算；需要调整时进入扫描任务中心。</p></template><p v-else class="muted">{{profileError||'当前归档没有对应的本机已保存配置；可继续查看与确认，接入真实工程配置后才能启动扫描。'}}</p><p>查看证据 → 人工确认 → 导出标准包/增量 → 在其他电脑继续确认</p></section>
          </template><section v-else class="panel empty"><h2>尚无可打开的静态结果</h2><p>从四步向导保存工程配置，再到任务中心发起真实扫描；也可先导入同事分享的完整结果包。</p><div class="actions"><button @click="go('sharing')">导入结果包</button><button @click="go('projects')">接入工程配置</button></div><p class="muted">示例扫描尚未接入；不会填充演示风险数据。</p></section>
        </template>
        <template v-else-if="route==='projects'">
          <div class="page-heading"><div><h1>接入工程 · 确认真实构建与范围</h1><p>配置保存在独立数据根。高级 YAML 原文保留，仅同步实际修改的普通字段。</p></div><button :disabled="busy" @click="newProfile">新建工程配置</button></div>
          <div class="steps"><span v-for="(text,index) in ['选择工程','确认构建','分析范围','检查与保存']" :class="{current: wizardStep===index+1}">{{ index+1 }} {{ text }}</span></div>
          <div class="overview-columns project-config"><section class="panel wizard-panel"><h2>第 {{ wizardStep }} 步</h2><fieldset class="wizard-fields" :disabled="busy"><div class="wizard-content">
            <template v-if="wizardStep===1"><label>工程名称<input v-model="projectName" placeholder="例如：电机控制 CM7"></label><label>固件目录（绝对路径）<input v-model="projectRoot" placeholder="D:/Firmware/MotorControl"></label><p>仅登记路径，不修改固件与原正式构建目录。</p></template>
            <template v-if="wizardStep===2"><label>真实构建方式<select v-model="buildMode" aria-label="真实构建方式" @change="changeBuildMode"><option value="cmake">CMake + Ninja（外置构建）</option><option value="database">已有 compile_commands.json</option></select></label><label>{{ buildMode==='cmake' ? '目标名称' : '编译数据库路径' }}<input v-model="target"></label><label v-if="buildMode==='cmake'">Toolchain 文件<input v-model="toolchain"></label><label v-if="buildMode==='cmake'">构建变体<input v-model="variant"></label><p v-else>宏、编译变体与工具链以真实编译数据库中的参数为准。</p><label>编译器标准头文件<select v-model="systemHeaders" aria-label="编译器标准头文件"><option value="default">按引擎默认（CMake 开启 / 数据库关闭）</option><option value="on">明确开启 · 从实际编译器探测</option><option value="off">明确关闭 · 使用已有参数</option></select></label><p class="muted">开启会调用真实编译器探测标准头文件目录；编译器缺失会明确失败。保持默认不会补写旧配置字段。</p></template>
            <template v-if="wizardStep===3"><label>变量定义纳入目录（每行一个，空表示全部）<textarea v-model="include" rows="3"></textarea></label><label>排除变量清单目录（每行一个，仍参与调用恢复）<textarea v-model="exclude" rows="3"></textarea></label><ContextEditor v-model="contextRows" :editable="contextsEditable" :reason="contextsReason"/><GitVersions :project-root="projectRoot" v-model:base-ref="baseRef" v-model:current-ref="currentRef"/><p>目录中的逗号与空格按原文保留。未提交输入的完整隔离快照尚待验收。</p></template>
            <template v-if="wizardStep===4"><label>高级完整 YAML<textarea v-model="yaml" rows="9" spellcheck="false" @input="profileCheck=null"></textarea></label><button :disabled="busy" @click="checkProfile">检查配置与工具路径</button><details v-if="profileCheck" class="profile-check" :open="profileCheck.checks.some((item:any)=>!item.available)"><summary>配置路径已检查 · 工具可用 {{profileCheck.checks.filter((item:any)=>item.available).length}} / {{profileCheck.checks.length}} · 展开详情</summary><p>工程：{{ profileCheck.project_root }}</p><p>独立数据：{{ profileCheck.data_root }}</p><p v-for="item in profileCheck.checks">{{ item.tool }}：{{ item.available ? '路径可用' : '缺失' }} · {{ item.path }} {{ item.repair }}</p><div class="banner warning">{{ profileCheck.note }}</div></details></template>
            <div v-if="yamlBackup && wizardStep===4" class="banner" role="note"><p>同步前原文已备份 · {{yamlBackup.bytes}} 字节 · {{yamlBackup.id.slice(0,12)}}</p><button @click="restoreYaml">恢复同步前原文</button></div>
            </div><div class="wizard-actions"><button v-if="wizardStep>1" @click="previousStep">上一步</button><button v-if="wizardStep<4" class="primary" @click="nextStep">下一步</button><button v-else :class="{primary:!savedProfileReady}" :disabled="!profileCheck || busy" @click="saveProfile">保存独立配置</button><button v-if="wizardStep===4" :class="{primary:savedProfileReady}" :disabled="busy||!savedProfileReady" @click="launchProfile(editedProfile)">开始此配置扫描</button></div></fieldset>
          </section><section class="panel"><h2>构建与执行边界</h2><p>真实宏和目标必须来自实际编译命令，工程名称和芯片标签不替代编译参数。</p><p>配置检查并保存后，可直接开始此配置扫描；修改YAML后须重新检查保存。完整输入闭包会在扫描过程中验证。</p><button @click="go('tasks')">进入扫描任务中心</button><p v-if="profileError" class="banner error" role="alert">{{profileError}}</p><h3>已保存配置</h3><button v-for="profile in profileList" class="profile" :disabled="busy" @click="openProfile(profile)">{{ profile.name || profile.id }} · 打开完整 YAML</button></section></div>
        </template>
        <template v-else-if="isWorkbench">
          <div class="page-heading"><div><h1>{{ route==='reviews' ? '人工确认工作台' : '变量与风险' }}</h1><p>静态证据与人工处理独立。原源码不可用时查看全部归档证据。</p></div><button v-if="route==='reviews' && scan" :disabled="busy" @click="continueReview">继续上次位置</button></div>
          <div v-if="route==='reviews' && summary" class="human-counts"><span v-for="(count,state) in summary.human_counts">{{ label(String(state)) }} {{ count }}</span></div>
          <section v-if="summary?.diff" class="banner"><strong>Git 差异：{{summary.diff.pin?.base_ref || summary.diff.pin?.base_sha}} → {{summary.diff.pin?.current_ref || summary.diff.pin?.head_sha}}</strong><p>影响 {{summary.diff.selected_symbol_ids_count}} 项，其中保守扩大 {{summary.diff.conservative_symbol_ids_count}} 项；{{summary.diff.impact_coverage==='COMPLETE'?'影响闭包记录完整':'存在保守扩大，核对回退理由'}}。</p><EvidenceNode :scan="scan" :node="summary.diff.node" title="完整基准、当前版本、可比性与影响理由"/></section><div v-if="scan" class="workbench" :style="{'--list-width':split+'%'}"><section class="list-panel panel"><button v-if="fromCoverage" :disabled="busy" @click="go('coverage')">返回覆盖诊断</button><p v-if="extra.symbol_id" class="identity">精确定位：{{extra.symbol_id}} <button :disabled="busy" @click="extra.symbol_id='';filter()">清除精确定位</button></p><form @submit.prevent="searchList"><label for="variable-search">查找变量、文件或规范身份</label><input id="variable-search" v-model="search" :disabled="busy" placeholder="变量名 / 文件 / symbol_id"><div class="filters"><select aria-label="静态分类" :disabled="busy" v-model="classification" @change="filter"><option value="">全部静态分类</option><option v-for="state in ['SUSPECT','UNKNOWN','SAFE_PROVEN','SHARED_NO_REVIEW','CONTAINER','OUT_OF_BUILD','NON_STORAGE']" :value="state">{{ label(state) }}</option></select><button :disabled="busy">搜索</button></div></form>
            <label>人工状态<select :disabled="busy" v-model="humanFilter" @change="filter"><option value="">全部人工状态</option><option v-for="state in ['PENDING','CONFIRMED_RISK','CONFIRMED_SAFE','NEED_MORE_EVIDENCE','RECHECK_REQUIRED','CONFLICT']" :value="state">{{ label(state) }}</option></select></label><details class="compound-filters"><summary>复合筛选（文件 / 函数 / IRQ / AI / 处理 / 覆盖 / Diff）</summary><label>定义文件包含<input v-model="extra.file" :disabled="busy" @change="filter"></label><label>访问函数身份包含<input v-model="extra.function" :disabled="busy" @change="filter"></label><label>执行上下文 / IRQ 身份<input v-model="extra.context" :disabled="busy" @change="filter" placeholder="例如 main、usart；精确身份"></label><label>AI 复核状态<select aria-label="AI 复核状态" v-model="extra.ai_state" :disabled="busy" @change="filter"><option value="">全部 AI 状态</option><option v-for="state in ['PENDING','DONE','TECH_FAILED','NEED_MORE_CONTEXT','NOT_QUEUED']" :value="state">{{label(state)}}</option></select></label><label>风险处理状态<select aria-label="风险处理状态" v-model="extra.handling_status" :disabled="busy" @change="filter"><option value="">全部处理状态</option><option v-for="state in ['TODO','FIXING','TO_VERIFY','CLOSED','ACCEPTED_RISK','CONFLICT']" :value="state">{{label(state)}}</option></select></label><label>对象覆盖状态<select aria-label="对象覆盖状态" v-model="extra.coverage" :disabled="busy" @change="filter"><option value="">全部覆盖状态</option><option v-for="state in ['COMPLETE','PARTIAL','FAILED','UNKNOWN']" :value="state">{{label(state)}}</option></select></label><label v-if="summary?.diff">Diff 影响范围<select aria-label="Diff 影响范围" v-model="extra.diff" :disabled="busy" @change="filter"><option value="">完整静态清单</option><option value="selected">全部影响项</option><option value="direct">确定依赖影响项</option><option value="conservative">保守扩大项</option></select></label></details><div class="filters"><label>列表排序<select aria-label="列表排序" v-model="extra.sort" :disabled="busy" @change="filter"><option value="priority">风险优先</option><option value="name">变量名称（字典序）</option><option value="definition">定义位置</option><option value="review_priority">待办优先级</option></select></label><label>排序方向<select aria-label="排序方向" v-model="extra.order" :disabled="busy" @change="filter"><option value="asc">升序</option><option value="desc">降序</option></select></label></div><p class="muted">{{ loading ? '正在加载…' : `匹配 ${total} 项；显示 ${total ? offset+1 : 0}–${Math.min(offset+50,total)}` }}</p>
            <div class="symbol-list"><button v-for="item in items" :key="item.symbol_id" :class="{selected:selected?.symbol_id===item.symbol_id}" class="symbol" :disabled="busy" @click="select(item)"><strong>{{ item.name }}</strong><div><span class="tag" :class="item.static_classification">{{ label(item.static_classification) }}</span><span class="tag">{{ label(item.human.decision) }}</span></div><small>{{ item.definition_file }}:{{ item.definition_line }}</small></button><p v-if="!loading && !items.length">没有匹配对象，请调整筛选。</p></div><div class="page-controls"><button :disabled="offset===0 || busy" @click="page(-1)">上一页</button><button :disabled="offset+50>=total || busy" @click="page(1)">下一页</button></div>
          </section><div class="splitter" role="separator" aria-label="调整列表与证据宽度" aria-orientation="vertical" tabindex="0" :aria-valuenow="Math.round(split)" aria-valuemin="30" aria-valuemax="46" @pointerdown="resizeSplit" @pointermove="resizeSplit" @keydown="splitKey"></div><section class="detail-panel panel" :key="selected?.symbol_id || ''"><template v-if="selected"><div class="detail-heading"><h2>{{ selected.name }}</h2><button @click="copyName">复制全名</button></div><p class="identity">{{ selected.symbol_id }}</p><p class="conclusion">静态：{{ label(selected.static_classification) }}；人工：{{ label(human?.decision || 'PENDING') }}。此处展示归档分析证据，不代表目标板实测。</p>
            <div class="detail-tabs" role="tablist" aria-label="证据分组"><button v-for="[id,title] in [['access','时序与访问'],['relations','调用与保护'],['source','归档源码'],['history','人工历史']]" role="tab" :aria-selected="detailTab===id" @click="detailTab=id">{{ title }}</button></div>
            <div class="detail-evidence">
            <section v-show="detailTab==='access'" class="detail-group"><h3>潜在并发与判定条件</h3><p>展开静态理由查看成立前提；证据不足时保持未知。推断时序不是硬件采集。</p><FindingCard v-for="record in findings?.items" :key="record.node" :scan="scan" :node="record.node" :summary="record.summary" @source="openSource"/><p v-if="findings?.total===0">本对象没有独立finding；请核对变量覆盖状态。</p>
            <h3>访问证据 · 共 {{ accesses?.total || 0 }} 项</h3><article v-for="record in accesses?.items" :key="record.ordinal" class="access-row"><strong>{{ label(record.summary.access_kind || '') }} · {{ record.summary.file }}:{{ record.summary.line }}</strong><p>{{ record.summary.function_id }} · {{ record.summary.expression || record.summary.source_text }}</p><button @click="openSource({file:record.summary.file,line:record.summary.line||1})">定位此访问代码</button><EvidenceNode :scan="scan" :node="record.node" :title="'完整访问 #'+(record.ordinal+1)"/></article><button v-if="accesses?.next_offset!==null && accesses?.next_offset!==undefined" @click="run(async()=>{ const next=await api(apiScan+'/records/accesses?symbol_id='+encodeURIComponent(selected.symbol_id)+'&offset='+accesses.next_offset); accesses={...next,items:[...accesses.items,...next.items]} })">继续读取访问</button></section>
            <section v-show="detailTab==='relations'" class="detail-group"><CallTree :key="selected.symbol_id" :scan="scan" :symbol="selected.symbol_id"/><h3>完整相关调用、NVIC、保护、初始化、别名与未知事实</h3><p class="muted">保留全部字段、原始顺序、总数与哈希；可继续逐段读取。</p><template v-for="item in staticFields" :key="item.id"><EvidenceNode v-if="item.kind==='object' || item.kind==='list'" :scan="scan" :node="item.id" :title="field(item.key)"/></template><details><summary>对象所有原始字段（含未来字段）</summary><EvidenceNode :scan="scan" :node="selected.node" title="完整规范对象"/></details></section>
            <section v-if="detailTab==='source' && sourceLocation" class="detail-group"><SourceViewer :scan="scan" :file="sourceLocation.file" :line="sourceLocation.line"/></section>
            <section v-show="detailTab==='history'" class="detail-group"><h3>不可变确认历史 · {{ human?.history?.length || 0 }} 个本轮事件</h3><section v-if="human?.prior_reviews?.length" class="banner warning"><h4>旧扫描确认仅作为历史，当前证据须重新确认</h4><details v-for="prior in human.prior_reviews"><summary>旧扫描 {{prior.binding.scan_id}} · {{prior.events.length}} 个原始事件</summary><article v-for="event in prior.events" class="history-event"><strong>{{label(event.decision)}}</strong><p>{{event.reviewer}} · {{event.timestamp}} · {{event.device}}</p><p>{{event.comment}}</p><small>旧证据指纹 {{event.fingerprint}}</small></article></details></section><article v-for="event in human?.history" class="history-event"><strong>{{ label(event.decision) }} · {{ label(event.handling_status) }}</strong><p>{{ event.reviewer }} · {{ event.timestamp }} · {{ event.device }}</p><p>{{ event.comment }}</p><small>{{ event.event_id }}</small></article></section>
            </div>
            <section class="review-controls"><p class="muted">确认者为未经认证的声明；操作不改变静态/AI分类。</p><div v-if="human?.conflict" class="banner error">离线并行确认冲突：先核对“人工历史”，填写依据后显式合并全部分支。</div><div class="review-fields"><label>确认者<input v-model="reviewer" placeholder="姓名或团队声明"></label><label>独立处理状态<select v-model="handling" aria-label="独立处理状态"><option v-for="state in ['TODO','FIXING','TO_VERIFY','CLOSED','ACCEPTED_RISK']" :value="state">{{ label(state) }}</option></select></label></div><label>依据 / 修改或撤销理由<textarea v-model="comment" rows="2" placeholder="确认无风险必须填写依据或证据引用"></textarea></label><div class="decision-actions"><button :disabled="busy || !reviewer.trim()" @click="saveDecision('CONFIRMED_RISK')">确认有风险</button><button :disabled="busy || !reviewer.trim() || !comment.trim()" @click="saveDecision('CONFIRMED_SAFE')">确认无风险</button><button :disabled="busy || !reviewer.trim()" @click="saveDecision('NEED_MORE_EVIDENCE')">暂无法确认</button><button :disabled="busy || !comment.trim() || !human?.heads?.length || human?.conflict" @click="saveDecision('PENDING', true)">撤销上次确认</button></div></section>
          </template><div v-else class="empty"><h2>选择左侧对象查看完整证据</h2><p>支持同名static的独立身份。Ctrl+F查找，Esc返回列表。</p></div></section></div><section v-else class="panel empty">尚无结果包。请先从“数据与共享”导入。</section>
        </template>
        <template v-else-if="route==='coverage'"><CoverageCenter v-if="scan&&summary" :key="scan" :scan="scan" :roots="summary.roots" @symbol="openCoverageSymbol"/><p v-else>{{scan?'正在读取当前归档；若读取失败，请查看上方诊断。':'尚无可查看的归档。'}}</p></template>
        <template v-else-if="route==='history'"><h1>历史与对比</h1><p>打开保存的不可变静态快照。“本轮未观察到”不等于已修复。跨版本自动继承尚未验收。</p><section class="panel"><article v-for="item in scans" class="history-row"><div><strong>{{ item.scan_id }}</strong><p>{{ item.project_id }} · {{ item.profile_id }} · {{ label(item.state) }}</p></div><button @click="run(async()=>{scan=item.scan_id;await refresh();go('overview')})">打开结果</button></article><p v-if="!scans.length">尚无扫描历史。</p></section></template>
        <template v-else-if="route==='sharing'"><div class="page-heading"><div><h1>数据与共享</h1><p>完整包可在无原固件的电脑查看归档并继续确认。导出可能含敏感代码与备注，请按团队规则分享。</p></div></div><div class="overview-columns"><section class="panel"><h2>导入完整结果</h2><p>校验ZIP路径、数据库结构、全部证据哈希与人工历史后原子发布；失败保留已有数据。</p><label>选择 .ecra-report<input type="file" accept=".ecra-report" :disabled="busy" @change="importFile($event)"></label><template v-if="scan"><h3>合并人工确认增量</h3><label>选择 .ecra-review-delta<input type="file" accept=".ecra-review-delta" :disabled="busy" @change="importFile($event,true)"></label><p>重复导入去重；并行决定保留双方事件，进入显式冲突。</p></template></section><section class="panel"><h2>导出当前归档</h2><p>{{ scan || '尚未选择归档' }}</p><div v-if="scan" class="actions"><button :disabled="busy" @click="exportFile('full')">导出标准完整包</button><button :disabled="busy" @click="exportFile('delta')">导出人工确认增量</button></div><h3>真实数据占用</h3><p class="muted">采样时间 {{storage?.sampled_at || '尚未读取'}}</p><button :disabled="busy" @click="run(async()=>{storage=await api('/storage')})">更新空间占用</button><p v-for="(bytes,name) in storage?.bytes">{{ name }}：{{ (Number(bytes)/1024/1024).toFixed(2) }} MiB</p><p class="muted">{{ storage?.reason }}</p></section></div><MigrationCenter @completed="readPage(async()=>{storage=await api('/storage');scans=(await api('/scans')).items})" @open="async(id:string)=>{scan=id;await refresh();go('overview')}" /><LegacyArchive v-if="summary?.legacy_warning" :key="scan" :scan="scan" @evidence="go('coverage')" /><CleanupCenter /></template>
        <template v-else-if="route==='tasks'"><TaskCenter :focus-task="taskFocus" @focus="rememberTask" @open="async(id:string)=>{scan=id;await refresh();go('overview')}" /></template>
        <template v-else-if="route==='opencode'"><ReviewCenter v-if="scan&&summary" :key="scan" :scan="scan" :project-id="summary.binding.project_id" :can-review="summary.can_review" @tasks="openTasks"/><section v-else class="panel"><h1>OpenCode 复核</h1><p>先打开已保存的真实扫描或结果包。</p></section></template>
        <template v-else><h1>设置与验收状态</h1><section class="panel"><h2>独立数据根</h2><p class="identity">{{ bootstrap?.data_root }}</p><p>可在启动前设置 ECRA_DATA_ROOT 为其他盘的绝对路径。升级软件不覆盖此数据目录。</p><h2>明确的能力边界</h2><p v-for="item in bootstrap?.limits">{{ item }}</p><p>大型原生全量/Diff、32GB资源、干净机Portable及真实工程师盲测尚未完成，不宣称完整发布。</p></section></template>
      </main>
    </div>
  </div>
</template>
