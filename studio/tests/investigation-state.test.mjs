import test from 'node:test'
import assert from 'node:assert/strict'
import { ReviewDrafts } from '../src/reviewDrafts.ts'
import { createEvidenceNames } from '../src/evidenceNames.ts'

test('drafts distinguish same-name static objects and scans; committing one keeps others',()=>{
  const drafts=new ReviewDrafts(),note={comment:'check IRQ path',handling:'TO_VERIFY',fingerprint:'f1',heads:'[]'}
  drafts.update('scan1','a.c::counter',note,'TODO')
  drafts.update('scan1','b.c::counter',{...note,comment:'other translation unit'},'TODO')
  drafts.update('scan2','a.c::counter',{...note,fingerprint:'f2'},'TODO')
  note.comment='mutated caller object'
  assert.equal(drafts.get('scan1','a.c::counter').comment,'check IRQ path')
  drafts.remove('scan1','a.c::counter')
  assert.equal(drafts.size,2)
  assert.equal(drafts.get('scan1','b.c::counter').comment,'other translation unit')
  assert.equal(drafts.get('scan2','a.c::counter').fingerprint,'f2')
})

test('state-only edits are drafts; reverting to saved state clears the leave warning',()=>{
  const drafts=new ReviewDrafts(),note={comment:'',handling:'FIXING',fingerprint:'f',heads:'["event"]'}
  drafts.update('a','x',note,'TODO');assert.equal(drafts.size,1)
  drafts.update('a','x',{...note,handling:'TODO'},'TODO');assert.equal(drafts.size,0)
  drafts.update('a','x',{...note,comment:'reason',handling:'TODO'},'TODO');assert.equal(drafts.size,1)
})

test('function names use exact identities, never names parsed from a USR',async()=>{
  const requests=[]
  const names=createEvidenceNames(async path=>{
    requests.push(path)
    return path.includes(encodeURIComponent('a.c::helper'))?{total:2,items:[{summary:{qualified_name:'helper(unsigned int)'}}]}:{total:0,items:[]}
  })
  assert.equal((await names('s','function','a.c::helper')).name,'helper(unsigned int)')
  assert.equal((await names('s','function','b.c::helper')).missing,true)
  assert.equal((await names('s','function','c:@F@invented')).missing,true)
  assert.equal(requests.length,3)
})

test('context pages retain unknowns and use exact archived identities',async()=>{
  const requests=[]
  const names=createEvidenceNames(async path=>{
    requests.push(path)
    return path.endsWith('offset=0')?{items:[{summary:{id:'irq-similar',kind:'MAIN',physical_id:'FOREGROUND'}}],next_offset:200}:{items:[{summary:{id:'irq',kind:'ISR',physical_id:'IRQ:SysTick_Handler'}}],next_offset:null}
  })
  assert.equal((await names('s','context','irq')).name,'中断 · IRQ:SysTick_Handler')
  assert.equal(requests.length,2)
  assert.equal((await names('s','context','vector:slot:999')).missing,true)
})

test('duplicate lookups share in-flight reads; failed names can retry',async()=>{
  let count=0,resolve
  const names=createEvidenceNames(()=>{count++;return new Promise(r=>{resolve=r})})
  const first=names('s','function','f'),second=names('s','function','f')
  assert.equal(first,second);assert.equal(count,1)
  resolve({total:1,items:[{summary:{name:'actual'}}]});assert.equal((await first).name,'actual')
  let attempt=0
  const retry=createEvidenceNames(async()=>{if(++attempt===1)throw Error('offline');return {items:[],total:0}})
  await assert.rejects(retry('s','function','x'),/offline/)
  assert.equal((await retry('s','function','x')).missing,true);assert.equal(attempt,2)
})

test('bounded name cache evicts old pages and separates archives',async()=>{
  let count=0
  const names=createEvidenceNames(async()=>{count++;return {items:[],total:0}},2)
  await names('s1','function','a');await names('s1','function','b');await names('s1','function','c')
  await names('s1','function','a');await names('s2','function','a');assert.equal(count,5)
})

test('malformed context pagination fails visibly instead of looping or claiming a match',async()=>{
  const names=createEvidenceNames(async()=>({items:[],next_offset:0}))
  await assert.rejects(names('s','context','x'),/分页未前进/)
})

test('known unresolved and DMA context kinds are labels, future kinds remain explicit',async()=>{
  const names=createEvidenceNames(async()=>({items:[
    {summary:{id:'a',kind:'UNKNOWN_CONTEXT'}},{summary:{id:'b',kind:'DMA'}},
    {summary:{id:'c',kind:'FUTURE_KIND'}}],next_offset:null}))
  assert.equal((await names('s','context','a')).name,'未知执行上下文')
  assert.equal((await names('s','context','b')).name,'DMA 上下文')
  assert.equal((await names('s','context','c')).name,'执行上下文（FUTURE_KIND）')
})
