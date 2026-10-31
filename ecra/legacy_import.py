"""Read-only, identity-bound legacy conversion, never a new scan validation.

Original files remain in place. Full facts/report are encoded directly into the
canonical graph; other bytes (including unknown historical files) are retained
as opaque CAS audit objects. No imported HTML, SQL or scripts are executed.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import uuid

from .workspace import WorkspaceResolver, no_links, canonical, studio_data_root
from .scan_store import EvidenceProvider, publish_json_scan
from .report_package import sha256, validate_objects
from .human_reviews import ReviewStore
from .storage_activity import DataActivity

REPORT = 'reports/global_static_concurrency.json'
REENCODED = {'facts.json', REPORT}


def small_json(path):
    path = no_links(path)
    if path.stat().st_size > 16*1024**2:
        raise ValueError('旧身份记录超过16MiB校验预算，原数据保留；请使用匹配版本检查来源')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('旧身份记录不是对象')
    return value


def paths(source):
    """Yield each regular file exactly once; fail on links or live databases."""
    for base, dirs, names in os.walk(source, followlinks=False):
        dirs.sort(); names.sort()
        for name in dirs+names:
            path = no_links(Path(base)/name)
            if name.endswith(('-wal', '-journal', '-shm')) or name in {'scan.lock', 'project.json.pending'}:
                raise ValueError('旧数据仍有锁/数据库恢复文件：'+str(path)+'；请在旧软件完成检查点并退出后重试')
            if name in names:
                if not stat.S_ISREG(path.stat().st_mode):
                    raise ValueError('旧数据包含非常规文件：'+str(path))
                yield path


def inspect(source, project_root, data_root):
    """Validate the explicitly selected archive against the existing resolver."""
    for value in (source, project_root):
        if not isinstance(value, (str, Path)) or not Path(value).is_absolute():
            raise ValueError('旧结果目录和原工程目录都必须是绝对路径')
    source, root, data = no_links(source), no_links(project_root), studio_data_root(data_root)
    if not source.is_dir():
        raise ValueError('旧结果目录不存在；请选择包含 run.json 和 scan_state.json 的目录')
    if source == data or source.is_relative_to(data) or data.is_relative_to(source):
        raise ValueError('旧来源与当前数据根重叠；拒绝递归导入自己的数据')
    if (source/'scan.db').exists():
        raise ValueError('此目录已经是新版权威格式，请从原Studio导出标准.ecra-report包后导入')
    run = small_json(source/'run.json'); state = small_json(source/'scan_state.json')
    if (canonical(run.get('project_root', '')) != canonical(root)
            or canonical(state.get('project_root', '')) != canonical(root)
            or state.get('schema') != 1 or not isinstance(state.get('fingerprint'), str) or not state['fingerprint']):
        raise ValueError('旧结果归属与所选原工程不一致；不根据目录名称猜测工程身份')
    workspace = WorkspaceResolver.resolve(root, dict(output=dict(location='custom', custom_dir=str(data))))
    # A resolver-owned tool workspace has an additional exact owner marker.
    marker = source.parent/'project.json' if source.name == 'results' else source/'project.json'
    kind = 'IDENTITY_BOUND_LEGACY_COPY'
    if marker.is_file():
        owner = small_json(marker)
        if (owner.get('schema_version') != 1 or owner.get('project_id') != workspace.project_id
                or canonical(owner.get('project_root', '')) != canonical(root)
                or canonical(owner.get('repository_root', '')) != canonical(workspace.repository_root)):
            raise ValueError('旧工具workspace归属校验失败；原数据保留')
        kind = 'TOOL_WORKSPACE'
    elif source == root/'.ecra':
        kind = 'FIRMWARE_LEGACY'
    if not (source/'facts.json').is_file():
        raise ValueError('缺少完整facts.json：旧facts.db不能无损恢复全部字段类型与顺序；未导入为有效结果，原数据保留')
    if not (source/REPORT).is_file():
        raise ValueError('缺少完整静态报告：请选择旧结果根目录；原数据保留')
    total, count = 0, 0
    for file in paths(source):
        count += 1; total += file.stat().st_size
    if marker.is_file() and marker.parent != source:
        count += 1; total += marker.stat().st_size
    return dict(source=str(source), project_root=str(root), project_id=workspace.project_id,
        repository_root=workspace.repository_root, source_kind=kind, files=count, logical_bytes=total,
        state='LEGACY_READ_ONLY', source_reverification=False,
        warning='只转换已归档的完整事实与报告，不重新证明当前源码。缺失的原始源码不会从当前工程冒充补齐。'
            '旧AI和人工文件逐字节保留；无法验证其合同的决定不会自动变成当前确认。原目录不会删除或改写。')


def _copy(source, target, expected):
    hashed = hashlib.sha256(); size = 0
    with source.open('rb') as reader, target.open('xb') as writer:
        for block in iter(lambda: reader.read(1024*1024), b''):
            writer.write(block); hashed.update(block); size += len(block)
            if size % (32*1024**2) == 0 and shutil.disk_usage(target.parent).free < 512*1024**2:
                raise OSError('迁移磁盘空间不足，已停止；原数据保留')
        writer.flush(); os.fsync(writer.fileno())
    if (size, hashed.hexdigest()) != expected or sha256(source) != expected[1]:
        raise ValueError('迁移期间旧输入已变化：'+str(source))


def _write_inventory(conn, destination, metadata):
    with destination.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(metadata, ensure_ascii=False)[:-1]+',"legacy_inputs":[')
        for index, row in enumerate(conn.execute('SELECT name,size,sha256,disposition FROM files ORDER BY name')):
            if index: stream.write(',')
            stream.write(json.dumps(dict(zip(('file','size','sha256','disposition'), row)), ensure_ascii=False))
        stream.write(']}')


def convert(source, project_root, data_root, *, progress=lambda _: None, _lease=None):
    """One atomic import; interrupted pending trees are retained for diagnosis."""
    data = studio_data_root(data_root)
    data.mkdir(parents=True, exist_ok=True)
    from contextlib import nullcontext
    if _lease is not None and (_lease.root != data or _lease.purpose != 'legacy-import'
            or not _lease.exclusive or _lease.stream is None or _lease.stream.closed):
        raise ValueError('迁移监督器未持有活动锁')
    with DataActivity(data), (nullcontext(_lease) if _lease is not None else
            DataActivity(data, exclusive=True, purpose='legacy-import')):
        plan = inspect(source, project_root, data)
        source = Path(plan['source']); ident = 'legacy-'+uuid.uuid4().hex
        work = no_links(data/'work/legacy'); work.mkdir(parents=True, exist_ok=True)
        stage = no_links(work/ident); stage.mkdir()
        record = stage/'migration.json'
        def receipt(state, **extra):
            from .common import write_json
            write_json(record, dict(plan, state=state, scan_id=ident, **extra))
        receipt('PREPARING'); progress(dict(stage='PREPARING', message='核对旧来源与完整文件清单', files=0, total=plan['files']))
        try:
            pending = stage/'archive'; pending.mkdir()
            evidence = pending/'evidence'; evidence.mkdir()
            copies = stage/'input'; copies.mkdir()
            with closing(sqlite3.connect(stage/'inventory.db')) as conn, conn:
                conn.execute('PRAGMA synchronous=FULL')
                conn.execute('CREATE TABLE files(name TEXT PRIMARY KEY,case_key TEXT UNIQUE,source TEXT,size INTEGER,sha256 TEXT,disposition TEXT)')
                items = ((p.relative_to(source).as_posix(), p) for p in paths(source))
                marker = source.parent/'project.json'
                from itertools import chain
                if source.name == 'results' and plan['source_kind'] == 'TOOL_WORKSPACE' and marker.is_file():
                    items = chain(items, [('owner/project.json', no_links(marker))])
                for number, (name, file) in enumerate(items, 1):
                    if ':' in name or '\\' in name or '..' in Path(name).parts:
                        raise ValueError('旧审计路径不安全，拒绝导入：'+name)
                    size, hashed = file.stat().st_size, sha256(file)
                    disposition = 'CANONICAL_REENCODED' if name in REENCODED else 'OPAQUE_AUDIT_PRESERVED'
                    conn.execute('INSERT INTO files VALUES (?,?,?,?,?,?)', (name, name.casefold(), str(file), size, hashed, disposition))
                    if name in {'facts.json', REPORT}:
                        target = copies/('facts.json' if name == 'facts.json' else 'report.json')
                    elif disposition == 'OPAQUE_AUDIT_PRESERVED':
                        target = evidence/hashed
                    else:
                        target = None
                    if target is not None:
                        if not target.exists():
                            if shutil.disk_usage(stage).free < size+512*1024**2:
                                raise OSError('迁移所需空间不足；原数据保留，请选择空间充足的独立数据盘')
                            _copy(file, target, (size, hashed))
                        elif target.stat().st_size != size or sha256(target) != hashed:
                            raise ValueError('旧审计对象SHA冲突/损坏')
                    progress(dict(stage='COPYING', message='逐文件捕获与校验：'+name, files=number, total=plan['files']))
                conn.commit()
                provenance = stage/'provenance.json'
                _write_inventory(conn, provenance, dict(legacy_migration_version=1,
                    project_root=plan['project_root'], source_directory=str(source), source_kind=plan['source_kind'],
                    source_reverification=False, legacy_warning=plan['warning'], archived_sources=[]))
                scan_id = 'legacy-'+sha256(provenance)[:48]
                def update(message): progress(dict(stage='CONVERTING', message=message))
                publish_json_scan(pending/'scan.db', copies/'facts.json', copies/'report.json',
                    scan_id=scan_id, project_id=plan['project_id'], profile_id='legacy-import',
                    provenance_path=provenance, progress=update)
                progress(dict(stage='VALIDATING', message='逐节点、全关系与业务投影校验，剩余量未知'))
                binding = EvidenceProvider(pending/'scan.db').validate(deep=True)
                ReviewStore(pending/'reviews.db', binding)
                # The familiar audit-index contract protects opaque old bytes
                # during package transfer and reference-aware garbage collection.
                index = stage/'audit-index.json'
                with index.open('x', encoding='utf-8') as stream:
                    stream.write('{"version":1,"files":{')
                    for ordinal, (name, size, hashed) in enumerate(conn.execute(
                            "SELECT name,size,sha256 FROM files WHERE disposition='OPAQUE_AUDIT_PRESERVED' ORDER BY name")):
                        if ordinal: stream.write(',')
                        stream.write(json.dumps(name, ensure_ascii=False)+':'+json.dumps(dict(size=size, sha256=hashed)))
                    stream.write('}}')
                index_hash = sha256(index); _copy(index, evidence/index_hash, (index.stat().st_size, index_hash))
                manifest = dict(format='ECRA_LEGACY_IMPORT', version=1, **binding,
                    mode='OFFLINE_ARCHIVE', source_reverification=False, audit_index=index_hash,
                    completed_at=datetime.now(timezone.utc).isoformat(), warning=plan['warning'])
                validate_objects(pending, manifest)
                # Re-list, hash and verify ownership again just before publication.
                current_count = 0
                for file in paths(source):
                    name = file.relative_to(source).as_posix(); current_count += 1
                    expected = conn.execute('SELECT size,sha256 FROM files WHERE name=?', (name,)).fetchone()
                    if expected is None or expected != (file.stat().st_size, sha256(file)):
                        raise ValueError('迁移校验期间旧目录已变化：'+name)
                for name, path, size, hashed in conn.execute("SELECT name,source,size,sha256 FROM files WHERE name='owner/project.json'"):
                    current_count += 1
                    if (Path(path).stat().st_size, sha256(path)) != (size, hashed):
                        raise ValueError('迁移期间旧workspace归属记录变化')
                if current_count != conn.execute('SELECT count(*) FROM files').fetchone()[0]:
                    raise ValueError('迁移期间旧目录文件数量变化')
                inspect(source, project_root, data)
                (pending/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
                scans = no_links(data/'scans'); scans.mkdir(exist_ok=True)
                destination = no_links(scans/scan_id)
                repeated = destination.exists()
                if repeated:
                    old = EvidenceProvider(destination/'scan.db').validate(deep=True)
                    root_hashes = lambda provider: {row['name']:row['hash'] for row in provider.roots()}
                    if old != binding or root_hashes(EvidenceProvider(destination/'scan.db')) != root_hashes(EvidenceProvider(pending/'scan.db')):
                        raise ValueError('同一旧导入身份对应不同证据；拒绝覆盖已有归档')
                    validate_objects(destination, small_json(destination/'manifest.json'))
                else:
                    pending.rename(destination)
            warnings = []
            try: receipt('COMPLETE', destination=str(destination))
            except OSError as exc: warnings.append('归档已发布；迁移诊断收据写入失败：'+str(exc))
            # Delete only private, verified conversion inputs, never old files.
            for name in ('facts.json', 'report.json'):
                try: (copies/name).unlink()
                except OSError as exc: warnings.append('私有转换输入暂未回收：'+str(exc))
            if repeated:
                try:
                    # Only this call's unpublished duplicate is disposable.
                    # Resolve and verify every path before recursive removal;
                    # links, replaced trees and original data are never targets.
                    if (no_links(stage).parent != no_links(data/'work/legacy')
                            or no_links(pending).parent != stage or pending.name != 'archive'):
                        raise ValueError('重复转换暂存路径已变化，保留现场')
                    for base, dirs, names in os.walk(pending,followlinks=False):
                        for name in dirs+names:
                            if not no_links(Path(base)/name).is_relative_to(pending):
                                raise ValueError('重复转换暂存出现越界路径')
                    shutil.rmtree(pending)
                except (ValueError,OSError) as exc: warnings.append('已验证的重复暂存暂未回收：'+str(exc))
            try: progress(dict(stage='COMPLETE', message='旧归档转换并发布完成；原目录保持不变', scan_id=ident))
            except Exception as exc: warnings.append('归档已发布；进度通知失败：'+str(exc))
            return dict(scan_id=scan_id, state='LEGACY_READ_ONLY', repeated=repeated, source_preserved=True,
                warning=plan['warning'], cleanup_warnings=warnings)
        except BaseException as exc:
            receipt('FAILED', error=str(exc)); raise
