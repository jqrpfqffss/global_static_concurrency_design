"""Prepare explicit derived multicore inputs from archived config bytes.

No live firmware/config file is read by the archive selector. Complete static
graphs and ELF symbols are validated later in the owned, budgeted worker.
"""
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path
import uuid

from ..common import write_json
from ..config import read_yaml
from ..report_package import IDENTITY, OBJECT, sha256
from ..scan_store import EvidenceProvider, connect_readonly, _decode
from ..storage_activity import DataActivity
from ..workspace import no_links, formal_workspace

MAX_CONFIG = 4*1024**2


def _small_json(path, maximum=8*1024**2):
    path = no_links(path)
    if path.stat().st_size > maximum: raise ValueError('多核输入元数据超过读取预算')
    return json.loads(path.read_bytes())


def _scalar(provider, path):
    return provider.node(provider.resolve('provenance', path)).get('value')


def archived_config(scan):
    """Return exact, hash-verified config bytes; replacement text is not proof."""
    scan = no_links(scan); provider = EvidenceProvider(scan/'scan.db')
    try:
        file = _scalar(provider, ['display_identity','config_file'])
        expected = _scalar(provider, ['display_identity','config_sha256'])
        project = _scalar(provider, ['project_root'])
    except KeyError as exc:
        raise ValueError('所选归档没有完整配置来源；请选择可核对配置的原生扫描') from exc
    if (not isinstance(file,str) or not isinstance(expected,str) or not OBJECT.fullmatch('evidence/'+expected)
            or not isinstance(project,str) or not Path(project).is_absolute()):
        raise ValueError('所选归档配置或工程来源身份无效')
    with closing(connect_readonly(provider.path)) as conn:
        root = conn.execute("SELECT e.child FROM roots r JOIN edges e ON e.parent=r.node WHERE r.name='provenance' AND e.key='archived_sources'").fetchone()
        rows = [] if root is None else list(conn.execute(
            "SELECT e.child FROM edges e JOIN edges f ON f.parent=e.child AND f.key='file' "
            "JOIN nodes n ON n.id=f.child WHERE e.parent=? AND n.kind='str' AND n.value=?",
            (root[0], file.encode('utf-8', errors='surrogatepass'))))
        if len(rows)!=1: raise ValueError('归档配置原始字节缺失或来源有歧义')
        fields = {key:_decode(kind,value) for key,kind,value in conn.execute(
            "SELECT e.key,n.kind,n.value FROM edges e JOIN nodes n ON n.id=e.child WHERE e.parent=? "
            "AND e.key IN ('sha256','raw_object','codec','size')", (rows[0][0],))}
    if (fields.get('sha256')!=expected or type(fields.get('size')) is not int
            or not 0 <= fields['size'] <= MAX_CONFIG or fields.get('codec')!='gzip'
            or not isinstance(fields.get('raw_object'),str) or not OBJECT.fullmatch('evidence/'+fields['raw_object'])):
        raise ValueError('归档配置缺少受支持的完整原始字节或超过4MiB预算；不使用预览文本代替')
    blob = no_links(scan/'evidence'/fields['raw_object'])
    if blob.stat().st_size>MAX_CONFIG+1024**2:
        raise ValueError('归档配置压缩对象超过5MiB读取预算；请核对归档来源')
    if sha256(blob)!=fields['raw_object']: raise ValueError('归档配置压缩对象已损坏')
    with gzip.open(blob,'rb') as stream: raw = stream.read(MAX_CONFIG+1)
    if len(raw)!=fields['size'] or hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError('归档配置解压字节与已记录SHA不符')
    from ..scan_identity import query as display_identity
    identity=display_identity(provider)
    reference=provider.archived_source(file)
    return dict(raw=raw, sha256=expected, project_root=project, file=file, binding=provider.metadata(),
                display_name=identity.get('project_name') or '工程名称未记录',
                display_target=identity.get('configured_target'),display_variant=identity.get('build_variant'),
                text_node=reference.get('text_node') if reference.get('available') else None)


def elf_input(data, identity):
    if not isinstance(identity,str) or not IDENTITY.fullmatch(identity): raise ValueError('请选择已上传的ELF输入')
    folder = no_links(Path(data)/'work/multicore-elfs'/identity)
    record = _small_json(folder/'input.json',4096); path = no_links(folder/'firmware.elf')
    if (record.get('format')!='ECRA_MULTICORE_ELF_V1' or record.get('id')!=identity
            or type(record.get('bytes')) is not int or path.stat().st_size!=record['bytes']
            or not isinstance(record.get('sha256'),str) or not OBJECT.fullmatch('evidence/'+record['sha256'])):
        raise ValueError('上传的ELF身份或大小已变化，请重新选择文件')
    return path, record


def parse_regions(rows):
    if not isinstance(rows,list) or not rows: raise ValueError('请填写真实共享RAM起始地址和长度')
    result = []
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'start','size'}: raise ValueError('共享RAM字段无效')
        values=[]
        for key in ['start','size']:
            value=row[key]
            if not isinstance(value,str) or not value.strip(): raise ValueError('共享RAM地址和长度使用十进制或0x十六进制文本')
            try: values.append(int(value.strip(),0))
            except ValueError as exc: raise ValueError('共享RAM地址或长度不是有效整数：'+key) from exc
        if values[0]<0 or values[1]<=0: raise ValueError('共享RAM起始地址须非负、长度须大于0')
        if values[0]>=2**32 or values[1]>2**32-values[0]:
            raise ValueError('所选链接文件为ELF32，GUI共享RAM区域必须完整位于32位地址空间')
        result.append(values)
    return result


def prepare(data, rows, regions):
    data = no_links(data); regions = parse_regions(regions)
    if not isinstance(rows,list) or len(rows)<2: raise ValueError('请选择至少两个核心的已保存扫描和对应ELF')
    variants=set(); inputs=[]; configs=[]; project_id=root=None
    with DataActivity(data):
        for row in rows:
            if not isinstance(row,dict) or set(row)!={'variant','scan_id','elf_id'}: raise ValueError('多核输入字段无效')
            variant, ident = row['variant'], row['scan_id']
            if (not isinstance(variant,str) or not IDENTITY.fullmatch(variant) or variant in variants
                    or not isinstance(ident,str) or not IDENTITY.fullmatch(ident)):
                raise ValueError('核心别名须唯一且只含字母数字、下划线或短横线；请选择有效扫描')
            variants.add(variant); scan = no_links(data/'scans'/ident)
            manifest_path=scan/'manifest.json'; manifest = _small_json(manifest_path)
            config=archived_config(scan); binding=config['binding']
            expected=manifest.get('scan_sha256') or manifest.get('files',{}).get('scan.db',{}).get('sha256')
            if (binding['scan_id']!=ident or not expected or not OBJECT.fullmatch('evidence/'+str(expected))
                    or any(manifest.get(k)!=binding[k] for k in ['scan_id','project_id','facts_hash','report_hash'])):
                raise ValueError('所选扫描尚未完整发布或清单绑定不一致')
            if project_id is None: project_id=binding['project_id'];root=config['project_root']
            if binding['project_id']!=project_id or no_links(config['project_root'])!=no_links(root):
                raise ValueError('请选择同一工程身份和原始工程根的核心配置；不同工程合并尚未验证')
            elf, record=elf_input(data,row['elf_id'])
            configs.append(config['raw'])
            inputs.append(dict(variant=variant,scan_id=ident,profile_id=binding['profile_id'],
                config_sha256=config['sha256'],config_origin=config['file'],elf_id=row['elf_id'],elf=str(elf),
                name=config['display_name'],target=config['display_target'],build_variant=config['display_variant'],
                config_node=config['text_node'],elf_name=record.get('name','链接ELF'),elf_bytes=record['bytes'],
                expected=dict(binding=binding,manifest_sha256=sha256(manifest_path),scan_sha256=expected,
                              elf_sha256=record['sha256'])))
        workspace=formal_workspace(root,dict(output=dict(location='custom',custom_dir=str(data))))
        if workspace.project_id!=project_id: raise ValueError('当前原工程路径不能重建已归档工程身份；请核对工程归属')
        identity=uuid.uuid4().hex; folder=no_links(data/'work/multicore-plans'/identity);folder.mkdir(parents=True)
        for index,(item,raw) in enumerate(zip(inputs,configs)):
            path=folder/'inputs'/str(index)/'config.yaml';path.parent.mkdir(parents=True)
            with path.open('xb') as stream: stream.write(raw);stream.flush();os.fsync(stream.fileno())
            config=read_yaml(path)
            project=config.get('project',{}) if isinstance(config,dict) else None
            configured=project.get('root') if isinstance(project,dict) else None
            if not isinstance(configured,str) or not Path(configured).is_absolute() or no_links(configured)!=no_links(root):
                raise ValueError('归档配置必须明确绑定相同的绝对工程根，不能猜测相对路径')
            item.update(config=str(path),core=project.get('core','未明确记录'))
        plan=dict(format='ECRA_MULTICORE_PLAN_V1',id=identity,project_id=project_id,project_root=root,
                  inputs=inputs,regions=regions,stage='INPUT_SELECTION_FIXED',
                  note='已固定归档配置、扫描声明及上传ELF；完整静态库、链接符号和全部输入将在受控任务中核对。结果仍是链接地址派生合并，不是新的多核原生扫描。')
        write_json(folder/'plan.json',plan)
        return dict(plan, revision=sha256(folder/'plan.json'))


def start(data, identity, revision, tasks, resources=None):
    if not isinstance(identity,str) or not IDENTITY.fullmatch(identity): raise ValueError('请先检查多核输入')
    folder=no_links(Path(data)/'work/multicore-plans'/identity); path=folder/'plan.json'
    with DataActivity(data):
        plan=_small_json(path)
        if (sha256(path)!=revision or plan.get('format')!='ECRA_MULTICORE_PLAN_V1' or plan.get('id')!=identity):
            raise ValueError('多核检查计划已变化，请重新检查')
        # An exclusive claim prevents two windows from starting the same plan.
        claim=folder/'started.json'
        try:
            with claim.open('x',encoding='utf-8') as stream: json.dump(dict(state='STARTING'),stream)
        except FileExistsError as exc: raise ValueError('此检查计划已提交任务，请到扫描任务查看；再次合并须重新检查') from exc
        try:
            result=tasks.start(Path(plan['inputs'][0]['config']), profile_id='multicore-derived',
                               mode='multicore',resources=resources,multicore=plan)
        except BaseException:
            claim.unlink(missing_ok=True);raise
        write_json(claim,dict(state='STARTED',task_id=result['id']))
        return result
