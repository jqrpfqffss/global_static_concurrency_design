type Request = (path:string)=>Promise<any>
export type IdentityKind = 'function'|'context'
export type EvidenceName = {name:string, detail?:string, missing?:boolean}
const contextKinds:Record<string,string>={MAIN:'主循环',ISR:'中断',TASK:'任务',RTOS_TASK:'任务',CALLBACK:'回调',DMA:'DMA 上下文',CORE:'核心',FOREGROUND:'前台',IRQ:'中断',EXTERNAL_ASYNC:'外部异步',UNKNOWN_CONTEXT:'未知执行上下文'}

export function createEvidenceNames(request:Request, capacity=128) {
  const cache=new Map<string,Promise<EvidenceName>>()
  async function read(scan:string,kind:IdentityKind,id:string):Promise<EvidenceName> {
    const base='/scans/'+encodeURIComponent(scan)+'/records/'
    if(kind==='function'){
      const page=await request(base+'functions?function_id='+encodeURIComponent(id)+'&limit=1')
      const row=page.items[0]?.summary
      return row?{name:row.qualified_name||row.name||id,detail:page.total>1?`归档定义 ${page.total} 处；完整调用证据保留全部定义`:undefined}:{name:'函数名称未记录',missing:true}
    }
    let offset=0
    while(true){
      const page=await request(base+'contexts?limit=200&offset='+offset)
      const row=page.items.find((item:any)=>item.summary?.id===id)?.summary
      if(row)return {name:[contextKinds[row.kind]||`执行上下文（${row.kind||'种类待核实'}）`,row.physical_id].filter(Boolean).join(' · ')}
      if(page.next_offset===null)return {name:'执行上下文待核实',missing:true}
      if(!Number.isInteger(page.next_offset)||page.next_offset<=offset)throw Error('上下文分页未前进')
      offset=page.next_offset
    }
  }
  return (scan:string,kind:IdentityKind,id:string):Promise<EvidenceName>=>{
    const key=JSON.stringify([scan,kind,id]),found=cache.get(key)
    if(found){cache.delete(key);cache.set(key,found);return found}
    const pending=read(scan,kind,id).catch(error=>{if(cache.get(key)===pending)cache.delete(key);throw error})
    cache.set(key,pending)
    while(cache.size>capacity)cache.delete(cache.keys().next().value!)
    return pending
  }
}
