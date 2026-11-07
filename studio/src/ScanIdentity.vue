<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { label } from './api'
import './scan-identity.css'
import WorkspaceDialog from './WorkspaceDialog.vue'
const props=defineProps<{scan:string,binding:any,identity:any,mode:string}>()
const opened=ref(false),trigger=ref<HTMLButtonElement|null>(null)
const project=computed(()=>props.identity?.project_name||'工程名称未记录')
const build=computed(()=>`${props.identity?.configured_target||'目标未记录'} · ${props.identity?.build_variant||'变体未记录'} · 核心声明 ${props.identity?.project_core||'未记录'}`)
const status=computed(()=>props.binding?.state?label(props.binding.state):'结果身份读取中')
function open(){opened.value=true}
async function close(){opened.value=false;await nextTick();trigger.value?.focus()}
</script>
<template>
  <template v-if="scan">
    <button ref="trigger" type="button" class="scan-identity-trigger" aria-label="查看当前工程与构建身份" :title="project+' · '+build" @click="open">
      <strong>{{project}}</strong><small>{{build}}</small>
    </button>
    <span class="header-scan" :title="scan">批次 {{scan}}</span>
    <span class="badge">{{mode==='LOCAL_SNAPSHOT'?'本机扫描快照':'归档证据模式'}}<br>{{status}}</span>
    <WorkspaceDialog v-if="opened" title="当前工程与构建身份" @close="close">
      <p class="banner warning">{{identity?.note||'正在读取归档身份；不表示当前源码已经重新验证。'}}</p>
      <dl class="scan-identity-fields">
        <dt>工程名称</dt><dd>{{project}}<small>{{identity?.project_name_source||'正在读取归档身份'}}</small></dd>
        <dt>归档工程根</dt><dd>{{identity?.project_root||'未记录'}}</dd>
        <dt>芯片 / 核心（配置声明）</dt><dd>{{identity?.project_chip||'芯片未记录'}}<br>{{identity?.project_core||'核心未记录'}}</dd>
        <dt>配置目标</dt><dd>{{identity?.configured_target||'未记录；不能从变量或芯片名称推断'}}</dd>
        <dt>构建变体</dt><dd>{{identity?.build_variant||'未记录'}}</dd>
        <dt>实际编译数据库</dt><dd>{{identity?.compile_database||'未记录'}}</dd>
        <dt>配置文件 / SHA-256</dt><dd>{{identity?.config_file||'未记录'}}<br>{{identity?.config_sha256||'未记录'}}</dd>
        <dt>工程ID / 配置ID</dt><dd>{{binding?.project_id||'读取中'}}<br>{{binding?.profile_id||'读取中'}}</dd>
        <dt>批次 / 生成时间</dt><dd>{{scan}}<br>{{identity?.generated_at||'未记录'}}</dd>
        <dt>发布状态 / 静态覆盖</dt><dd>{{status}}<br>{{identity?.analysis_status==='INCOMPLETE'?'部分覆盖（INCOMPLETE）':identity?.analysis_status?label(identity.analysis_status):'未记录'}}</dd>
        <dt>归档记录的Git提交</dt><dd>{{identity?.recorded_git_commit&&identity.recorded_git_commit!=='unknown'?identity.recorded_git_commit:'未记录可用Git提交'}}</dd>
        <template v-if="identity?.diff"><dt>固定比较方向</dt><dd>{{identity.diff.base_ref||'未记录'}} → {{identity.diff.current_ref||'未记录'}}<br>{{identity.diff.base_sha||'未记录'}} → {{identity.diff.head_sha||'未记录'}}<br>未提交输入：{{identity.diff.include_uncommitted===true?'纳入':identity.diff.include_uncommitted===false?'不纳入':'未记录'}}</dd></template>
      </dl>
      <p v-if="identity?.metadata_note" class="banner warning">{{identity.metadata_note}}</p>
      <p v-if="identity?.oversized_fields?.length" class="banner warning">以下字段超过身份栏读取上限，请从完整证据页分段查看：{{identity.oversized_fields.join('、')}}</p>
      <template #footer><button type="button" @click="close">关闭身份详情</button></template>
    </WorkspaceDialog>
  </template>
  <template v-else><strong>尚未选择工程结果</strong><span class="header-scan">未扫描</span><span class="badge">等待工程或结果包</span></template>
</template>
