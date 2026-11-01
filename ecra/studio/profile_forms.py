"""Conservative form edits over complete YAML, preserving advanced configuration.

PyYAML remains the engine's interpreter. Round-trip output is accepted only if
that interpreter sees exactly the requested changes. Ambiguous shared mappings
stay editable as YAML; the form never rewrites them by guessing.
"""
import copy
import datetime
import hashlib
import io
import os
from pathlib import Path
import tempfile

import yaml as engine_yaml
from ..config import UniqueKeyLoader

MAX_BYTES=4*1024**2
FIELDS={'project_name','project_root','build_mode','target','toolchain','variant','include_dirs','exclude_dirs','base_ref','current_ref','contexts','system_headers'}
CONTEXT_KINDS={'ISR','TASK','MAIN','CALLBACK','DMA','CORE','FOREGROUND','IRQ','EXTERNAL_ASYNC','UNKNOWN_CONTEXT'}


def _text(value,path,default=''):
    if value is None:return default
    if not isinstance(value,str) or '\n' in value or '\r' in value:raise ValueError(path+' 无法用单行文本表单表达，请使用高级YAML')
    return value


def _mapping(value,path):
    if not isinstance(value,dict):raise ValueError(path+' 必须是映射，请在高级YAML修复')
    return value


def _graph(value):
    active=set();seen=set();counts={}
    def visit(node):
        if isinstance(node,(dict,list)):
            identity=id(node);counts[identity]=counts.get(identity,0)+1
            if identity in active:raise ValueError('配置包含循环YAML别名，请在高级原文修复')
            if identity in seen:return
            seen.add(identity);active.add(identity)
            for item in (list(node.keys())+list(node.values()) if isinstance(node,dict) else node):visit(item)
            active.remove(identity)
        elif node is not None and not isinstance(node,(str,int,float,bool,bytes,datetime.date,datetime.datetime)):
            raise ValueError('配置含无法证明无损同步的类型 '+type(node).__name__+'；请保留高级YAML编辑')
    visit(value);return counts


def _plain(raw):
    if not isinstance(raw,str) or len(raw.encode('utf-8'))>MAX_BYTES:raise ValueError('完整配置必须是4MiB以内的UTF-8文本')
    try:value=engine_yaml.load(raw,Loader=UniqueKeyLoader)
    except engine_yaml.YAMLError as exc:raise ValueError('高级YAML格式错误：'+str(exc)) from exc
    _mapping(value,'配置根');_graph(value);return value


def _same(left,right,seen=None):
    if type(left) is not type(right):return False
    if isinstance(left,(dict,list)):
        if len(left)!=len(right):return False
        seen={'left':{},'right':{}} if seen is None else seen
        a,b=id(left),id(right)
        if a in seen['left']:return seen['left'][a]==b
        if b in seen['right']:return False
        seen['left'][a]=b;seen['right'][b]=a
        if isinstance(left,dict):
            return all(_same(a,b,seen) and _same(left[a],right[b],seen) for a,b in zip(left,right))
        return all(_same(a,b,seen) for a,b in zip(left,right))
    if isinstance(left,float):return left.hex()==right.hex()
    if isinstance(left,(datetime.date,datetime.datetime)):return left.isoformat()==right.isoformat()
    return left==right


def _roundtrip(raw):
    from ruamel.yaml import YAML
    parser=YAML(typ='rt',pure=True);parser.preserve_quotes=True;parser.width=4096
    parser.indent(mapping=2,sequence=4,offset=2)
    if '\r\n' in raw:parser.line_break='\r\n'
    try:return parser,parser.load(raw)
    except Exception as exc:raise ValueError('该YAML不能无损进入表单，请保留原文编辑：'+str(exc)) from exc


def _parents(document,path,*,create=False):
    from ruamel.yaml.comments import CommentedMap
    node=document;counts=_graph(document)
    for key in path[:-1]:
        if counts.get(id(node),0)>1 or getattr(node,'merge',None):raise ValueError('表单字段经过共享映射或合并键，请在高级YAML中修改；原文保留')
        if key not in node:
            if not create:return None
            node[key]=CommentedMap() if hasattr(document,'ca') else {}
        node=_mapping(node[key],'.'.join(path))
    if counts.get(id(node),0)>1 or getattr(node,'merge',None):raise ValueError('表单字段经过共享映射或合并键，请在高级YAML中修改；原文保留')
    return node


def _context_form(document):
    """Expose only rows whose identity and editable containers are unambiguous."""
    _parents(document,('contexts',))
    rows=document.get('contexts',[]);counts=_graph(document)
    if not isinstance(rows,list):raise ValueError('contexts 必须是入口映射列表，请使用高级YAML')
    if counts.get(id(rows),0)>1:raise ValueError('入口列表被其他高级字段共享，请保留高级YAML原文')
    identities=set();result=[]
    for row in rows:
        if not isinstance(row,dict) or counts.get(id(row),0)>1 or getattr(row,'merge',None):
            raise ValueError('入口含共享映射或合并键，请保留高级YAML原文')
        identity=row.get('id');kind=row.get('kind');functions=row.get('functions',[])
        if (not isinstance(identity,str) or not identity.strip() or '\n' in identity or '\r' in identity or
            identity in identities or not isinstance(kind,str) or kind not in CONTEXT_KINDS):
            raise ValueError('入口身份缺失/重复或类型无法表达，请在高级YAML修复')
        if (not isinstance(functions,list) or counts.get(id(functions),0)>1 or
            any(not isinstance(item,str) or not item or '\n' in item or '\r' in item for item in functions)):
            raise ValueError('入口函数含共享列表或无法逐行表达的值，请保留高级YAML原文')
        identities.add(identity);result.append(dict(origin_id=identity,id=identity,kind=kind,functions=list(functions)))
    return result


def _merge_contexts(document,expected,rows):
    from ruamel.yaml.comments import CommentedMap,CommentedSeq
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString as Quoted
    original=_context_form(document)
    if not isinstance(rows,list):raise ValueError('执行入口必须是列表')
    positions={row['id']:i for i,row in enumerate(original)};used=set();identities=set();last=-1;new_seen=False
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'origin_id','id','kind','functions'}:raise ValueError('执行入口表单字段无效')
        identity=row['id'];kind=row['kind'];functions=row['functions'];origin=row['origin_id']
        if not isinstance(identity,str) or not identity.strip() or '\n' in identity or '\r' in identity or identity in identities:raise ValueError('入口ID必须非空单行且不能重复')
        if not isinstance(kind,str) or kind not in CONTEXT_KINDS:raise ValueError('入口类型不受引擎支持')
        if not isinstance(functions,list) or any(not isinstance(item,str) or not item or '\n' in item or '\r' in item for item in functions):
            raise ValueError('入口函数必须为非空逐行字符串列表')
        identities.add(identity)
        if origin is None:new_seen=True;continue
        if not isinstance(origin,str) or origin not in positions or origin in used:raise ValueError('原入口身份不存在或重复，请重新读取原文')
        index=positions[origin]
        if index<=last or new_seen:raise ValueError('已有入口不支持重排；请在高级YAML显式修改')
        last=index;used.add(origin)
    # Edit the actual sequence in place: ruamel retains its sequence comments
    # and the untouched row maps, including their advanced aliases and styles.
    actual=document.setdefault('contexts',CommentedSeq());wanted=expected.setdefault('contexts',[])
    for index in reversed(range(len(original))):
        if original[index]['id'] not in used:del actual[index];del wanted[index]
    retained={row['id']:(actual[i],wanted[i]) for i,row in enumerate(row for row in original if row['id'] in used)}
    for row in rows:
        if row['origin_id'] is None:
            a=CommentedMap();e={};actual.append(a);wanted.append(e);previous={}
        else:
            a,e=retained[row['origin_id']];previous=original[positions[row['origin_id']]]
        for key in ('id','kind','functions'):
            value=row[key]
            if key in previous and value==previous[key]:continue
            if key=='functions':
                # Preserve comments on existing function items when possible.
                if key in a:
                    target=a[key]
                    for i,item in enumerate(value):
                        if i<len(target):target[i]=Quoted(item)
                        else:target.append(Quoted(item))
                    while len(target)>len(value):del target[-1]
                else:a[key]=CommentedSeq(Quoted(item) for item in value)
                e[key]=list(value)
            else:a[key]=Quoted(value);e[key]=value


def form_state(raw):
    value=_plain(raw);project=_mapping(value.get('project',{}),'project');analysis=_mapping(value.get('analysis',{}),'analysis')
    cmake=_mapping(analysis.get('cmake',{}),'analysis.cmake');git=_mapping(analysis.get('git_diff',{}),'analysis.git_diff')
    mode='cmake' if 'cmake' in analysis else 'database'
    def directories(name):
        result=analysis.get(name,[])
        if not isinstance(result,list) or any(not isinstance(item,str) or not item or '\n' in item or '\r' in item for item in result):raise ValueError(name+' 不能用逐行目录表单表达，请保留高级YAML')
        return result
    result=dict(project_name=_text(project.get('name'),'project.name'),project_root=_text(project.get('root'),'project.root'),
        build_mode=mode,target=_text(cmake.get('target') if mode=='cmake' else analysis.get('compile_database','auto'),'构建目标/数据库'),
        toolchain=_text(cmake.get('toolchain_file'),'Toolchain'),variant=_text(cmake.get('build_type','Debug'),'构建变体'),
        include_dirs=directories('include_dirs'),exclude_dirs=directories('exclude_dirs'),
        base_ref=_text(git.get('base_ref','HEAD^'),'base_ref') if git.get('enabled') else '',current_ref=_text(git.get('current_ref','HEAD'),'current_ref',default='HEAD'))
    headers=analysis.get('auto_system_includes')
    if 'auto_system_includes' in analysis and type(headers) is not bool:raise ValueError('analysis.auto_system_includes 必须是布尔值，请在高级YAML修复')
    result['system_headers']='default' if headers is None else 'on' if headers else 'off'
    _,document=_roundtrip(raw);reason='';context_reason=''
    try:result['contexts']=_context_form(document)
    except ValueError as exc:result['contexts']=[];context_reason=str(exc)
    for path in [('project','root'),('analysis','include_dirs'),('analysis','cmake','target'),('analysis','git_diff','base_ref')]:
        try:_parents(document,path)
        except ValueError as exc:reason=str(exc);break
    return dict(form=result,editable=not reason,reason=reason,contexts_editable=not context_reason,contexts_reason=context_reason,sha256=hashlib.sha256(raw.encode('utf-8')).hexdigest())


def merge_form(raw,changes):
    before=_plain(raw)
    if not isinstance(changes,dict) or set(changes)-FIELDS:raise ValueError('表单包含未知修改字段')
    for key,value in changes.items():
        if key=='contexts':continue
        if key in {'include_dirs','exclude_dirs'}:
            if not isinstance(value,list) or any(not isinstance(item,str) or not item or '\n' in item or '\r' in item for item in value):raise ValueError('目录必须是非空逐行文本数组')
        elif not isinstance(value,str):raise ValueError('表单字段 '+key+' 必须是文本')
    if not changes:return dict(yaml=raw,changed_paths=[])
    parser,document=_roundtrip(raw);expected=copy.deepcopy(before);operations=[]
    mode=changes.get('build_mode',form_state(raw)['form']['build_mode'])
    if mode not in {'cmake','database'}:raise ValueError('构建方式必须是CMake或编译数据库')
    def set_value(path,value):operations.append((path,value,False))
    def remove(path):operations.append((path,None,True))
    if 'build_mode' in changes:
        if mode=='database':remove(('analysis','cmake'));set_value(('analysis','compile_database'),changes.get('target') or 'compile_commands.json')
        else:
            remove(('analysis','compile_database'))
            if 'cmake' not in before.get('analysis',{}):
                for key,value in dict(generator='Ninja',build=True,build_type='Debug').items():set_value(('analysis','cmake',key),value)
    paths=dict(project_name=('project','name'),project_root=('project','root'),include_dirs=('analysis','include_dirs'),exclude_dirs=('analysis','exclude_dirs'))
    for key,path in paths.items():
        if key in changes:set_value(path,changes[key])
    if 'target' in changes:
        path=('analysis','cmake','target') if mode=='cmake' else ('analysis','compile_database')
        if mode=='cmake' and not changes['target']:remove(path)
        else:set_value(path,changes['target'] or 'compile_commands.json')
    for key,field in [('toolchain','toolchain_file'),('variant','build_type')]:
        if key in changes:
            if mode!='cmake':raise ValueError('编译数据库模式使用真实数据库参数，不改写CMake字段')
            if key=='toolchain' and not changes[key]:remove(('analysis','cmake',field))
            else:set_value(('analysis','cmake',field),changes[key])
    if 'base_ref' in changes:
        set_value(('analysis','git_diff','enabled'),bool(changes['base_ref']))
        if changes['base_ref']:set_value(('analysis','git_diff','base_ref'),changes['base_ref'])
    if 'current_ref' in changes:set_value(('analysis','git_diff','current_ref'),changes['current_ref'])
    if 'system_headers' in changes:
        if changes['system_headers'] not in {'default','on','off'}:raise ValueError('编译器标准头文件选项无效')
        if changes['system_headers']=='default':remove(('analysis','auto_system_includes'))
        else:set_value(('analysis','auto_system_includes'),changes['system_headers']=='on')
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString
    from ruamel.yaml.comments import CommentedSeq
    for path,value,deleted in operations:
        actual_parent=_parents(document,path,create=not deleted);expected_parent=_parents(expected,path,create=not deleted)
        if deleted:
            if actual_parent is not None:actual_parent.pop(path[-1],None)
            if expected_parent is not None:expected_parent.pop(path[-1],None)
        else:
            actual_parent[path[-1]]=DoubleQuotedScalarString(value) if isinstance(value,str) else CommentedSeq(DoubleQuotedScalarString(item) for item in value) if isinstance(value,list) else value
            expected_parent[path[-1]]=copy.deepcopy(value)
    if 'contexts' in changes:_merge_contexts(document,expected,changes['contexts'])
    stream=io.StringIO();parser.dump(document,stream);result=stream.getvalue();after=_plain(result)
    if not _same(expected,after):raise ValueError('同步会改变未选中的高级字段或类型；已拒绝，请继续编辑原文')
    return dict(yaml=result,changed_paths=['.'.join(path) for path,_,_ in operations]+(['contexts'] if 'contexts' in changes else []),build_mode_changed='build_mode' in changes)


def backup_original(settings,raw):
    """Immutable source text, separate from the editable profile and firmware."""
    from ..workspace import no_links
    content=raw.encode('utf-8')
    if len(content)>MAX_BYTES:raise ValueError('配置原文超过4MiB')
    identity=hashlib.sha256(content).hexdigest();root=no_links(Path(settings)/'profile-drafts');root.mkdir(parents=True,exist_ok=True)
    target=no_links(root/(identity+'.yaml'))
    with tempfile.NamedTemporaryFile(dir=root,suffix='.pending',delete=False) as stream:
        pending=Path(stream.name)
        try:stream.write(content);stream.flush();os.fsync(stream.fileno())
        except BaseException:stream.close();pending.unlink(missing_ok=True);raise
    try:
        try:os.link(pending,target)
        except FileExistsError:
            if target.read_bytes()!=content:raise ValueError('原文备份同摘要内容不一致；保留已有文件')
    finally:pending.unlink(missing_ok=True)
    return dict(id=identity,bytes=len(content))


def read_backup(settings,identity):
    import re
    from ..workspace import no_links
    if not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{64}',identity):raise ValueError('原文备份身份无效')
    path=no_links(Path(settings)/'profile-drafts'/(identity+'.yaml'))
    if not path.is_file() or path.stat().st_size>MAX_BYTES:raise ValueError('原文备份不存在或大小无效')
    content=path.read_bytes()
    if hashlib.sha256(content).hexdigest()!=identity:raise ValueError('原文备份摘要不一致；请保留现场')
    return content.decode('utf-8')
