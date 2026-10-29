"""Lossless offline evidence sidecars for large HTML reports.

Only presentation is split. Analysis, classifications, JSON and SQLite facts
remain complete. Files are content-addressed and the report index keeps every
variable; opening a detail loads its own document instead of a giant template.
"""
from contextvars import ContextVar
import hashlib
import html
import json
from pathlib import Path
import re
import uuid

CURRENT = ContextVar('ecra_html_evidence', default=None)
_IDS = re.compile(r'(?<![\w-])id=["\']([^"\']+)["\']')

EXTERNAL_SCRIPT = r"""
function syncEvidenceFrame(d){
let visible=d.open;for(let p=d;visible&&p;p=p.parentElement)if(p.hidden||(p!==d&&p.tagName==='DETAILS'&&!p.open))visible=false;
if(visible){const t=d.querySelector(':scope > template[data-ecra-frame="1"]');if(t){d.append(t.content);t.remove();}}
for(const f of d.querySelectorAll(':scope > iframe[data-ecra-src]')){
 if(visible){if(!f.hasAttribute('src')){f.loading='eager';f.src=f.dataset.ecraSrc;}}
 else{const t=document.createElement('template');t.dataset.ecraFrame='1';t.content.append(f);f.removeAttribute('src');d.append(t);}
}}
document.addEventListener('toggle',e=>{const d=e.target;if(d.tagName!=='DETAILS')return;
if(d.dataset.externalDetail==='1')syncEvidenceFrame(d);
for(const child of d.querySelectorAll('details[data-external-detail="1"][open]'))syncEvidenceFrame(child);},true);
new MutationObserver(()=>{for(const d of document.querySelectorAll('details[data-external-detail="1"][open]'))syncEvidenceFrame(d);})
 .observe(document.documentElement,{subtree:true,attributes:true,attributeFilter:['hidden']});
let evidenceAnchorsPromise;
async function evidenceDestination(id){
 if(!window.ECRA_EVIDENCE_ANCHORS){
  if(!evidenceAnchorsPromise)evidenceAnchorsPromise=new Promise((resolve,reject)=>{const s=document.createElement('script');s.src=(document.documentElement.dataset.ecraRoot||'')+'html_details/anchors.js';s.onload=()=>window.ECRA_EVIDENCE_ANCHORS?resolve():reject(Error('证据导航索引无效'));s.onerror=()=>reject(Error('完整证据导航索引载入失败'));document.head.append(s);});
  await evidenceAnchorsPromise;
 }
 return window.ECRA_EVIDENCE_ANCHORS[id];
}
async function routeEvidence(id){
 if(!id||document.getElementById(id))return;
 try{const destination=await evidenceDestination(id);if(!destination)return;const root=document.documentElement.dataset.ecraRoot||'';const url=root+destination+'#'+encodeURIComponent(id);if(destination==='index.html')window.top.location.href=url;else location.href=url;}
 catch(error){let note=document.getElementById('ecra-navigation-error');if(!note){note=document.createElement('p');note.id='ecra-navigation-error';note.setAttribute('role','alert');document.body.prepend(note);}note.textContent=error.message+'；请从首页变量详情重新打开完整证据。';}
}
document.addEventListener('click',e=>{const a=e.target.closest('a[href^="#"]');if(!a)return;let id;try{id=decodeURIComponent(a.getAttribute('href').slice(1));}catch{return;}if(document.getElementById(id))return;e.preventDefault();routeEvidence(id);});
function routeEvidenceHash(){let id;try{id=decodeURIComponent(location.hash.slice(1));}catch{return;}routeEvidence(id);}
window.addEventListener('hashchange',routeEvidenceHash);routeEvidenceHash();
"""

DETAIL_SCRIPT = r"""
document.addEventListener('toggle',e=>{const d=e.target;if(d.tagName!=='DETAILS'||!d.open)return;const t=[...d.children].find(c=>c.tagName==='TEMPLATE');if(t){d.append(t.content);t.remove();}},true);
function revealEvidence(){let id;try{id=decodeURIComponent(location.hash.slice(1));}catch{return;}const target=document.getElementById(id);if(!target)return;for(let p=target.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;target.scrollIntoView({block:'start'});}
window.addEventListener('hashchange',revealEvidence);revealEvidence();
for(const b of document.querySelectorAll('[data-copy]'))b.addEventListener('click',async()=>{const note=b.nextElementSibling;try{await navigator.clipboard.writeText(b.dataset.copy);note.textContent='已复制';}catch{const area=document.createElement('textarea');area.value=b.dataset.copy;area.readOnly=true;area.style.width='100%';note.append(area);area.focus();area.select();}});
"""


def large(value, budget=32768):
    """Bounded size probe; never serialize a whole evidence tree to measure it."""
    pending, visited = [value], 0
    while pending:
        item = pending.pop()
        visited += 1
        if visited > 256 or budget < 0:
            return True
        if isinstance(item, str):
            budget -= len(item)
        elif isinstance(item, dict):
            if len(item) + len(pending) > 256:
                return True
            pending.extend(item.values())
            budget -= sum(len(str(key)) for key in item)
        elif isinstance(item, (list, tuple)):
            if len(item) + len(pending) > 256:
                return True
            pending.extend(item)
        else:
            budget -= 20
    return budget < 0


class HtmlEvidence:
    def __init__(self, out, fingerprint, style, threshold=131072):
        self.out, self.fingerprint, self.threshold = Path(out), fingerprint, threshold
        self.folder = self.out/'html_details'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.files, self.anchors = {}, {}
        self.searches = {}
        self.max_detail_chars = 0
        self.style_name = self.put('css', [style])

    def __enter__(self):
        from .common import write_json
        write_json(self.folder/'manifest.json', dict(fingerprint=self.fingerprint, complete=False), indent=None)
        self.token = CURRENT.set(self)
        return self

    def __exit__(self, kind, value, trace):
        CURRENT.reset(self.token)
        if kind is None:
            from .common import write_json
            write_json(self.folder/'manifest.json', dict(fingerprint=self.fingerprint,
                complete=True, files=self.files, max_detail_chars=self.max_detail_chars), indent=None)

    def put(self, suffix, chunks):
        temp = self.folder/(uuid.uuid4().hex+'.tmp')
        sha, length = hashlib.sha256(), 0
        try:
            with temp.open('wb') as stream:
                for chunk in chunks:
                    for offset in range(0, len(chunk), 65536):
                        block = chunk[offset:offset+65536].encode('utf-8')
                        sha.update(block); length += len(block); stream.write(block)
            name = sha.hexdigest()+'.'+suffix
            target = self.folder/name
            if target.exists():
                existing = hashlib.sha256()
                with target.open('rb') as stream:
                    for block in iter(lambda: stream.read(65536), b''):
                        existing.update(block)
                if existing.digest() == sha.digest():
                    temp.unlink()
                else:
                    from .common import replace_file
                    replace_file(temp, target)
            else:
                from .common import replace_file
                replace_file(temp, target)
            self.files[name] = dict(bytes=length, sha256=sha.hexdigest())
            return name
        finally:
            temp.unlink(missing_ok=True)

    def raw(self, value, title):
        encoder = json.JSONEncoder(ensure_ascii=False, separators=(',', ':'))
        name = self.put('json', encoder.iterencode(value))
        return ('<details class="raw-evidence"><summary>高级调试：'+html.escape(title)+'</summary>'
                '<p><a download href="html_details/'+name+'">下载完整 JSON 证据</a>（完整保留，按需读取）</p></details>')

    def search(self, text):
        ident = hashlib.sha256(text.encode('utf-8')).hexdigest()
        self.searches.setdefault(ident, text)
        return ident

    def detail(self, summary, contents, classes):
        if len(contents) < self.threshold:
            return None
        self.max_detail_chars = max(self.max_detail_chars, len(contents))
        # Sidecar documents share a folder; root-relative report links move up
        # one level. Hash-only links are resolved through the full anchor map.
        contents = re.sub(r'((?:href|src|data-ecra-src)=["\'])html_details/', r'\1', contents)
        contents = re.sub(r'(href=["\'])((?:index|opencode_review|classification_quality)\.html|facts\.json|inventory/|reports/|review/|git_diff/)',
                          r'\1../\2', contents)
        title = re.sub(r'<[^>]*>', '', summary)
        header = ('<!doctype html><html lang="zh-CN" data-ecra-root="../"><meta charset="utf-8">'
                  '<meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)
                  +'</title><link rel="stylesheet" href="'+self.style_name+'"><main><p><a target="_top" href="../index.html">返回完整报告</a>'
                  ' · 证据片段；完整性与有效性以首页为准。指纹：<code>'+html.escape(str(self.fingerprint))+'</code></p>')
        tail = '</main><script src="detail.js"></script></html>'
        name = self.put('html', [header, contents, tail])
        self.register('html_details/'+name, contents)
        url = 'html_details/'+name
        return ('<details class="'+html.escape(classes)+'" data-external-detail="1"><summary>'+summary+'</summary>'
                '<p><a target="_blank" href="'+url+'">独立打开全部证据</a></p>'
                '<template data-ecra-frame="1"><iframe loading="lazy" title="'+html.escape(title, quote=True)+'" data-ecra-src="'+url
                +'" style="width:100%;height:75vh;border:1px solid #d6e0eb"></iframe></template></details>')

    def register(self, name, contents):
        for ident in _IDS.findall(contents):
            self.anchors.setdefault(ident, name)

    def graph(self, graph, script):
        from .common import replace_file
        temp = self.folder/'graph-data.js.tmp'
        with temp.open('w', encoding='utf-8') as stream:
            stream.write('window.ECRA_CALL_GRAPH=')
            json.dump(graph, stream, ensure_ascii=True, separators=(',', ':'))
            stream.write(';')
        replace_file(temp, self.folder/'graph-data.js')
        (self.folder/'detail.js').write_text(DETAIL_SCRIPT+EXTERNAL_SCRIPT+script.replace(
            "JSON.parse(document.getElementById('call-graph').textContent)", 'window.ECRA_CALL_GRAPH'), encoding='utf-8')

    def finish(self):
        with (self.folder/'anchors.js').open('w', encoding='utf-8') as stream:
            stream.write('window.ECRA_EVIDENCE_ANCHORS=')
            json.dump(self.anchors, stream, ensure_ascii=True, separators=(',', ':'))
            stream.write(';')
        with (self.folder/'search-index.js').open('w', encoding='utf-8') as stream:
            stream.write('window.ECRA_SEARCH_INDEX=')
            json.dump(self.searches, stream, ensure_ascii=True, separators=(',', ':'))
            stream.write(';')
        for name in ('graph-data.js', 'anchors.js', 'detail.js', 'search-index.js'):
            path = self.folder/name
            sha = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(65536), b''):
                    sha.update(block)
            self.files[name] = dict(bytes=path.stat().st_size, sha256=sha.hexdigest())
