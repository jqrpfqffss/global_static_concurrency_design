"""Plain-text forms over existing Markdown, with surgical case edits.

Unedited cases, provenance, comments and the original appendix retain their
exact bytes. The form never asks users to manufacture headings or code fences.
"""
import re

METADATA=('分类','来源类型','确认状态','来源','适用环境','关键共享对象','执行上下文','识别线索','检索关键词')
SECTIONS=('风险机制','典型代码模式','危险交错','隐蔽原因','OpenCode排查方法','常见错误判断','可证明安全的条件','适用性和边界')
STRUCTURAL=r'(?:#{1,6}\s|`{3,}|~{3,}|\*\*|(?:'+'|'.join(METADATA)+r')[：:])'


def lines_outside_code(text,*,with_balance=False):
    visible=re.sub(r'<!--.*?-->',lambda m:' '*(len(m[0])-m[0].count('\n')) if '\n' not in m[0] else
                   ''.join('\n' if c=='\n' else ' ' for c in m[0]),text,flags=re.S)
    if visible.startswith('\ufeff'):visible=' '+visible[1:]
    position=0;fence=None;result=[]
    for line,shown in zip(text.splitlines(keepends=True),visible.splitlines(keepends=True)):
        marker=re.match(r'^\s*(`{3,}|~{3,})',shown)
        if marker:
            token=marker[1]
            if fence is None:fence=token
            elif token[0]==fence[0] and len(token)>=len(fence):fence=None
        elif fence is None:result.append((position,line))
        position+=len(line)
    return (result,fence is None) if with_balance else result


def _plain(value):
    return re.sub(r'(?m)^\\(?=\s*'+STRUCTURAL+')','',value).strip()


def _encoded(value):
    # Text resembling a heading is still the engineer's text, not a new CASE
    # or section. Escape only structural Markdown, retaining newlines/code.
    return re.sub(r'(?m)^(?=\s*'+STRUCTURAL+')',r'\\',value.strip())


def _code(value):
    fence='`'*max(3,max((len(m[0])+1 for m in re.finditer(r'`{3,}',value)),default=3))
    return fence+'c\n'+value.strip()+'\n'+fence if value.strip() else ''


def _value(text,key):
    if key=='2':
        match=re.fullmatch(r'\s*(`{3,}|~{3,})[^\n]*\n(.*?)\n\1\s*',text,flags=re.S)
        if match:return match[2].strip()
    return _plain(text)


def library_forms(text):
    tokens=list(lines_outside_code(text));starts=[];appendix=len(text)
    for offset,line in tokens:
        match=re.match(r'^\ufeff?\s*#{1,6}\s+(CASE-[\w-]+)\s*[｜|:：]?\s*(.*?)\s*\r?\n?$',line,re.I)
        if match:starts.append((offset,match))
        if re.match(r'^\s*#{1,3}\s+后续追加模板\s*$',line.rstrip()):appendix=min(appendix,offset)
    cases=[];seen=set()
    for i,(start,heading) in enumerate(starts):
        end=starts[i+1][0] if i+1<len(starts) else len(text)
        end=min(end,appendix) if appendix>start else end
        for pos,line in tokens:
            if start<pos<end and re.match(r'^\s*#{1,2}\s',line):end=pos;break
        block=text[start:end];body_start=len(heading[0]);parts,balanced=lines_outside_code(block,with_balance=True)
        sections=[];metadata=[];all_metadata=[];headings=[]
        for pos,line in parts:
            if re.match(r'^\s*#{1,6}\s',line):headings.append(pos)
            match=re.match(r'^\s*###\s+([1-8])[.、．]\s*.*?(?:\r?\n|$)',line)
            if match:sections.append((pos,match[1],pos+len(line)))
            match=re.match(r'^\s*(?:\*\*)?([^*\n：:]+?)(?:\*\*)?[：:](?:\*\*)?[ \t]*(.*?)(?:\r?\n|$)',line)
            if match:
                all_metadata.append(pos)
                if match[1] in METADATA:metadata.append((pos,match[1],pos+match.start(2)))
        spans={};form=dict(title=heading[2],metadata={key:'' for key in METADATA},sections={str(n):'' for n in range(1,9)})
        first_section=next((pos for pos in headings if pos>0),len(block))
        metadata=[row for row in metadata if row[0]<first_section]
        for j,(pos,key,value_start) in enumerate(metadata):
            stop=min(next((p for p in all_metadata if p>pos),len(block)),first_section)
            value_end=stop-len(block[value_start:stop])+len(block[value_start:stop].rstrip())
            spans['m:'+key]=(value_start,value_end)
            form['metadata'][key]=_plain(block[value_start:value_end])
        for j,(pos,key,value_start) in enumerate(sections):
            stop=next((p for p in headings if p>pos),len(block))
            value_end=stop-len(block[value_start:stop])+len(block[value_start:stop].rstrip())
            spans['s:'+key]=(value_start,value_end);form['sections'][key]=_value(block[value_start:value_end],key)
        spans['title']=(heading.start(2),heading.end(2))
        ident=heading[1]
        duplicate=ident in seen;seen.add(ident)
        cases.append(dict(id=ident,form=form,start=start,end=end,spans=spans,body_start=body_start,
                          editable=balanced and not duplicate and len({x[1] for x in sections})==len(sections)
                          and len({x[1] for x in metadata})==len(metadata),raw=block))
    duplicate_ids={c['id'] for c in cases if sum(other['id']==c['id'] for other in cases)>1}
    for case in cases:
        if case['id'] in duplicate_ids:case['editable']=False
    return cases,appendix


def clean_form(value):
    if not isinstance(value,dict) or set(value)!={'title','metadata','sections'}:raise ValueError('请使用案例填写表单保存')
    if not isinstance(value['title'],str) or not value['title'].strip() or '\n' in value['title'] or '\r' in value['title']:raise ValueError('请填写一行案例名称')
    if len(value['title'])>300:raise ValueError('案例名称请控制在300字以内')
    for key,allowed in [('metadata',set(METADATA)),('sections',{str(n) for n in range(1,9)})]:
        if not isinstance(value[key],dict) or set(value[key])!=allowed or not all(isinstance(v,str) for v in value[key].values()):raise ValueError('案例填写字段不完整，请重新打开资料编辑器')
    if not value['sections']['1'].strip():raise ValueError('请填写问题描述')
    return dict(title=value['title'].strip(),metadata={k:v.strip() for k,v in value['metadata'].items()},sections={k:v.strip() for k,v in value['sections'].items()})


def update_library(text,case_id,value):
    value=clean_form(value);cases,appendix=library_forms(text)
    if case_id is None:
        value['metadata']['分类']=value['metadata']['分类'] or '用户补充（待分类）'
        value['metadata']['识别线索']=value['metadata']['识别线索'] or value['title']
        value['metadata']['来源类型']=value['metadata']['来源类型'] or '用户记录'
        value['metadata']['确认状态']=value['metadata']['确认状态'] or '待核实'
        used={c['id'].upper() for c in cases}
        number=max((int(ident[5:]) for ident in used if re.fullmatch(r'CASE-[0-9]+',ident)),default=0)+1
        while 'CASE-%04d'%number in used:number+=1
        ident='CASE-%04d'%number
        block='## '+ident+'｜'+value['title']+'\n\n'
        block+='\n'.join('**'+key+'：** '+_encoded(value['metadata'][key]) for key in METADATA)+'\n\n'
        block+='\n\n'.join('### '+str(n)+'. '+label+'\n\n'+(_code(value['sections'][str(n)]) if n==2 else _encoded(value['sections'][str(n)])) for n,label in enumerate(SECTIONS,1))+'\n\n'
        insertion=appendix if appendix<len(text) else len(text)
        return text[:insertion]+('' if not text[:insertion] or text[:insertion].endswith('\n\n') else '\n\n')+block+text[insertion:],ident
    matches=[c for c in cases if c['id']==case_id]
    if len(matches)!=1 or not matches[0]['editable']:raise ValueError('该案例编号重复或章节格式无法安全修改；原文保留，可先新增案例')
    case=matches[0];edits=[];missing_metadata=[];missing_sections=[]
    if value['title']!=case['form']['title']:edits.append((*case['spans']['title'],value['title']))
    for kind in ('metadata','sections'):
        for key,new in value[kind].items():
            if new==case['form'][kind][key]:continue
            token=('m:' if kind=='metadata' else 's:')+key
            encoded=_code(new) if kind=='sections' and key=='2' else _encoded(new)
            if token in case['spans']:edits.append((*case['spans'][token],encoded))
            elif kind=='metadata':missing_metadata.append('**'+key+'：** '+encoded+'\n')
            else:missing_sections.append('\n\n### '+key+'. '+SECTIONS[int(key)-1]+'\n\n'+encoded)
    if missing_metadata:edits.append((case['body_start'],case['body_start'],'\n'+''.join(missing_metadata)+'\n'))
    if missing_sections:edits.append((len(case['raw']),len(case['raw']),''.join(missing_sections)+'\n\n'))
    block=case['raw']
    for start,end,replacement in sorted(edits,reverse=True):block=block[:start]+replacement+block[end:]
    return text[:case['start']]+block+text[case['end']:],case_id


def context_text(raw):
    text=re.sub(r'<!--.*?-->','',raw,flags=re.S).strip()
    if text.startswith('# 当前工程背景\n'):text=text[len('# 当前工程背景\n'):].strip()
    return text


def context_markdown(text):
    if not isinstance(text,str):raise ValueError('工程背景请填写文字，可以留空')
    return '# 当前工程背景\n\n'+text.strip()+'\n' if text.strip() else ''
