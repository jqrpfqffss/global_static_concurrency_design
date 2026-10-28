"""为完整报告构建按需加载展示验证副本；不重新分析、不发布安全结论。"""
import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ecra.html_evidence import HtmlEvidence, _IDS, DETAIL_SCRIPT, EXTERNAL_SCRIPT
from ecra.html_report import STYLE


class Converter(HTMLParser):
    def __init__(self, stream, evidence, frame_script=None):
        super().__init__(convert_charrefs=False)
        self.stream,self.evidence=stream,evidence
        self.parts=None;self.depth=0;self.classes='';self.ids=set();self.moved=[]
        self.template_depth=0;self.frame_wrapped=False;self.inert_frames=0
        self.frame_script=frame_script;self.refreshed_scripts=0

    def emit(self,value):
        if self.parts is None:self.stream.write(value)
        else:self.parts.append(value)

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if self.parts is None and tag=='details' and attrs.get('data-deferred-detail')=='1':
            self.parts=[];self.depth=1;self.classes=attrs.get('class','evidence')
        elif self.parts is not None and tag=='details':self.depth+=1
        elif self.parts is None and attrs.get('id'):self.ids.add(attrs['id'])
        if self.parts is None:
            if tag=='template':self.template_depth+=1
            elif tag=='iframe' and 'data-ecra-src' in attrs and not self.template_depth:
                self.emit('<template data-ecra-frame="1">')
                self.frame_wrapped=True;self.inert_frames+=1
        self.emit(self.get_starttag_text())

    def handle_endtag(self,tag):
        self.emit('</'+tag+'>')
        if self.parts is None:
            if tag=='template':self.template_depth-=1
            elif tag=='iframe' and self.frame_wrapped:
                self.emit('</template>');self.frame_wrapped=False
        if self.parts is not None and tag=='details':
            self.depth-=1
            if self.depth==0:
                original=''.join(self.parts);self.parts=None
                match=re.fullmatch(r'<details\b[^>]*><summary>(.*?)</summary><template\b[^>]*>(.*)</template></details>',original,re.S)
                if not match:raise ValueError('原报告的折叠证据结构不完整，禁止丢弃内容')
                summary,contents=match.groups()
                stub=self.evidence.detail(summary,contents,self.classes)
                destination=re.search(r'data-ecra-src="([^"]+)"',stub)[1]
                for ident in _IDS.findall(contents):self.evidence.anchors[ident]=destination
                # The writer only relocates report-relative URLs. Check every
                # original character after that defined relocation.
                expected=re.sub(r'((?:href|src|data-ecra-src)=["\'])html_details/',r'\1',contents)
                expected=re.sub(r'(href=["\'])((?:index|opencode_review|classification_quality)\.html|facts\.json|inventory/|reports/|review/)',r'\1../\2',expected)
                stored=(self.evidence.out/destination).read_text(encoding='utf-8')
                if expected not in stored:raise ValueError('完整折叠证据未保留，禁止记录通过')
                self.moved.append(dict(destination=destination,characters=len(contents),
                    original_sha256=hashlib.sha256(contents.encode('utf-8')).hexdigest()))
                self.emit(stub)

    def handle_startendtag(self,tag,attrs):self.emit(self.get_starttag_text())
    def handle_data(self,data):
        if self.parts is None and self.frame_script and self.frame_script[0] in data:
            self.refreshed_scripts+=data.count(self.frame_script[0])
            data=data.replace(*self.frame_script)
        self.emit(data)
    def handle_entityref(self,name):self.emit('&'+name+';')
    def handle_charref(self,name):self.emit('&#'+name+';')
    def handle_comment(self,data):self.emit('<!--'+data+'-->')
    def handle_decl(self,decl):self.emit('<!'+decl+'>')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();source=args.source.resolve();out=args.output.resolve()
    if source.is_relative_to(out) or out.is_relative_to(source):parser.error('来源与输出目录不能重叠')
    out.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    for path in source.rglob('*'):
        relative=path.relative_to(source);target=out/relative
        if relative.as_posix()=='index.html':continue
        if path.is_dir():target.mkdir(exist_ok=True);continue
        target.parent.mkdir(parents=True,exist_ok=True)
        # Named navigation/manifest files are rewritten in this copy; never
        # hardlink those mutable files back to the verified original.
        immutable=bool(re.fullmatch(r'[a-f0-9]{64}\.(?:html|json|css)',path.name)) or \
            relative.as_posix() in {'facts.json','facts.db'} or relative.parts[0] in {'inventory','reports'}
        if immutable:
            try:os.link(path,target);continue
            except OSError:pass
        shutil.copy2(path,target)
    old=json.loads((source/'html_details/manifest.json').read_text(encoding='utf-8'))
    script=(source/'html_details/anchors.js').read_text(encoding='utf-8')
    anchors=json.loads(script.split('=',1)[1].strip().removesuffix(';'))
    script=(source/'html_details/search-index.js').read_text(encoding='utf-8')
    searches=json.loads(script.split('=',1)[1].strip().removesuffix(';'))
    with HtmlEvidence(out,old['fingerprint'],STYLE,threshold=0) as evidence:
        evidence.files.update(old['files']);evidence.anchors.update(anchors)
        evidence.searches.update(searches)
        evidence.max_detail_chars=old.get('max_detail_chars',0)
        # Keep the original complete navigation/graph program and refresh only
        # its frame lifecycle; named JS was copied independently above.
        original=(source/'html_details/detail.js').read_text(encoding='utf-8')
        marker='\nlet evidenceAnchorsPromise;'
        before,found,after=original.partition(marker)
        if not found or not before.startswith(DETAIL_SCRIPT):
            raise ValueError('原证据脚本版本不兼容，禁止覆盖完整交互脚本')
        current=DETAIL_SCRIPT+EXTERNAL_SCRIPT.partition(marker)[0]+found+after
        (out/'html_details/detail.js').write_text(current,encoding='utf-8')
        with (out/'index.html').open('w',encoding='utf-8') as stream:
            converter=Converter(stream,evidence,(before[len(DETAIL_SCRIPT):],EXTERNAL_SCRIPT.partition(marker)[0]))
            with (source/'index.html').open(encoding='utf-8') as original:
                for block in iter(lambda:original.read(1024*1024),''):converter.feed(block)
            converter.close()
            if converter.parts is not None:raise ValueError('报告末尾存在未闭合证据，禁止记录通过')
        for ident in converter.ids:evidence.anchors[ident]='index.html'
        evidence.finish()
    result=dict(complete=True,kind='SAVED_HTML_PRESENTATION_ONLY',native_acceptance=False,safety_report_valid=False,
        source=str(source),source_bytes=(source/'index.html').stat().st_size,
        index_bytes=(out/'index.html').stat().st_size,moved_count=len(converter.moved),
        legacy_frames_deferred=converter.inert_frames,
        frame_scripts_refreshed=converter.refreshed_scripts,
        moved=converter.moved,main_ids=len(converter.ids),seconds=time.monotonic()-started)
    (out/'presentation-proof.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'result_validity.json').write_text(json.dumps(dict(analysis_valid=False,state='PRESENTATION_TEST_ONLY'),ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='moved'},ensure_ascii=False))


if __name__=='__main__':main()
