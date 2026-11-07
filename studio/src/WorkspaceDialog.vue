<script setup lang="ts">
import { computed, inject, onMounted, onBeforeUnmount, ref, type Ref } from 'vue'
const props=defineProps<{title:string,error?:string}>()
const applicationError=inject<Ref<string>|null>('workspace-error',null)
const visibleError=computed(()=>props.error||applicationError?.value||'')
const emit=defineEmits<{close:[],keydown:[event:KeyboardEvent]}>()
const dialog=ref<HTMLDialogElement|null>(null), maximized=ref(false)
let previous:HTMLElement|null=null
onMounted(()=>{previous=document.activeElement as HTMLElement;dialog.value?.showModal()})
onBeforeUnmount(()=>{dialog.value?.close();if(previous?.isConnected)previous.focus()})
</script>
<template>
 <Teleport to="body"><dialog ref="dialog" class="workspace-dialog" :class="{maximized}" :aria-label="title" @cancel.prevent.stop="emit('close')" @keydown="emit('keydown',$event)" @keydown.esc.stop>
  <div class="dialog-heading"><h2>{{title}}</h2><div class="actions"><button @click="maximized=!maximized">{{maximized?'还原窗口':'最大化窗口'}}</button><button aria-label="关闭窗口" @click="emit('close')">关闭</button></div></div>
  <p v-if="visibleError" class="dialog-error banner error" role="alert">{{visibleError}}</p>
  <div class="dialog-body"><slot/></div>
  <div v-if="$slots.footer" class="dialog-footer"><slot name="footer"/></div>
 </dialog></Teleport>
</template>
<style>
.workspace-dialog{width:min(1040px,calc(100vw - 32px));height:min(720px,calc(100dvh - 32px));max-width:none;max-height:none;margin:auto;padding:0;border:1px solid #bfcddd;border-radius:6px;color:#22344d;background:white;overflow:hidden}.workspace-dialog[open]{display:flex;flex-direction:column}.workspace-dialog::backdrop{background:#17283d80}.workspace-dialog.maximized{width:calc(100vw - 16px);height:calc(100dvh - 16px)}
.dialog-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:8px 16px;border-bottom:1px solid #d9e1ed;flex-shrink:0}.dialog-heading h2{margin:0;font-size:18px}.dialog-body{flex:1;min-height:0;overflow:auto;padding:16px}.dialog-footer{padding:8px 16px;display:flex;justify-content:space-between;align-items:center;gap:12px;border-top:1px solid #d9e1ed;flex-shrink:0}.dialog-footer p{margin:0;min-width:0;overflow-wrap:anywhere}.dialog-footer .actions{flex-shrink:0}
.dialog-error{margin:8px 16px 0;flex-shrink:0}
@media(max-height:600px),(max-width:700px){.workspace-dialog{width:calc(100vw - 16px);height:calc(100dvh - 16px)}.dialog-heading{padding:4px 8px;gap:4px}.dialog-heading h2{font-size:16px}.dialog-body{padding:8px}.dialog-footer{padding:4px 8px;flex-wrap:wrap}}
</style>
