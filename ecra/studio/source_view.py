"""Bounded archive line windows; live IDE links require original byte identity."""
import json
from pathlib import Path
from urllib.parse import quote

from ..report_package import sha256
from ..workspace import no_links


def source_window(provider,file,*,line=1,before=10,after=30):
    if line<1 or not 0<=before<=100 or not 0<=after<=100:
        raise ValueError('源码行窗口要求 line>=1，前后各不超过100行')
    ref=provider.archived_source(file)
    if not ref['available']:return ref
    start=max(1,line-before);end=line+after
    rows=[];number=1;column=1;offset=0;used=0;more=False
    # Long individual lines are segmented too. Never accumulate a full file or
    # an unbounded single line, and never imply a partial segment is complete.
    while True:
        page=provider.text(ref['text_node'],offset=offset,limit=16384)
        pieces=page['value'].split('\n')
        for index,part in enumerate(pieces):
            terminated=index<len(pieces)-1
            if number>end:more=True;break
            if start<=number and (part or terminated):
                if used+len(part)>262144 or len(rows)>=400:
                    more=True;break
                rows.append(dict(line=number,column=column,text=part,complete=terminated,selected=number==line))
                used+=len(part)
            column+=len(part)
            if terminated:number+=1;column=1
        if more or page['next_offset'] is None:break
        offset=page['next_offset']
    return dict(ref,requested_line=line,start_line=start,end_line=min(end,number),lines=rows,
                window_limited=more,next_line=(end+1 if number>end else number) if more else None,
                complete_file_available=True,ide=_ide(provider,file,line,ref.get('sha256')))


def _ide(provider,file,line,expected):
    unavailable=dict(available=False,reason='原源码不可用或未核对到完全相同的原始字节；继续使用归档证据。')
    if not expected:return unavailable
    out=provider.path.parent
    manifest=out/'manifest.json'
    if not manifest.is_file() or json.loads(manifest.read_text(encoding='utf-8')).get('format')!='ECRA_LOCAL_SCAN':
        return unavailable
    try:
        node=provider.node(provider.resolve('provenance',['project_root']))
        if not node.get('value'):return unavailable
        root=no_links(node['value']);relative=Path(file)
        if relative.is_absolute() or '..' in relative.parts:return unavailable
        target=no_links(root/relative)
        if not target.is_relative_to(root) or not target.is_file() or sha256(target)!=expected:return unavailable
        return dict(available=True,uri='vscode://file/'+quote(target.as_posix(),safe='/:')+':'+str(line)+':1',
                    reason='已核对此文件原始字节与扫描归档一致；点击由本机 VS Code 处理。')
    except (KeyError,ValueError,OSError):return unavailable
