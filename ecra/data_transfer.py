"""Verified, resumable copies from read-only legacy sources into workspace."""
from contextlib import closing, contextmanager, ExitStack
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import re
from pathlib import Path
from pathlib import PurePosixPath
import shutil
import sqlite3
import time
import uuid

from .common import write_json
from .diff_review import DiffReviewEvidence
from .storage_activity import DataActivity
from .workspace import control_path, managed_root, no_links, studio_data_root


_INFRASTRUCTURE = {'.ecra', 'a', 'data-roots'}


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True).encode()).hexdigest()


def registry(source):
    return control_path('transfers', _digest(os.path.normcase(str(no_links(source)))))


def _walk(root, *, onerror):
    for base, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
        if Path(base) == root and root == managed_root():
            dirs[:] = [name for name in dirs if name not in _INFRASTRUCTURE]
        yield Path(base), dirs, names


def _files(root):
    result={}
    def fail(error):raise error
    for base,dirs,names in _walk(root,onerror=fail):
        dirs.sort();names.sort()
        for name in dirs+names:no_links(Path(base)/name)
        for name in names:
            path=Path(base)/name
            if path.parent==root/'settings' and name.endswith('-activity.lock'):
                continue  # live OS mutexes are recreated, never user evidence
            if not path.is_file():raise ValueError('数据根包含非普通文件：'+str(path))
            stat=path.stat()
            result[path.relative_to(root).as_posix()]=dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns)
    return result


def _directories(root):
    def fail(error):raise error
    return sorted(no_links(Path(base)/name).relative_to(root).as_posix()
        for base,dirs,_ in _walk(root,onerror=fail) for name in dirs)


def _hash(path):
    hashed=hashlib.sha256()
    with no_links(path).open('rb') as stream:
        for part in iter(lambda:stream.read(1024**2),b''):hashed.update(part)
    return hashed.hexdigest()


def _target(source,destination):
    from .studio_preferences import _target as check
    target=check(destination,source)
    path = studio_data_root(target['path'])
    if (path == managed_root() or path == source or source.is_relative_to(path)
            or (path.is_relative_to(source) and source != managed_root()) or target['kind'] != 'EMPTY'):
        raise ValueError(f'请在 {managed_root() / "data-roots"} 选择新的空目录；不会覆盖已有数据: {path}')
    return path


def _source(value):
    if not isinstance(value, (str, Path)) or not Path(value).is_absolute():
        raise ValueError('旧 Studio 来源必须是绝对路径')
    source=no_links(value)
    if source.name.casefold() == 'ecrastudio' and (source/'data').is_dir():
        source=no_links(source/'data')
    if not source.is_dir() or source==Path(source.anchor):
        raise ValueError(f'没有找到旧 Studio 数据目录: {source}')
    device=no_links(source/'settings/device.json')
    if device.exists():
        if not device.is_file() or device.stat().st_size>4096:
            raise ValueError(f'来源 Studio 设备声明无效: {device}')
        record=json.loads(device.read_text('utf-8'))
        if not isinstance(record,dict) or not isinstance(record.get('device'),str) or not record['device'].startswith('device-'):
            raise ValueError(f'来源 Studio 设备声明无效: {device}')
    elif not any((source/'scans').glob('*/scan.db')) and not any((source/'projects').glob('*/project.json')):
        raise ValueError(f'旧数据没有 Studio 设备、扫描或工程归属，请核对旧目录: {source}')
    return source


@contextmanager
def _stable_source(source, *, closed=False):
    """Hold existing activity locks read-only and detect writers during import."""
    tool = managed_root()
    if not source.is_relative_to(tool) and closed is not True:
        raise ValueError(f'请先关闭旧 ECRA Studio 和扫描、复核等写入进程，再确认来源已停止写入: {source}')
    with ExitStack() as locks:
        if os.name == 'nt' and source != tool:
            from .guarded_cmake import InputWatch
            watch = locks.enter_context(InputWatch())
            for path in sorted((source/'settings').glob('*-activity.lock')):
                try:
                    watch.file(path)
                except OSError as exc:
                    raise ValueError(f'旧 ECRA 正在使用活动锁，请关闭后重试: {path}') from exc
            yield
        else:
            # The default root's transfer controls live in its excluded .ecra.
            for path in sorted((source/'settings').glob('*-activity.lock')):
                locks.enter_context(DataActivity(source, exclusive=True,
                    purpose=path.name.removesuffix('-activity.lock'), read_only=True))
            yield


def _safe_name(name):
    if (not isinstance(name,str) or not name or '\\' in name or ':' in name
            or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
            or PurePosixPath(name).as_posix()!=name):raise ValueError('搬迁记录包含越界路径')
    return name


def retired_roots(data):
    """Execution may not silently keep depending on a previous data location."""
    data=no_links(data);roots=set()
    state = no_links(data/'settings/storage-location.json')
    if state.is_file():
        record = json.loads(state.read_text('utf-8'))
        for name in [record['current'], *record['previous']]:
            old = Path(name)
            if not old.is_absolute():
                raise ValueError(f'数据位置记录无效: {state}')
            if old != data:
                roots.add(old)
    for path in (data/'settings/root-transfers').glob('*.json'):
        record=json.loads(no_links(path).read_text('utf-8'))
        if record.get('format')!='ECRA_VERIFIED_ROOT_COPY_V1':raise ValueError('数据根复制来源记录版本无效')
        for name in ('source','target'):
            value=record.get(name)
            if not isinstance(value,str) or not Path(value).is_absolute():raise ValueError('数据根复制来源路径无效')
            old=Path(value)
            if old!=data:roots.add(old)
        for value in record.get('source_aliases',[]):
            if not isinstance(value,str) or not Path(value).is_absolute():raise ValueError('旧数据根别名无效')
            old=Path(value)
            if old!=data:roots.add(old)
    return sorted(roots)


def register_location(data):
    """Remember moves without rewriting the paths in immutable receipts."""
    data = studio_data_root(data)
    file = no_links(data/'settings/storage-location.json')
    if file.is_file() and json.loads(file.read_text('utf-8')).get('current') == str(data):
        return
    with DataActivity(data, exclusive=True, purpose='root-transfer', wait=10):
        record = json.loads(file.read_text('utf-8')) if file.is_file() else dict(previous=[])
        previous = record['previous']
        old = record.get('current')
        if old and Path(old) != data and old not in previous:
            previous.append(old)
        if old != str(data):
            write_json(file, dict(version=1, current=str(data), previous=previous))


def reject_retired_inputs(data,values):
    roots=retired_roots(data)
    if not roots:return
    variants=[]
    if os.name=='nt':
        for path in (no_links(data)/'settings/root-transfers').glob('*.json'):
            record=json.loads(no_links(path).read_text('utf-8'))
            if no_links(record['source'])==no_links(data):continue
            spellings=[Path(p).parts for p in [record['source'],*record.get('source_aliases',[])]]
            depth=len(spellings[0])
            variants.append([set(parts[i].casefold() for parts in spellings if len(parts)==depth) for i in range(depth)])
    def strings(value):
        if isinstance(value,str):yield value
        elif isinstance(value,dict):
            for key,item in value.items():
                if key!='_workspace':yield from strings(item)
        elif isinstance(value,(list,tuple)):
            for item in value:yield from strings(item)
    for value in strings(values):
        candidates=[value]
        # Compiler arguments include -I/path and -DNAME=C:/path. Resolve each
        # absolute spelling too: Windows temp paths often use ADMINI~1.
        for match in re.finditer(r'[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+',value):
            candidates.append(value[match.start():])
            try:candidates.append(str(Path(value[match.start():]).resolve()))
            except (OSError,ValueError):pass
        alias_match=False
        for candidate in candidates:
            parts=Path(candidate).parts
            if any(len(parts)>=len(binding) and all(parts[i].casefold() in names for i,names in enumerate(binding))
                    for binding in variants):alias_match=True
        for root in roots:
            old=str(root).replace('\\','/')
            if os.name=='nt':old=old.casefold()
            normalized=[s.replace('\\','/').casefold() if os.name=='nt' else s for s in candidates]
            nested = str(no_links(data)).replace('\\','/')
            if os.name=='nt':nested=nested.casefold()
            retained = normalized if not no_links(data).is_relative_to(root) else [
                s for s in normalized if s != nested and nested.rstrip('/')+'/' not in s]
            if (alias_match and retained) or any(s==old or old.rstrip('/')+'/' in s for s in retained):
                raise ValueError('搬迁后的构建/编译输入仍引用旧数据目录：'+str(root)+
                    '；请在工程接入中重新检查构建或选择重新导出的编译数据库，不能依赖旧盘符继续扫描。')


def _aliases(path):
    aliases={str(path)}
    if os.name=='nt':
        import ctypes
        function=ctypes.WinDLL('kernel32',use_last_error=True).GetShortPathNameW
        function.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint32];function.restype=ctypes.c_uint32
        size=function(str(path),None,0)
        if size:
            buffer=ctypes.create_unicode_buffer(size)
            if function(str(path),buffer,size):aliases.add(buffer.value)
    return sorted(aliases)


def relocated_task_config(data,path,raw):
    """A derived execution config; never edit the original task snapshot."""
    data=no_links(data);path=no_links(path)
    task = path.parent.parent == data/'work/tasks' and path.name == 'semantics.yaml'
    profile = path.parent.name == 'profiles' and path.parent.parent.parent == data/'projects'
    if not task and not profile:return raw,None
    from .studio.profile_forms import _roundtrip,_plain,_same
    parser,document=_roundtrip(raw.decode('utf-8'));old=_plain(raw.decode('utf-8'))
    output=old.get('analysis',{}).get('output',{})
    if output.get('location')!='custom' or Path(output['custom_dir']) not in retired_roots(data):return raw,None
    original=hashlib.sha256(raw).hexdigest()
    if task:
        meta=json.loads((path.parent/'task.json').read_text('utf-8'))
        if meta.get('profile_revision')!=original:raise ValueError('搬迁后的原任务配置已变化，不能恢复；请从工程配置重新扫描')
    document['analysis']['output']={'location':'user'}
    expected=json.loads(json.dumps(old));expected['analysis']['output']={'location':'user'}
    stream=io.StringIO();parser.dump(document,stream);result=stream.getvalue()
    if not _same(_plain(result),expected):raise ValueError('原任务的活动输出路径不能无损重绑；原配置保留')
    return result.encode('utf-8'),dict(source_config=str(path),source_sha256=original,
        old_output=output['custom_dir'],new_data_root=str(data),mode='REVALIDATE_INPUTS_AND_REUSE_ONLY_VALID_TU_CACHE')


def preview(source,destination,*,closed=False):
    source=_source(source)
    target=_target(source,destination)
    with _stable_source(source,closed=closed):
        files=_files(source);directories=_directories(source)
    total=sum(r['size'] for r in files.values())
    return dict(source=str(source),target=str(target),files=len(files),bytes=total,
        revision=_digest(dict(source=str(source),target=str(target),files=files,directories=directories)),
        retention='全部原数据保留；复制、校验及路径重绑成功后才发布新目录。',
        activation='完成后在设置中保存新数据目录，再重新启动 ECRA。')


def _validate_copy(stage):
    """Validate SQLite including committed WAL, without opening source writers."""
    from .scan_store import EvidenceProvider
    from .human_reviews import ReviewStore
    from .report_package import _review_events,copy_prior_decisions,copy_ai_receipts,validate_objects
    import tempfile
    for path in sorted(p for p in stage.rglob('*') if p.suffix.lower() in {'.db','.sqlite','.sqlite3'}):
        with path.open('rb') as stream:header=stream.read(16)
        if header!=b'SQLite format 3\0':
            if path.name in {'scan.db','reviews.db'}:raise ValueError('扫描/人工数据库文件头损坏：'+str(path))
            continue  # unknown opaque bytes are preserved, never interpreted
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=rw',uri=True)) as conn:
            conn.execute('PRAGMA trusted_schema=OFF')
            if conn.execute('PRAGMA integrity_check').fetchone()!=('ok',):
                raise ValueError('搬迁副本SQLite完整性失败：'+str(path))
    for path in sorted((stage/'scans').glob('*/scan.db')):
        if (path.parent/'storage.json').is_file() and not (path.parent/'manifest.json').is_file():
            continue  # interrupted unpublished work is retained, never blessed as a valid scan
        provider=EvidenceProvider(path);binding=provider.validate(deep=True)
        manifest=path.parent/'manifest.json'
        if manifest.is_file():
            record=json.loads(manifest.read_text('utf-8'))
            if any(record.get(key)!=binding[key] for key in ('scan_id','project_id','facts_hash','report_hash')):
                raise ValueError('搬迁来源已发布扫描的身份与完整事实不一致')
            validate_objects(path.parent,record)
        for obj in (path.parent/'evidence').glob('*'):
            if not obj.is_file() or _hash(obj)!=obj.name:raise ValueError('搬迁来源的归档证据对象损坏')
        events=_review_events(path.parent/'reviews.db',binding)
        with tempfile.TemporaryDirectory(prefix='review-check-',dir=stage) as folder:
            check=Path(folder)/'reviews.db';store=ReviewStore(check,binding)
            copy_prior_decisions(path.parent/'reviews.db',check,provider)
            copy_ai_receipts(path.parent/'reviews.db',check)
            store.merge(events,fingerprint_for=DiffReviewEvidence(path.parent, provider).fingerprint)


def _rebind(stage,source,target):
    """Only editable profiles change; immutable scans/receipts stay original."""
    from .studio.profile_forms import _roundtrip,_plain,_same
    changed=[];retained=[]
    for path in sorted((stage/'projects').glob('*/profiles/*.yaml')):
        original=path.read_text('utf-8')
        parser,document=_roundtrip(original)
        before=_plain(original)
        if not isinstance(document,dict) or not isinstance(document.get('analysis'),dict):
            raise ValueError('活动配置缺少analysis，原文保留：'+str(path))
        analysis=document['analysis'];expected=json.loads(json.dumps(before))
        output=analysis.get('output',{})
        if output.get('location','user')=='custom' and no_links(output['custom_dir'])==source:
            analysis['output']={'location':'user'};expected['analysis']['output']={'location':'user'}
        # Explicit configuration paths inside the copied root can be rebound.
        # Compiler arguments, provenance and unknown fields are never guessed.
        for name in ('compile_database','libclang_file'):
            raw=analysis.get(name)
            if isinstance(raw,str) and Path(raw).is_absolute() and no_links(raw).is_relative_to(source):
                value=str(target/no_links(raw).relative_to(source));analysis[name]=value;expected['analysis'][name]=value
        if not _same(_plain(original),expected):
            stream=io.StringIO();parser.dump(document,stream);updated=stream.getvalue()
            if not _same(_plain(updated),expected):raise ValueError('配置无损重绑校验失败，保留原件')
            backup=stage/'settings/transfer-original-profiles'/path.relative_to(stage)
            backup.parent.mkdir(parents=True,exist_ok=True)
            if backup.exists() and backup.read_bytes()!=path.read_bytes():
                backup=backup.with_name(backup.name+'.'+_hash(path))
            if not backup.exists():shutil.copyfile(path,backup)
            path.write_text(updated,encoding='utf-8',newline='')
            changed.append(path.relative_to(stage).as_posix())
    # Runtime caches keep their original bytes. The resolver keys new caches by
    # the current data location and never reuses the previous namespaces.
    for project in sorted((stage/'projects').glob('*')):
        for suffix in ('builds','trees','git-snapshots','results/git_diff'):
            old=project/suffix
            if old.exists():
                retained.append(dict(original=old.relative_to(stage).as_posix(), reusable=False))
    return changed,retained


def transfer(source,destination,*,expected=None,resume=None,closed=False,progress=lambda value:None):
    source=_source(source);target=studio_data_root(destination)
    control=registry(source);control.mkdir(parents=True,exist_ok=True)
    reservation=control_path('reservations',_digest(os.path.normcase(str(target))))
    with ExitStack() as stack:
        stack.enter_context(DataActivity(control,exclusive=True))
        stack.enter_context(DataActivity(reservation,exclusive=True))
        stack.enter_context(_stable_source(source,closed=closed))
        if resume:
            journal=no_links(resume)
            if journal.parent!=control or journal.suffix!='.json':raise ValueError('搬迁恢复记录不属于当前数据根')
            item=json.loads(journal.read_text('utf-8'))
            if item.get('source')!=str(source) or item.get('target')!=str(target):raise ValueError('搬迁恢复身份不一致')
            if item.get('state')=='COMPLETE':raise ValueError('此搬迁已完成，请查看原收据，不重复发布')
        else:
            _target(source,str(target));files=_files(source);directories=_directories(source)
            revision=_digest(dict(source=str(source),target=str(target),files=files,directories=directories))
            if expected!=revision:raise ValueError('来源内容/目录已变化，请重新检查搬迁计划')
            ident=uuid.uuid4().hex;journal=control/(ident+'.json')
            item=dict(format='ECRA_ROOT_TRANSFER_V1',id=ident,source=str(source),target=str(target),
                started=datetime.now(timezone.utc).isoformat(),state='COPYING',files=files,directories=directories,journal=str(journal))
            write_json(journal,item)
        ident=item['id']
        if not isinstance(ident,str) or len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise ValueError('搬迁记录身份无效')
        if item.get('format')!='ECRA_ROOT_TRANSFER_V1' or journal.stem!=ident or not isinstance(item.get('files'),dict):
            raise ValueError('搬迁记录格式/身份无效')
        for name,row in item['files'].items():
            _safe_name(name)
            if (not isinstance(row,dict) or set(row)!={'size','mtime_ns'} or type(row['size']) is not int
                    or row['size']<0 or type(row['mtime_ns']) is not int):raise ValueError('搬迁文件记录无效')
        if not isinstance(item.get('directories'),list):raise ValueError('搬迁目录清单无效')
        for name in item['directories']:_safe_name(name)
        stage=control_path('staging',ident)
        marker=target/'settings/root-transfers'/(ident+'.json')
        if item['state']=='PUBLISHING' and marker.is_file() and not stage.exists():
            seal=json.loads(marker.read_text('utf-8'))
            if (seal.get('format')!='ECRA_VERIFIED_ROOT_COPY_V1' or seal.get('id')!=ident
                    or seal.get('source')!=str(source) or seal.get('target')!=str(target)
                    or set(_files(target))!={*seal['files'],marker.relative_to(target).as_posix()}
                    or any(_hash(target/_safe_name(name))!=hashed for name,hashed in seal['files'].items())):
                raise ValueError('发布后的搬迁副本校验失败，保留原根和现场')
            item.update(state='COMPLETE',recovered_after_publication=True,
                        verified_source=str(source), verified_source_bytes=sum(r['size'] for r in item['files'].values()))
            write_json(journal,item)
            return item
        _target(source,str(target))
        if _files(source)!=item['files'] or _directories(source)!=item['directories']:
            raise ValueError('来源文件/目录已变化，不能恢复旧搬迁；请创建新计划')
        total=sum(row['size'] for row in item['files'].values())
        parent=target.parent
        while not parent.exists():parent=parent.parent
        ready={}
        for path in sorted(control.glob(ident+'.copies-*.jsonl')):
            for line in path.read_bytes().splitlines(keepends=True):
                if not line.endswith(b'\n'):continue  # incomplete crash tail proves nothing
                row=json.loads(line);ready[row['file']]=row['sha256']
        required = 16*1024**2
        for name, record in item['files'].items():
            existing = no_links(stage/name)
            if name not in ready or not existing.is_file() or _hash(existing) != ready[name]:
                required += record['size']
        if shutil.disk_usage(parent).free < required:
            raise ValueError(f'目标磁盘可用空间不足，需 {required} 字节: {target}；原数据保留')
        stage.mkdir(parents=True,exist_ok=True)
        for name in item['directories']:no_links(stage/name).mkdir(parents=True,exist_ok=True)
        count=copied=reused=0;hashes={}
        log=control/(ident+'.copies-'+uuid.uuid4().hex+'.jsonl')
        def update(state):
            status=dict(id=ident,state=state,journal=str(journal),copied_files=count,total_files=len(item['files']),
                copied_bytes=copied,total_bytes=total,reused_files=reused,source=str(source),target=str(target))
            write_json(control/(ident+'.progress'),status);progress(status)
        try:
            with log.open('xb') as receipts:
                update('COPYING')
                for name,record in item['files'].items():
                    src=no_links(source/name);dst=no_links(stage/name)
                    if not src.is_relative_to(source) or not dst.is_relative_to(stage):raise ValueError('搬迁文件路径越界')
                    hashed=ready.get(name)
                    if hashed and dst.is_file() and _hash(dst)==hashed and _hash(src)==hashed:
                        reused+=1
                    else:
                        dst.parent.mkdir(parents=True,exist_ok=True);pending=no_links(dst.with_name(dst.name+'.ecra-copy-'+ident))
                        sha=hashlib.sha256()
                        with src.open('rb') as reader,pending.open('wb') as writer:
                            for part in iter(lambda:reader.read(1024**2),b''):writer.write(part);sha.update(part)
                            writer.flush();os.fsync(writer.fileno())
                        hashed=sha.hexdigest()
                        stat=src.stat()
                        if dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns)!=record or pending.stat().st_size!=record['size']:
                            raise ValueError('复制期间来源发生变化，拒绝发布')
                        if _hash(pending)!=hashed:raise ValueError('搬迁副本字节校验失败')
                        os.replace(pending,dst);shutil.copystat(src,dst)
                    receipts.write((json.dumps(dict(file=name,sha256=hashed),ensure_ascii=True)+'\n').encode())
                    receipts.flush();os.fsync(receipts.fileno())
                    hashes[name]=hashed;count+=1;copied+=record['size'];update('COPYING')
            update('VALIDATING')
            if (_files(source)!=item['files'] or _directories(source)!=item['directories']
                    or any(_hash(source/name)!=hashed for name,hashed in hashes.items())):
                raise ValueError('校验期间来源内容发生变化，拒绝发布')
            _validate_copy(stage)
            # A crash during rebinding must not resume from a mixed projection.
            # Resume always re-copies changed/moved originals, then revalidates.
            changed,retained=_rebind(stage,source,target)
            if (_files(source)!=item['files'] or _directories(source)!=item['directories']
                    or any(_hash(source/name)!=hashed for name,hashed in hashes.items())):
                raise ValueError('数据库/配置校验期间来源发生变化，拒绝发布')
            physical={name:_hash(stage/name) for name in _files(stage)}
            seal=dict(format='ECRA_VERIFIED_ROOT_COPY_V1',id=ident,source=str(source),target=str(target),
                source_aliases=_aliases(source),files=physical,source_hashes=hashes,source_bytes=total,
                profiles_rebound=changed,retained_runtime=retained)
            out=stage/'settings/root-transfers'/(ident+'.json');out.parent.mkdir(parents=True,exist_ok=True);write_json(out,seal)
            item.update(state='PUBLISHING',profiles_rebound=changed,retained_runtime=retained,reused_files=reused)
            write_json(journal,item)
            _target(source,str(target))
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():target.rmdir()  # only the explicitly selected, still-empty directory
            for attempt in range(6):
                try:
                    stage.rename(target)
                    break
                except PermissionError as exc:
                    if getattr(exc,'winerror',None) not in {5,32,33} or attempt==5:raise
                    if os.path.lexists(target):
                        raise ValueError(f'搬迁目标在发布期间被占用: {target}') from exc
                    time.sleep(.05*2**attempt)
            item.update(state='COMPLETE',copied_files=count,total_bytes=total, verified_source=str(source),
                        verified_source_bytes=total, source_retained=True)
            write_json(journal,item);update('COMPLETE')
            return item
        except BaseException as exc:
            item.update(state='INTERRUPTED' if isinstance(exc,(InterruptedError,KeyboardInterrupt)) else 'FAILED',error=str(exc))
            # Preserve PUBLISHING if the atomic rename already happened.
            if marker.is_file() and not stage.exists():item['state']='PUBLISHING'
            write_json(journal,item)
            raise
