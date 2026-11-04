"""Combine separate core scans only where linked ELF addresses overlap shared RAM."""
import argparse
import copy
import hashlib
import json
import struct
import uuid
from pathlib import Path

from .analysis import analyze, TABLES
from .common import read_json, write_json
from .config import load_config


def elf_objects(path):
    raw = Path(path).read_bytes()
    if raw[:7] != b'\x7fELF\x01\x01\x01' or struct.unpack_from('<H', raw, 18)[0] != 40:
        raise ValueError('Expected little-endian ELF32 ARM firmware: ' + str(path))
    section_offset = struct.unpack_from('<I', raw, 32)[0]
    entry_size, count = struct.unpack_from('<HH', raw, 46)
    sections = [struct.unpack_from('<10I', raw, section_offset + i*entry_size) for i in range(count)]
    symbols = []
    for section in sections:
        if section[1] != 2:
            continue
        strings = sections[section[6]]
        names = raw[strings[4]:strings[4]+strings[5]]
        owner = ''
        for offset in range(section[4], section[4]+section[5], section[9] or 16):
            name, address, size, info, _, shndx = struct.unpack_from('<IIIBBH', raw, offset)
            spelling = names[name:].split(b'\0', 1)[0].decode('utf-8', 'replace')
            if info & 15 == 4:
                owner = spelling
            if info & 15 == 1 and shndx and size:
                symbols.append(dict(name=spelling, address=address, size=size, binding=info >> 4, file=owner))
    return symbols


def _assemble(root, inputs, regions, elf_paths=None, *, _fixed_inputs=None):
    combined = {k: [] for k in TABLES}
    combined.update(pointer_model_applied=True, linked_objects=[])
    cfg = copy.deepcopy(_fixed_inputs[0][0]) if _fixed_inputs is not None else load_config(root, inputs[0][1])[0]
    cfg['contexts'], cfg['call_edges'] = [], []
    cfg['analysis']['auto_contexts'] = False
    objects = {}
    cross = {}
    units = []
    for index,(variant, config_path) in enumerate(inputs):
        source_cfg = _fixed_inputs[index][0] if _fixed_inputs is not None else load_config(root, config_path)[0]
        from .workflow import output_path
        folder = _fixed_inputs[index][1] if _fixed_inputs is not None else output_path(root, source_cfg)
        facts = read_json(folder / 'facts.json')
        elf = _fixed_inputs[index][2] if _fixed_inputs is not None else root / (elf_paths or {}).get(variant, source_cfg['project'].get('firmware_elf', ''))
        linked = elf_objects(elf)
        idmap = {}
        for var in facts['variables']:
            symbol = var['symbol_id']
            matches = [s for s in linked if s['name'] == var['name'] and
                       (s['binding'] != 0 or Path(s['file']).name == Path(var['definition_file'] or '').name)]
            location = matches[0] if len(matches) == 1 else None
            shared = location and any(start <= location['address'] and location['address']+location['size'] <= start+size for start, size in regions)
            sid = ('shared:' + hex(location['address']) + ':' + str(location['size'])) if shared else variant + '::' + symbol
            idmap[symbol] = sid
            obj = copy.deepcopy(var)
            obj.update(symbol_id=sid, accesses=[], core_instances=[dict(variant=variant, symbol_id=symbol)])
            if shared:
                obj['linked_address'] = location['address']
                combined['linked_objects'].append(dict(variant=variant, symbol_id=symbol, combined_symbol_id=sid,
                    elf=str(elf), elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(), **location))
                cross.setdefault(sid, set()).add(source_cfg['project']['core'])
            if sid in objects:
                objects[sid]['core_instances'].extend(obj['core_instances'])
            else:
                objects[sid] = obj
        fmap = {f['function_id']: variant + '::' + f['function_id'] for f in facts['functions']}
        for f in facts['functions']:
            combined['functions'].append(dict(f, function_id=fmap[f['function_id']]))
        for a in facts['accesses']:
            row = copy.deepcopy(a)
            row.update(symbol_id=idmap[a['symbol_id']], function_id=fmap.get(a['function_id'], ''),
                       access_id=variant + ':' + a['access_id'], core=source_cfg['project']['core'], variant=variant)
            combined['accesses'].append(row)
        for c in facts['calls']:
            combined['calls'].append(dict(c, caller_function_id=fmap.get(c['caller_function_id'], variant + '::' + c['caller_function_id']),
                callee_function_id=fmap.get(c['callee_function_id'], variant + '::' + (c['callee_function_id'] or ''))))
        for key in ('unknowns', 'protection_events', 'snapshots'):
            for item in facts[key]:
                row = copy.deepcopy(item)
                if row.get('symbol_id'):
                    row['symbol_id'] = idmap[row['symbol_id']]
                if row.get('function_id'):
                    row['function_id'] = fmap.get(row['function_id'], variant + '::' + row['function_id'])
                combined[key].append(row)
        for c in facts['contexts']:
            roots = [fmap[b['function_id']] for b in facts['context_bindings'] if b['context_id'] == c['id'] and b['call_depth'] == 0]
            cfg['contexts'].append(dict(c, id=variant + ':' + c['id'], functions=roots, core=source_cfg['project']['core']))
        units.extend(dict(u, variant=variant) for u in facts['translation_units'])
    combined['variables'] = list(objects.values())
    combined['translation_units'] = units
    coverage = dict(translation_units_failed=sum(u['parse_status'] == 'FAILED' for u in units),
                    translation_units_partial=sum(u['parse_status'] == 'PARTIAL' for u in units),
                    translation_units_total=len(units), unlisted_sources=[])
    coverage['translation_units_parsed'] = sum(u['parse_status'] == 'PARSED' for u in units)
    coverage['parse_coverage_percent'] = round(100*(coverage['translation_units_parsed'] + coverage['translation_units_partial'])/max(1,len(units)),2)
    report = analyze(combined, cfg, coverage)
    for finding in report['findings']:
        if len(cross.get(finding.get('symbol_id'), set())) > 1:
            finding['rules'] = sorted(set(finding['rules']) | {'GS-CROSS-CORE'})
            finding['linked_memory_evidence'] = [x for x in combined['linked_objects'] if x['combined_symbol_id'] == finding['symbol_id']]
    report.update(run_status='INCOMPLETE', review_summary=dict(total=len(report['findings']), unresolved=len(report['findings'])),
                  fingerprint=hashlib.sha256(json.dumps(combined['linked_objects'], sort_keys=True).encode()).hexdigest())
    return combined, report


def combine(root, inputs, regions, out=None, elf_paths=None, *, data_root=None, publication=None,
            scan_ids=None, profile_ids=None, expected_inputs=None, _budget_owned=False):
    """Publish a derived combination once, outside firmware, using Studio storage.

    The assembler and its conservative INCOMPLETE status are unchanged. This
    publication does not grant source re-verification or native multicore proof.
    """
    from contextlib import ExitStack
    from datetime import datetime, timezone
    import shutil
    from .workspace import formal_workspace, no_links
    from .workflow import output_path, clean_report
    from .report import prepare
    from .scan_store import EvidenceProvider, publish_scan
    from .human_reviews import ReviewStore
    from .scan_persistence import append_runtime, archive_audit
    from .report_package import IDENTITY, sha256, validate_objects
    from .storage_activity import DataActivity

    root=Path(root).resolve();inputs=list(inputs);regions=list(regions)
    if not inputs or len({variant for variant,_ in inputs})!=len(inputs):
        raise ValueError('多核合并需要非空、各不相同的variant输入')
    if any(not isinstance(variant,str) or not IDENTITY.fullmatch(variant) for variant,_ in inputs):
        raise ValueError('多核variant须为字母数字、下划线或短横线，最长128字符')
    variants={variant for variant,_ in inputs}
    if scan_ids is not None and (not isinstance(scan_ids,dict) or set(scan_ids)!=variants
            or any(not isinstance(value,str) or not IDENTITY.fullmatch(value) for value in scan_ids.values())):
        raise ValueError('显式多核输入必须为每个variant提供一个有效scan_id，不能回退到最新结果')
    if profile_ids is not None and (scan_ids is None or not isinstance(profile_ids,dict)
            or set(profile_ids)!=variants or any(not isinstance(value,str) or not IDENTITY.fullmatch(value)
                                               for value in profile_ids.values())):
        raise ValueError('多核profile身份必须与全部显式扫描输入一一对应')
    if expected_inputs is not None:
        if not isinstance(expected_inputs,dict) or scan_ids is None or set(expected_inputs)!=variants:
            raise ValueError('多核预检查指纹必须覆盖全部显式输入')
        for item in expected_inputs.values():
            if (not isinstance(item,dict) or set(item)!={'binding','manifest_sha256','scan_sha256','elf_sha256'}
                    or not isinstance(item['binding'],dict)
                    or any(not isinstance(item[k],str) or len(item[k])!=64 or set(item[k])-set('0123456789abcdef')
                           for k in ['manifest_sha256','scan_sha256','elf_sha256'])):
                raise ValueError('多核预检查指纹字段无效')
    if not regions or any(len(region)!=2 or any(type(v) is not int for v in region)
                          or region[0]<0 or region[1]<=0 for region in regions):
        raise ValueError('共享RAM区域须为非负起始地址和正整数长度')
    first_reads={};first,_=load_config(root,inputs[0][1],consumed_inputs=first_reads)
    # These settings govern only this derived output; input configs remain exact.
    policy={key:copy.deepcopy(first['analysis'][key]) for key in ('output','output_dir') if key in first['analysis']}
    if out is not None:
        if not Path(out).is_absolute():raise ValueError('多核输出不能位于固件内；使用独立数据根的绝对路径 scans/<scan_id>')
        out=no_links(out)
        if out.parent.name!='scans' or not IDENTITY.fullmatch(out.name):
            raise ValueError('多核输出须为独立数据根下的 scans/<scan_id> 新目录')
        if data_root is not None and no_links(data_root)!=out.parent.parent:
            raise ValueError('--output与--data-root必须属于同一个独立数据根')
        data_root=out.parent.parent
    if data_root is not None:
        if not Path(data_root).is_absolute():raise ValueError('多核数据根必须是独立绝对路径')
        policy=dict(output=dict(location='custom',custom_dir=str(data_root)))
    workspace=formal_workspace(root,policy)
    data=Path(workspace.workspace_root)
    out=no_links(out if out is not None else data/'scans'/uuid.uuid4().hex)
    if out.exists():raise FileExistsError('保留已有多核结果，请使用新的扫描目录: '+str(out))
    if out==root or out.is_relative_to(root) or root.is_relative_to(out):
        raise ValueError('多核输出不得与固件目录重叠')

    sources=[];components=[];fixed=[];implicit_folders=set()
    def record(path):
        path=Path(path).resolve();before=path.stat();hashed=sha256(path);after=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
            raise ValueError('多核输入在核对期间改变: '+str(path))
        item=dict(path=str(path),size=before.st_size,mtime_ns=before.st_mtime_ns,sha256=hashed)
        sources.append(item);return item

    with ExitStack() as activities:
        activities.enter_context(DataActivity(data))
        if not _budget_owned:
            activities.enter_context(DataActivity(data,exclusive=True,purpose='scan-budget'))
        for variant,config_path in inputs:
            from .config import resolve_config_path
            config_record=record(resolve_config_path(root,config_path))
            consumed={};cfg,config_file=load_config(root,config_path,consumed_inputs=consumed)
            if consumed[str(Path(config_file).resolve())]['sha256']!=config_record['sha256']:
                raise ValueError('多核配置实际读取字节与冻结摘要不符')
            if variant==inputs[0][0] and first_reads[str(Path(config_file).resolve())]['sha256']!=config_record['sha256']:
                raise ValueError('多核输出配置在启动期间改变')
            if scan_ids is None:
                folder=output_path(root,cfg)
                if folder.resolve() in implicit_folders:
                    raise ValueError('多个核心配置解析到同一latest结果；请用--scan为每个核心显式固定扫描身份')
                implicit_folders.add(folder.resolve())
            else:
                folder=no_links(data/'scans'/scan_ids[variant])
                manifest_path=folder/'manifest.json'
                if not manifest_path.is_file():
                    raise ValueError('所选多核输入不是已发布扫描：'+scan_ids[variant])
            if out==folder or out.is_relative_to(folder) or folder.is_relative_to(out):
                raise ValueError('多核输出不得与任一输入结果重叠')
            static=folder/'scan.db' if (folder/'scan.db').is_file() else folder/'facts.json'
            # Hold input roots against cleanup while their complete facts are used.
            if folder.parent.name=='scans' and folder.parent.parent!=data:
                activities.enter_context(DataActivity(folder.parent.parent))
            elf=root/(elf_paths or {}).get(variant,cfg['project'].get('firmware_elf',''))
            component=dict(variant=variant,core=cfg['project']['core'],config=config_record,
                           facts=record(static),elf=record(elf))
            if static.name=='scan.db':
                component['binding']=EvidenceProvider(static).validate(deep=True)
            if scan_ids is not None:
                binding=component.get('binding',{})
                if binding.get('scan_id')!=scan_ids[variant] or binding.get('project_id')!=workspace.project_id:
                    raise ValueError('所选多核扫描与配置工程身份不符：'+variant)
                if profile_ids is not None and binding.get('profile_id')!=profile_ids[variant]:
                    raise ValueError('所选多核扫描与配置profile身份不符：'+variant)
                manifest_record=record(manifest_path)
                manifest_bytes=manifest_path.read_bytes()
                if hashlib.sha256(manifest_bytes).hexdigest()!=manifest_record['sha256']:
                    raise ValueError('所选多核扫描清单读取期间改变：'+variant)
                manifest=json.loads(manifest_bytes)
                expected=manifest.get('scan_sha256') or manifest.get('files',{}).get('scan.db',{}).get('sha256')
                if (not expected or expected!=component['facts']['sha256'] or any(
                        manifest.get(key)!=binding.get(key) for key in ['scan_id','project_id','facts_hash','report_hash'])):
                    raise ValueError('所选多核扫描发布清单与完整静态库不一致：'+variant)
                provider=EvidenceProvider(static)
                try:
                    config_node=provider.resolve('provenance',['display_identity','config_sha256'])
                    archived_config=provider.node(config_node).get('value')
                except KeyError:
                    archived_config=None
                if archived_config!=config_record['sha256']:
                    raise ValueError('所选扫描的已归档配置与当前配置字节不符；请选择对应配置或重新扫描：'+variant)
                if expected_inputs is not None:
                    expected=expected_inputs[variant]
                    if (binding!=expected['binding'] or manifest_record['sha256']!=expected['manifest_sha256']
                            or component['facts']['sha256']!=expected['scan_sha256']
                            or component['elf']['sha256']!=expected['elf_sha256']):
                        raise ValueError('多核输入已在预检查后变化，请重新检查：'+variant)
                component.update(selection_mode='EXPLICIT_SCAN',manifest=manifest_record)
            components.append(component)
            fixed.append((cfg,folder,elf))
        # Original directories and pointers are never initialized or rebound here.
        try:
            facts,report=_assemble(root,inputs,regions,elf_paths,_fixed_inputs=fixed)
        except (struct.error,IndexError) as exc:
            raise ValueError('链接ELF或派生输入结构不完整；请核对真实链接文件与扫描归档。技术信息：'+str(exc)) from exc
        prepare(facts,report,[])
        for item in sources:
            path=Path(item['path']);stat=path.stat()
            if (stat.st_size,stat.st_mtime_ns)!=(item['size'],item['mtime_ns']) or sha256(path)!=item['sha256']:
                raise ValueError('多核输入在合并期间改变；拒绝发布: '+str(path))
        out.mkdir(parents=True,exist_ok=False)
        profile='multicore-'+hashlib.sha256(json.dumps(dict(variants=[v for v,_ in inputs],regions=regions),
            separators=(',',':')).encode()).hexdigest()[:24]
        write_json(out/'storage.json',dict(version=1,scan_id=out.name,project_id=workspace.project_id,profile_id=profile,
                                         derivation='LINKED_MULTICORE_COMBINATION'))
        try:
            for index,component in enumerate(components):
                folder=out/'diagnostics'/'multicore-inputs'/str(index);folder.mkdir(parents=True)
                for field,name in [('config','config.yaml'),('elf','firmware.elf')]:
                    target=folder/name;shutil.copyfile(component[field]['path'],target)
                    if sha256(target)!=component[field]['sha256']:raise ValueError('多核配置/ELF在归档期间改变')
            note='链接地址派生合并；未重新执行多核原生扫描。未归档可核对的原源码；可查看合并证据并继续人工确认，不能重新进行源码复核。'
            provenance=dict(storage_version=1,project_root=str(root),derivation='LINKED_MULTICORE_COMBINATION',
                            components=components,shared_regions=regions,source_reverification=False,
                            evidence_notice=note,archived_sources=[],
                            display_identity=dict(version=1,project_name=first['project'].get('name') or root.name,
                                project_core=' / '.join(component['core'] for component in components)))
            publish_scan(out/'scan.db',facts,clean_report(report),scan_id=out.name,project_id=workspace.project_id,
                         profile_id=profile,provenance=provenance)
            binding=EvidenceProvider(out/'scan.db').validate(deep=True)
            ReviewStore(out/'reviews.db',binding);append_runtime(out,report,[])
            audit=archive_audit(out);validate_objects(out,audit)
            # Verify again after publication work, before making the result visible.
            for item in sources:
                if sha256(Path(item['path']))!=item['sha256']:raise ValueError('多核输入在发布期间改变')
            write_json(out/'manifest.json',dict(binding,format='ECRA_LOCAL_SCAN',version=1,**audit,
                state='STATIC_VALIDATED',run_state='INCOMPLETE',scan_sha256=sha256(out/'scan.db'),
                source_reverification=False,derivation='LINKED_MULTICORE_COMBINATION',
                completed_at=datetime.now(timezone.utc).isoformat()))
            if publication is not None:publication.update(scan_id=out.name,data_root=str(data),scan_path=str(out))
        except BaseException:
            write_json(out/'result_validity.json',dict(analysis_valid=False,state='FAILED_DERIVED_PUBLICATION'))
            raise
    return facts,report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--input', action='append', required=True, help='variant=config/path.yaml')
    p.add_argument('--shared-region', action='append', required=True, help='start:size, integers including 0x prefix')
    p.add_argument('--elf', action='append', default=[], help='variant=firmware.elf')
    p.add_argument('--scan',action='append',default=[],help='variant=scan_id；为全部核心固定本数据根中的已发布扫描')
    p.add_argument('--profile-id',action='append',default=[],help='variant=profile_id；核对显式扫描的配置身份')
    p.add_argument('--output',type=Path,help='独立数据根下全新的绝对路径 scans/<scan_id>；不允许固件内目录')
    p.add_argument('--data-root',type=Path,help='独立数据根；默认复用项目的WorkspaceResolver设置')
    a = p.parse_args()
    def pairs(values,field):
        result={}
        for value in values:
            if '=' not in value:p.error(field+' 需要 variant=value')
            variant,item=value.split('=',1)
            if not variant or not item or variant in result:p.error(field+' 的variant/value不能为空或重复')
            result[variant]=item
        return result
    root = a.project.resolve()
    publication={}
    facts, report = combine(root, [x.split('=', 1) for x in a.input], [tuple(int(v, 0) for v in x.split(':')) for x in a.shared_region], a.output,
                            pairs(a.elf,'--elf'),data_root=a.data_root,publication=publication,
                            scan_ids=pairs(a.scan,'--scan') if a.scan else None,
                            profile_ids=pairs(a.profile_id,'--profile-id') if a.profile_id else None)
    print(json.dumps(dict(variables=len(facts['variables']), cross_core_findings=sum('GS-CROSS-CORE' in f['rules'] for f in report['findings']),**publication)))


if __name__ == '__main__':
    main()
