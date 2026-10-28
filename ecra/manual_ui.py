"""Small extension to the existing offline report, no frontend dependencies."""
import json

from .common import digest
from .manual_review import LABELS, targets


def entry(symbol_id):
    from .html_report import esc
    vid = digest(['storage-v1', symbol_id])
    return ('<div class="manual-entry" data-manual-id="' + vid + '">'
            '<span class="tag" data-manual-label>人工确认：需连接本地服务</span> '
            '<button type="button" data-manual-edit="' + esc(vid) + '" data-choice="CONFIRMED_RISK" disabled>确认有风险</button> '
            '<button type="button" data-manual-edit="' + esc(vid) + '" data-choice="CONFIRMED_SAFE" disabled>确认无风险</button> '
            '<button type="button" data-manual-edit="' + esc(vid) + '" data-choice="UNCONFIRMED" disabled>撤销确认</button>'
            '<span class="manual-disagreement"></span></div>')


def render(facts, report, records):
    from .html_report import anchor, esc, panel, row, table, VERDICTS, to_display_text
    variables = sorted(targets(facts, report), key=lambda v: (v.get('qualified_name', ''), v['symbol_id']))
    rows = []
    for v in variables:
        sid = v['symbol_id']
        vid = digest(['storage-v1', sid])
        reviews = [records.get(f['finding_id'], {}) for f in report['findings'] if f.get('symbol_id') == sid]
        verdicts = '；'.join(dict.fromkeys(VERDICTS.get(r.get('status'), '尚未完成 / 证据不足')
                              if r.get('state') == 'DONE' else '尚未完成 / 证据不足' for r in reviews))
        cells = ['<a href="#' + anchor('var-', sid) + '">' + esc(v.get('qualified_name', sid)) + '</a><p>'
                 + esc(v.get('definition_file')) + ':' + esc(v.get('definition_line')) + '</p>',
                 '<p>静态扫描：' + esc(to_display_text(v.get('static_classification'))) + '</p><p>OpenCode 复核：'
                 + esc(verdicts or '未送入复核') + '</p><a href="#' + anchor('var-', sid) + '">查看源码、访问和调用链</a>',
                 entry(sid)]
        rows.append(row(cells, 'manual-' + vid, 'UNCONFIRMED', file=v.get('definition_file'),
                        search_text=v.get('qualified_name', sid) + ' ' + str(v.get('definition_file', ''))))
    options = [('all', '全部待核对变量'), ('unfinished', '待人工确认 + 需重新确认')] + list(LABELS.items())
    body = table(['变量', '原始结论与证据', '人工确认'], rows, 'manual-table', True)
    section = panel('manual', '人工确认', '按实际存储变量计数；结构体容器、独立证据缺口和静态安全项不计入。人工结论独立保存。', body, options)
    banner = '''<aside class="next-actions" id="manual-overview"><h2>人工确认进度</h2>
<p id="manual-message" role="status">人工确认需要启动本地服务：py -3.10 run_ecra.py serve。离线报告仅供查看，未保存任何人工操作。</p>
<p id="manual-progress">需确认总数：''' + str(len(variables)) + '''；连接服务后恢复最新进度。</p>
<progress id="manual-meter" max="100" value="0" aria-label="人工确认完成率"></progress>
<p><button type="button" id="manual-continue" disabled>继续确认</button>
<button type="button" id="manual-refresh" disabled>重新加载人工状态</button>
<button type="button" id="manual-export" disabled>导出记录与历史</button>
<button type="button" id="manual-import-button" disabled>导入记录</button>
<button type="button" id="manual-all-history" disabled>查看全部历史（含范围外变量）</button>
<input type="file" accept="application/json,.json" id="manual-import" hidden></p></aside>
<dialog id="manual-dialog"><form id="manual-form"><h2 id="manual-title">人工确认</h2>
<p>请先核对变量的源码、访问、调用链及 OpenCode 依据。</p>
<p><label>确认结论 <select id="manual-decision"><option value="CONFIRMED_RISK">确认有风险</option><option value="CONFIRMED_SAFE">确认无风险</option><option value="UNCONFIRMED">撤销确认</option></select></label></p>
<p><label>确认依据 / 修改或撤销原因<br><textarea id="manual-reason" rows="5" maxlength="10000" style="width:100%"></textarea></label></p>
<p><label>实际触发条件 / 备注<br><textarea id="manual-conditions" rows="2" maxlength="3000" style="width:100%"></textarea></label></p>
<p><label>确认人 <input id="manual-reviewer" maxlength="200"></label></p>
<p id="manual-save-message" role="status"></p>
<button type="submit" id="manual-save">保存确认</button> <button type="button" id="manual-history">查看此变量历史</button>
<button type="button" id="manual-close">关闭</button><pre id="manual-history-text" style="white-space:pre-wrap;max-height:30vh;overflow:auto"></pre></form></dialog>'''
    payload = json.dumps(dict(fingerprint=report.get('fingerprint'), labels=LABELS), ensure_ascii=False).replace('<', '\\u003c')
    return banner, section, 'const manualConfig=' + payload + ';\n' + SCRIPT


SCRIPT = r"""
const manualMessage=document.getElementById('manual-message'), manualDialog=document.getElementById('manual-dialog');
let manualState=null, manualItems=new Map(), manualEditing=null, manualBusy=false;
const manualNodes=new Map();for(const node of document.querySelectorAll('[data-manual-id]')){const id=node.dataset.manualId;if(!manualNodes.has(id))manualNodes.set(id,[]);manualNodes.get(id).push(node);}
async function manualApi(path,body){const opts={cache:'no-store',credentials:'same-origin'};if(body){opts.method='POST';opts.headers={'Content-Type':'application/json','X-ECRA-Token':manualState.token};opts.body=JSON.stringify({...body,report_fingerprint:manualConfig.fingerprint});}const response=await fetch(path,opts);const result=await response.json();if(!response.ok)throw new Error(result.error||'请求失败');return result;}
function manualApply(state){manualState=state;manualItems=new Map(state.rows.map(r=>[r.variable_id,r]));const available=state.valid&&state.report_fingerprint===manualConfig.fingerprint;
manualMessage.textContent=available?'已连接本地数据库；保存成功后才会更新确认状态。':('当前证据不可用，请重新扫描或打开新报告：'+(state.error||'报告版本已变化'));
for(const id of ['manual-continue','manual-refresh','manual-export','manual-import-button','manual-all-history'])document.getElementById(id).disabled=id==='manual-refresh'||id==='manual-export'||id==='manual-all-history'?false:!available;
const p=state.progress,c=p.counts;document.getElementById('manual-progress').textContent='需确认总数：'+p.total+' · 已确认有风险：'+c.CONFIRMED_RISK+' · 已确认无风险：'+c.CONFIRMED_SAFE+' · 待确认：'+c.UNCONFIRMED+' · 需重新确认：'+c.NEEDS_RECHECK+' · 完成率：'+p.percent.toFixed(2)+'%';document.getElementById('manual-meter').value=p.percent;
for(const [id,nodes] of manualNodes){const item=manualItems.get(id);for(const node of nodes){const signature=JSON.stringify([available,item?.decision,(item?.reviews||[]).map(r=>[r.state,r.verdict])]);if(node.dataset.manualSignature===signature)continue;node.dataset.manualSignature=signature;node.querySelector('[data-manual-label]').textContent='人工确认：'+(item?manualConfig.labels[item.decision]:'不在当前核对范围');for(const b of node.querySelectorAll('button'))b.disabled=!available||!item;const verdicts=(item?.reviews||[]).filter(r=>r.state==='DONE').map(r=>r.verdict);const disagreement=item&&((item.decision==='CONFIRMED_SAFE'&&verdicts.some(v=>['CONFIRMED','LIKELY'].includes(v)))||(item.decision==='CONFIRMED_RISK'&&verdicts.some(v=>['REVIEWED_SAFE','FALSE_POSITIVE'].includes(v))));node.querySelector('.manual-disagreement').textContent=disagreement?' 人工结论与 OpenCode 结论存在分歧':'';}const tr=document.getElementById('manual-'+id);if(tr&&item)tr.dataset.group=item.decision;}
const body=document.querySelector('#manual-table>tbody');if(body){const ordered=[...body.children].sort((a,b)=>{const score=r=>['UNCONFIRMED','NEEDS_RECHECK'].includes(r.dataset.group)?0:1;return score(a)-score(b);});let cursor=null;for(const r of [...ordered].reverse()){if(r.nextElementSibling!==cursor)body.insertBefore(r,cursor);cursor=r;}const view=views.find(v=>v.pager.dataset.table==='manual-table');if(view)view.rows=ordered.filter(r=>r.dataset.group);}
search(false);}
async function manualLoad(){try{manualApply(await manualApi('/api/state'));}catch(error){manualMessage.textContent='读取人工状态失败：'+error.message;for(const node of manualNodes.values())for(const n of node){delete n.dataset.manualSignature;for(const b of n.querySelectorAll('button'))b.disabled=true;}}}
function manualContinue(){const next=[...manualItems.values()].find(r=>['UNCONFIRMED','NEEDS_RECHECK'].includes(r.decision));if(!next){manualMessage.textContent='当前范围已全部完成人工确认。';return;}const hash='#manual-'+next.variable_id;if(!document.getElementById('manual-table')){location.href='index.html'+hash;return;}if(location.hash===hash)reveal();else location.hash=hash;}
function manualEdit(id,choice){manualEditing=manualItems.get(id);if(!manualEditing)return;document.getElementById('manual-title').textContent='人工确认：'+manualEditing.variable_name;document.getElementById('manual-decision').value=choice||'CONFIRMED_RISK';document.getElementById('manual-save').disabled=false;document.getElementById('manual-history').disabled=false;document.getElementById('manual-reason').value='';document.getElementById('manual-conditions').value='';document.getElementById('manual-reviewer').value=manualEditing.reviewer==='系统'?'':manualEditing.reviewer||'';document.getElementById('manual-save-message').textContent=manualEditing.reason?'上次依据：'+manualEditing.reason:'';document.getElementById('manual-history-text').textContent='';manualDialog.showModal();}
for(const button of document.querySelectorAll('[data-manual-edit]'))button.addEventListener('click',()=>manualEdit(button.dataset.manualEdit,button.dataset.choice));
document.getElementById('manual-continue').addEventListener('click',manualContinue);
document.getElementById('manual-refresh').addEventListener('click',manualLoad);
document.getElementById('manual-close').addEventListener('click',()=>{if(!manualBusy)manualDialog.close();});
manualDialog.addEventListener('cancel',e=>{if(manualBusy)e.preventDefault();});
document.getElementById('manual-form').addEventListener('submit',async e=>{e.preventDefault();if(manualBusy||!manualEditing)return;const decision=document.getElementById('manual-decision').value,reason=document.getElementById('manual-reason').value.trim(),conditions=document.getElementById('manual-conditions').value.trim(),message=document.getElementById('manual-save-message');if((decision==='CONFIRMED_SAFE'||manualEditing.decision!=='UNCONFIRMED')&&!reason){message.textContent='请填写人工确认依据或修改 / 撤销原因。';return;}manualBusy=true;document.getElementById('manual-save').disabled=true;message.textContent='正在保存到本地数据库…';try{const state=await manualApi('/api/decision',{variable_id:manualEditing.variable_id,revision:manualEditing.revision,evidence_digest:manualEditing.evidence_digest,analysis_scope_id:manualEditing.analysis_scope_id,decision,reason:reason+(conditions?'\n实际触发条件 / 备注：'+conditions:''),reviewer:document.getElementById('manual-reviewer').value});manualApply(state);manualDialog.close();manualMessage.textContent='保存成功，确认状态与进度已更新。可点击“继续确认”核对下一项。';}catch(error){message.textContent='保存失败，未确认成功：'+error.message;await manualLoad();}finally{manualBusy=false;document.getElementById('manual-save').disabled=false;}});
function manualHistoryText(events){return events.map(h=>{const r=h.current;return h.timestamp+' · '+(r?.variable_name||'变量')+' · '+(manualConfig.labels[h.old_decision]||h.old_decision)+' → '+(manualConfig.labels[h.new_decision]||h.new_decision)+' · 修订 '+h.revision+'\n确认人：'+h.reviewer+'\n依据：'+h.reason+(r?.imported_history?'\n导入的历史：'+JSON.stringify(r.imported_history,null,2):'');}).join('\n\n')||'尚无人工操作历史。';}
document.getElementById('manual-history').addEventListener('click',async()=>{try{const data=await manualApi('/api/history?variable_id='+encodeURIComponent(manualEditing.variable_id));document.getElementById('manual-history-text').textContent=manualHistoryText(data.history);}catch(e){document.getElementById('manual-history-text').textContent='读取历史失败：'+e.message;}});
document.getElementById('manual-all-history').addEventListener('click',async()=>{try{const data=await manualApi('/api/history');manualEditing=null;document.getElementById('manual-save').disabled=true;document.getElementById('manual-history').disabled=true;document.getElementById('manual-title').textContent='全部人工操作历史（含范围外变量）';document.getElementById('manual-history-text').textContent=manualHistoryText(data.history);document.getElementById('manual-save-message').textContent='仅供查看；请从变量入口修改确认。';manualDialog.showModal();}catch(e){manualMessage.textContent='读取历史失败：'+e.message;}});
document.getElementById('manual-export').addEventListener('click',async()=>{try{const data=await manualApi('/api/export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='ecra-manual-review.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){manualMessage.textContent='导出失败：'+e.message;}});
document.getElementById('manual-import-button').addEventListener('click',()=>document.getElementById('manual-import').click());
document.getElementById('manual-import').addEventListener('change',async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>8*1024*1024)throw new Error('文件超过 8 MiB');const document=JSON.parse(await file.text()),revisions=manualState.revisions;manualApply(await manualApi('/api/import',{document,revisions}));manualMessage.textContent='导入成功；不匹配当前证据的历史结论已标记为需重新确认。';}catch(error){manualMessage.textContent='导入失败：'+error.message;}finally{e.target.value='';}});
if(location.protocol==='http:'&&location.hostname==='127.0.0.1')manualLoad();
"""
