"""Authenticated loopback API for immutable evidence and human decisions."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import uuid
import zipfile

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse as BaseJSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from ..human_reviews import ReviewConflict, ReviewStore
from ..report_package import import_report, export_report, import_delta, export_delta, IDENTITY
from ..scan_store import EvidenceProvider, connect_readonly
from ..workspace import no_links, studio_data_root, formal_workspace
from ..storage_activity import DataActivity,DataBusy
from .display_manifest import DISPLAY_MANIFEST_LIMIT,manifest_object as _manifest_object,display_manifest as _display_manifest


def _startup_barrier(function):
    from functools import wraps
    @wraps(function)
    def guarded(data_root,**kwargs):
        with DataActivity(studio_data_root(data_root),purpose='api'):
            return function(data_root,**kwargs)
    return guarded


class JSONResponse(BaseJSONResponse):
    def render(self, content):
        # Escaped lone UTF-16 surrogates are valid legacy JSON. Sending them
        # as literal UTF-8 would fail or corrupt the original evidence value.
        return json.dumps(content,ensure_ascii=True,allow_nan=False,separators=(',',':')).encode('utf-8')


def _uploaded_manifest_shape(path):
    # The core importer still checks all paths, budgets, hashes and bindings.
    # Guard the JSON container here so malformed input never becomes an
    # AttributeError before the importer can report a domain validation error.
    with zipfile.ZipFile(path) as package:
        try:
            member = package.getinfo('manifest.json')
        except KeyError:
            return  # importer supplies its existing missing-manifest error
        if member.file_size<=DISPLAY_MANIFEST_LIMIT and not member.flag_bits&1:
            with package.open(member) as stream:
                raw=stream.read(DISPLAY_MANIFEST_LIMIT+1)
            if len(raw)<=DISPLAY_MANIFEST_LIMIT:
                return _manifest_object(raw,'结果包导入阶段')


def create_app(data_root=None, *, token=None, authority='127.0.0.1:8765'):
    from ..studio_preferences import startup_selection
    selection = startup_selection(data_root)
    try:
        return _create_app(selection['root'], token=token, authority=authority, startup=selection)
    except (ValueError, OSError) as exc:
        if isinstance(exc,DataBusy):raise
        if selection['source'] != 'GUI_DEFAULT':
            raise
        from ..workspace import default_user_data_root
        fallback = studio_data_root(default_user_data_root())
        if fallback == selection['root']:
            raise
        recovery = dict(root=fallback, source='RECOVERY_DEFAULT', warning='已保存目录无法打开：'+str(exc)+
                        '。当前在系统默认目录恢复设置，原数据保留；请到设置页核对。')
        return _create_app(fallback, token=token, authority=authority, startup=recovery)


@_startup_barrier
def _create_app(data_root, *, token, authority, startup):
    data = studio_data_root(data_root)
    data.mkdir(parents=True, exist_ok=True)
    from .tasks import TaskManager
    from contextlib import asynccontextmanager
    tasks = TaskManager(data)
    from .cleanup_jobs import CleanupJobs
    cleanup=CleanupJobs(data)
    from .migration_jobs import MigrationJobs
    migrations = MigrationJobs(data)
    from .root_transfers import RootTransfers
    transfers=RootTransfers(data)
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await run_in_threadpool(tasks.close)
    session = token or secrets.token_urlsafe(32)
    app = FastAPI(title='ECRA Studio', docs_url=None, redoc_url=None, openapi_url=None,
        default_response_class=JSONResponse, lifespan=lifespan)
    app.state.task_manager = tasks
    app.state.session_token = session
    app.state.data_root = data
    app.state.preference_warning = startup['warning']
    from .downloads import DownloadTickets
    downloads=DownloadTickets(data/'exports');app.state.download_tickets=downloads
    settings = no_links(data/'settings'); settings.mkdir(exist_ok=True)
    device_path = no_links(settings/'device.json')
    if not device_path.exists():
        try:
            with device_path.open('x',encoding='utf-8') as stream:
                json.dump(dict(device='device-'+uuid.uuid4().hex),stream)
        except FileExistsError:
            pass
    try:
        device = json.loads(device_path.read_text(encoding='utf-8'))['device']
        if not isinstance(device,str) or not device:
            raise ValueError()
    except (ValueError,KeyError) as exc:
        raise ValueError('本地设备声明元数据损坏；请保留并核对 '+str(device_path)) from exc

    @app.middleware('http')
    async def boundary(request, call_next):
        if request.headers.get('host') != authority:
            return JSONResponse(dict(error='Host 不属于本地 ECRA 会话'), status_code=403)
        origin = request.headers.get('origin')
        if origin is not None and origin != 'http://' + authority:
            return JSONResponse(dict(error='Origin 不属于本地 ECRA 会话'), status_code=403)
        if request.url.path.startswith('/api/'):
            if not secrets.compare_digest(request.headers.get('x-ecra-session', ''), session):
                return JSONResponse(dict(error='本地会话已失效，请从启动器重新打开'), status_code=401)
            if request.method not in {'GET', 'HEAD'} and origin != 'http://' + authority:
                return JSONResponse(dict(error='写入操作缺少同源校验'), status_code=403)
        lease=None
        if request.url.path.startswith('/api/') and not request.url.path.startswith('/api/data-transfers'):
            try:lease=DataActivity(data,purpose='api').__enter__()
            except DataBusy as exc:return JSONResponse(dict(error=str(exc)),status_code=409)
        try:response = await call_next(request)
        finally:
            if lease:lease.__exit__(None,None,None)
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(Exception)
    async def errors(request, exc):
        # Persist actionable diagnostics without sending stack paths or local
        # secrets to arbitrary network clients. APIs expose domain errors.
        if isinstance(exc, (ValueError, OSError, KeyError, sqlite3.Error)):
            import errno
            sqlite_code=getattr(exc,'sqlite_errorcode',None)
            exhausted=(isinstance(exc,OSError) and (exc.errno==errno.ENOSPC or getattr(exc,'winerror',None) in {39,112})) or (
                isinstance(exc,sqlite3.Error) and ((type(sqlite_code) is int and sqlite_code&255==13) or str(exc).strip().lower()=='database or disk is full'))
            if exhausted:
                message=('写入磁盘空间不足，操作未能正常完成。请检查独立数据目录及系统临时目录所在盘，释放空间后核对当前结果和人工状态再重试。'
                         '“数据与共享”可查看占用和安全回收计划。当前数据目录：'+str(data)+'。技术信息：'+str(exc))
                return JSONResponse(dict(error=message,code='DISK_FULL',detail=str(exc)),status_code=400)
            locked=isinstance(exc,sqlite3.Error) and (
                (type(sqlite_code) is int and sqlite_code&255 in {5,6})
                or str(exc).strip().lower() in {'database is locked','database table is locked','database schema is locked'})
            if locked:
                action='人工确认保存' if request.method=='POST' and request.url.path.endswith('/human') else '当前数据操作'
                message=(action+'遇到数据库占用，未能正常完成。已保存记录保留；请保留当前窗口中的未提交草稿，'
                         '等待其它写入完成，核对人工历史及当前状态后重试。不要删除数据库或确认记录。技术信息：'+str(exc))
                return JSONResponse(dict(error=message,code='DATABASE_BUSY',detail=str(exc)),status_code=409)
            return JSONResponse(dict(error=str(exc)), status_code=409 if isinstance(exc, ReviewConflict) else 400)
        import traceback
        folder = no_links(data/'work/errors'); folder.mkdir(parents=True, exist_ok=True)
        receipt = uuid.uuid4().hex
        (folder/(receipt+'.txt')).write_text(traceback.format_exc(), encoding='utf-8')
        return JSONResponse(dict(error='操作未完成，原归档保留；诊断编号 '+receipt), status_code=500)

    for error_type in (ValueError, OSError, KeyError, sqlite3.Error):
        app.add_exception_handler(error_type, errors)

    def scan_path(scan_id):
        if not IDENTITY.fullmatch(scan_id):
            raise ValueError('扫描身份无效')
        path = no_links(data/'scans'/scan_id)
        if not (path/'scan.db').is_file():
            raise ValueError('扫描不存在；请选择已校验归档')
        return path

    def stores(scan_id):
        path = scan_path(scan_id)
        provider = EvidenceProvider(path/'scan.db')
        binding = provider.metadata()
        return provider, ReviewStore(path/'reviews.db', binding, device=device)

    def degraded_legacy(provider):
        try:
            return provider.node(provider.resolve('provenance', ['legacy_degraded'])).get('value') is True
        except KeyError:
            return False

    @app.get('/api/bootstrap')
    def bootstrap():
        from .sample import sample_info
        return dict(product='ECRA Studio', data_root=str(data), protocol=1,
            data_root_source=startup['source'], preference_warning=startup['warning'],
            sample=sample_info(),
            scan_pipeline='SQLITE_NATIVE_SCAN',
            capabilities=['archive_viewer', 'human_reviews', 'report_packages', 'review_delta', 'profile_validation', 'native_scan_tasks', 'legacy_json_import', 'real_build_preflight'],
            limits=['大型工程资源门禁及完整 U01–U24 尚未全部通过。',
                    '归档内容校验不等于当前源码重新验证；确认者为用户声明，未经认证。'])

    @app.get('/api/settings/data-root')
    def data_root_settings():
        from ..studio_preferences import status
        return status(data, startup['source'], startup['warning'])

    @app.post('/api/data-transfers/preview')
    def transfer_preview(payload: dict):
        from ..data_transfer import preview
        return preview(payload.get('source') or data,payload.get('target'))

    @app.get('/api/data-transfers')
    def transfer_history():
        return dict(items=transfers.history())

    @app.post('/api/data-transfers')
    def start_transfer(payload: dict):
        return transfers.start(payload.get('source') or data,payload.get('target'),expected=payload.get('revision'))

    @app.get('/api/data-transfers/{ident}')
    def transfer_status(ident: str):
        return transfers.get(ident)

    @app.post('/api/data-transfers/{ident}/resume')
    def resume_transfer(ident: str):
        return transfers.resume(ident)

    @app.post('/api/settings/data-root/preview')
    def preview_data_root(payload: dict):
        from ..studio_preferences import preview
        return preview(payload.get('path'), data)

    @app.put('/api/settings/data-root')
    def save_data_root(payload: dict):
        from ..studio_preferences import save, PreferenceConflict
        try:
            return save(payload.get('path'), data, plan_id=payload.get('plan_id'),
                        revision=payload.get('revision'), repair=payload.get('repair') is True)
        except PreferenceConflict as exc:
            return JSONResponse(dict(error=str(exc)), status_code=409)

    @app.post('/api/sample/open')
    def open_builtin_sample():
        from .sample import open_sample
        return open_sample(data)

    @app.get('/api/scans')
    def scans():
        result = []
        root = no_links(data/'scans')
        if root.exists():
            for directory in sorted(root.iterdir()):
                try:
                    no_links(directory)
                    if not directory.is_dir() or not (directory/'scan.db').is_file():
                        continue
                    if (directory/'storage.json').is_file() and not (directory/'manifest.json').is_file():
                        continue  # task work is never mistaken for a published result
                    item = EvidenceProvider(directory/'scan.db').metadata()
                    if item['scan_id']!=directory.name:
                        raise ValueError('扫描目录与静态库身份不一致；请保留原件并核对完整结果包')
                    item['mode'] = 'OFFLINE_ARCHIVE'
                    item['can_open'] = True
                    if (directory/'manifest.json').is_file():
                        manifest = _display_manifest(directory/'manifest.json', item)
                        if manifest.get('format') == 'ECRA_LOCAL_SCAN':
                            item.update(mode='LOCAL_SNAPSHOT', state=manifest['state'], completed_at=manifest.get('completed_at'))
                except (ValueError, sqlite3.Error, OSError, KeyError, TypeError) as exc:
                    item = dict(scan_id=directory.name, state='FAILED', can_open=False, error=str(exc))
                result.append(item)
        return dict(items=result)

    @app.get('/api/history')
    def history(project: str='', profile: str='', core: str='', git: str='', scan_mode: str='', state: str='',
                date_from: str='', date_to: str='', offset: int=0, limit: int=20):
        from .history import history as query_history
        return query_history(data, project=project, profile=profile, core=core, git=git, scan_mode=scan_mode,
                             state=state, date_from=date_from, date_to=date_to, offset=offset, limit=limit)

    @app.get('/api/history/compare')
    def compare_history(base: str, current: str, search: str='', change: str='', offset: int=0, limit: int=50):
        from .comparison import compare_archives
        return compare_archives(scan_path(base), scan_path(current), search=search, change=change, offset=offset, limit=limit)

    @app.get('/api/scans/{scan_id}/summary')
    def summary(scan_id: str):
        provider, reviews = stores(scan_id)
        counts = provider.counts()
        from .query import QueryService
        current=QueryService(scan_path(scan_id)).current_summary()
        total = sum(counts.values())
        binding = provider.metadata()
        mode = 'OFFLINE_ARCHIVE'
        manifest_path = scan_path(scan_id)/'manifest.json'
        if manifest_path.is_file():
            manifest = _display_manifest(manifest_path, binding)
            if manifest.get('format') == 'ECRA_LOCAL_SCAN':
                binding['state'] = manifest['state']; mode = 'LOCAL_SNAPSHOT'
        try:
            legacy_warning = provider.node(provider.resolve('provenance', ['legacy_warning'])).get('value')
        except KeyError:
            legacy_warning = None
        try:
            evidence_notice = provider.node(provider.resolve('provenance', ['evidence_notice'])).get('value')
        except KeyError:
            evidence_notice = None
        degraded = degraded_legacy(provider)
        from ..scan_identity import query as scan_identity
        return dict(binding=binding, static_counts=counts, total=total,**current,
                    identity=scan_identity(provider),
                    counting_basis='完整清单以canonical身份计数；容器/未进入构建/非存储单列，不计入已证明安全。',
                    mode=mode,legacy_warning=legacy_warning,evidence_notice=evidence_notice,legacy_degraded=degraded,can_confirm=not degraded,
                    diff=QueryService(scan_path(scan_id)).diff_summary(),
                    can_review=not degraded and (scan_path(scan_id)/'scan_state.json').is_file(), roots=provider.roots())

    @app.get('/api/scans/{scan_id}/ai')
    def ai_records(scan_id: str, offset: int=0, limit: int=50, outcome: str='', search: str=''):
        from ..scan_persistence import ai_page
        return ai_page(scan_path(scan_id),offset,limit,outcome=outcome,search=search)

    @app.get('/api/scans/{scan_id}/ai-artifact')
    def ai_artifact(scan_id: str, name: str, offset: int=0, limit: int=16384):
        from ..report_package import sha256
        out=scan_path(scan_id)
        if (Path(name).name!=name or '/' in name or '\\' in name or ':' in name
                or not name.endswith(('.json','.txt')) or offset<0 or not 1<=limit<=16384):
            raise ValueError('复核收据名称/游标无效')
        file=no_links(out/'review'/name)
        if not file.is_file():
            manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
            indices=set(manifest.get('audit_indices',[]))
            if manifest.get('audit_index'):
                indices.add(manifest['audit_index'])
            if not indices:
                raise ValueError('此归档未包含对应审计收据')
            from ..report_package import OBJECT
            matches=set()
            for index_hash in indices:
                if not OBJECT.fullmatch('evidence/'+index_hash):
                    raise ValueError('审计索引引用无效')
                index=json.loads((out/'evidence'/index_hash).read_text(encoding='utf-8'))
                record=index['files'].get('review/'+name)
                if record:
                    matches.add(record.get('sha256'))
            if not matches:
                raise ValueError('归档中缺少此收据')
            if len(matches)!=1:
                raise ValueError('此便捷名称对应多个历史版本；请选择带时间戳的不可变收据')
            hashed=matches.pop()
            if not OBJECT.fullmatch('evidence/'+str(hashed)):
                raise ValueError('收据对象身份无效')
            file=no_links(out/'evidence'/hashed)
            if sha256(file)!=hashed:
                raise ValueError('审计收据内容损坏')
        with file.open('rb') as stream:
            stream.seek(offset); raw=stream.read(limit)
        for trim in range(4):
            try:
                chunk=raw[:-trim] if trim else raw
                text=chunk.decode('utf-8');break
            except UnicodeDecodeError as exc:
                if exc.start<len(raw)-3 or trim==3:
                    raise ValueError('收据文本游标不在 UTF8 边界') from exc
        total=file.stat().st_size
        return dict(text=text,offset=offset,total=total,next_offset=offset+len(chunk) if offset+len(chunk)<total else None)

    @app.get('/api/scans/{scan_id}/symbols')
    def symbols(scan_id: str, search: str='', classification: str='', human_decision: str='',
                handling_status: str='',file: str='',function: str='',context: str='',coverage: str='',ai_state: str='',
                current_result: str='',review_scope: str='all',diff: str='',symbol_id: str='',sort: str='priority',order: str='asc',offset: int=0, limit: int=50):
        from .query import QueryService
        provider, reviews = stores(scan_id)
        page = QueryService(scan_path(scan_id)).symbols(search=search, classification=classification,
            human_decision=human_decision,handling_status=handling_status,file=file,function=function,context=context,
            coverage=coverage,ai_state=ai_state,current_result=current_result,review_scope=review_scope,diff=diff,symbol_id=symbol_id,sort=sort,order=order,offset=offset,limit=limit)
        for item in page['items']:
            item['human'] = reviews.current(item['symbol_id'], provider.fingerprint(item['symbol_id']))
        return page

    @app.get('/api/scans/{scan_id}/result-revision')
    def result_revision(scan_id: str):
        from .query import QueryService
        return QueryService(scan_path(scan_id)).result_revision()

    @app.get('/api/scans/{scan_id}/symbol-ai')
    def symbol_ai(scan_id: str,symbol_id: str,offset: int=0,limit: int=20):
        from .query import QueryService
        return QueryService(scan_path(scan_id)).symbol_ai(symbol_id,offset=offset,limit=limit)

    @app.get('/api/scans/{scan_id}/symbol')
    def exact_symbol(scan_id: str, symbol_id: str):
        from .query import QueryService
        provider,reviews=stores(scan_id)
        page=QueryService(scan_path(scan_id)).symbols(symbol_id=symbol_id,limit=1)
        if not symbol_id or not page['items']:raise ValueError('当前归档未记录该规范身份；不能据此解释为无影响')
        item=page['items'][0]
        item['human']=reviews.current(symbol_id,provider.fingerprint(symbol_id))
        return item

    def coverage_service(scan_id):
        from .coverage import CoverageService
        return CoverageService(scan_path(scan_id)/'scan.db')

    @app.get('/api/scans/{scan_id}/coverage')
    def coverage_summary(scan_id: str):
        return coverage_service(scan_id).summary()

    @app.get('/api/scans/{scan_id}/coverage/groups')
    def coverage_groups(scan_id: str,offset: int=0,limit: int=50):
        return coverage_service(scan_id).groups(offset,limit)

    @app.get('/api/scans/{scan_id}/coverage/issues')
    def coverage_issues(scan_id: str,kind_node: int|None=None,missing_kind: bool=False,offset: int=0,limit: int=50):
        return coverage_service(scan_id).issues(kind_node,missing_kind,offset,limit)

    @app.get('/api/scans/{scan_id}/coverage/blockers')
    def coverage_blockers(scan_id: str,offset: int=0,limit: int=50):
        return coverage_service(scan_id).blockers(offset,limit)

    @app.get('/api/scans/{scan_id}/coverage/tus')
    def coverage_tus(scan_id: str,status_node: int|None=None,status_missing: bool=False,search: str='',
                     zero_only: bool=False,offset: int=0,limit: int=50):
        return coverage_service(scan_id).translation_units(status_node,status_missing,search,zero_only,offset,limit)

    @app.get('/api/scans/{scan_id}/coverage/related')
    def coverage_related(scan_id: str,node: int,offset: int=0,limit: int=50):
        return coverage_service(scan_id).related(node,offset,limit)

    @app.get('/api/scans/{scan_id}/coverage/position')
    def coverage_position(scan_id: str):
        return stores(scan_id)[1].position('coverage')

    @app.put('/api/scans/{scan_id}/coverage/position')
    def save_coverage_position(scan_id: str,payload: dict):
        stores(scan_id)[1].position('coverage',payload)
        return dict(saved=True)

    @app.get('/api/scans/{scan_id}/records/{relation}')
    def records(scan_id: str, relation: str, dataset: str='facts', symbol_id: str|None=None,
                function_id: str|None=None, source_id: str|None=None, target_id: str|None=None, offset: int=0, limit: int=50):
        provider = EvidenceProvider(scan_path(scan_id)/'scan.db')
        return provider.records(relation, dataset=dataset, symbol_id=symbol_id, function_id=function_id,
                                source_id=source_id, target_id=target_id, offset=offset, limit=limit)

    @app.get('/api/scans/{scan_id}/symbol-functions')
    def symbol_functions(scan_id: str, symbol_id: str, offset: int=0, limit: int=50):
        from .query import QueryService
        return QueryService(scan_path(scan_id)).symbol_functions(symbol_id,offset=offset,limit=limit)

    @app.get('/api/scans/{scan_id}/call-neighbors')
    def call_neighbors(scan_id: str, function_id: str, direction: str='upstream', offset: int=0, limit: int=50):
        from .query import QueryService
        return QueryService(scan_path(scan_id)).call_neighbors(function_id,direction=direction,offset=offset,limit=limit)

    @app.get('/api/scans/{scan_id}/nodes/{node_id}')
    def node(scan_id: str, node_id: int, offset: int=0, limit: int=50):
        return EvidenceProvider(scan_path(scan_id)/'scan.db').node(node_id, offset=offset, limit=limit)

    @app.get('/api/scans/{scan_id}/text/{node_id}')
    def text(scan_id: str, node_id: int, offset: int=0, limit: int=8192):
        return EvidenceProvider(scan_path(scan_id)/'scan.db').text(node_id, offset=offset, limit=limit)

    @app.get('/api/scans/{scan_id}/source')
    def source(scan_id: str, file: str):
        return EvidenceProvider(scan_path(scan_id)/'scan.db').archived_source(file)

    @app.get('/api/scans/{scan_id}/legacy-files')
    def legacy_files_page(scan_id: str, offset: int=0, limit: int=50):
        provider = EvidenceProvider(scan_path(scan_id)/'scan.db')
        root = provider.resolve('provenance', ['legacy_inputs'])
        page = provider.node(root, offset=offset, limit=limit)
        items = []
        for item in page['items']:
            fields = {row['key']:row.get('value') for row in provider.node(item['id'],limit=20)['items']}
            items.append(dict(fields, ordinal=item['ordinal']))
        return dict(items=items,total=page['total'],offset=offset,next_offset=page['next_offset'])

    @app.get('/api/scans/{scan_id}/legacy-file')
    def legacy_file_text(scan_id: str, ordinal: int, offset: int=0, limit: int=8192):
        if ordinal < 0 or offset < 0 or not 1 <= limit <= 16384:
            raise ValueError('旧审计文件游标无效')
        out = scan_path(scan_id); provider = EvidenceProvider(out/'scan.db')
        node = provider.resolve('provenance', ['legacy_inputs', ordinal])
        fields = {row['key']:row.get('value') for row in provider.node(node,limit=20)['items']}
        if fields.get('disposition') != 'OPAQUE_AUDIT_PRESERVED':
            raise ValueError('该完整事实/报告已转换到权威库；请在原始证据中逐段浏览')
        from ..report_package import OBJECT
        hashed = fields.get('sha256','')
        if not OBJECT.fullmatch('evidence/'+hashed): raise ValueError('旧审计对象身份损坏')
        file = no_links(out/'evidence'/hashed)
        if file.stat().st_size != fields['size'] or offset > fields['size']:
            raise ValueError('旧审计对象大小或游标不符')
        with file.open('rb') as stream:
            stream.seek(offset); block = stream.read(limit)
        # Bytes remain exact in CAS. Preview binary or non-UTF8 data as hex,
        # never execute imported SQLite, HTML, shell or embedded scripts.
        try:
            for trim in range(4):
                try:
                    part = block[:-trim] if trim else block
                    text = part.decode('utf-8'); break
                except UnicodeDecodeError as exc:
                    if exc.start < len(block)-3 or trim == 3: raise
            if b'\0' in part: raise UnicodeError()
            if block and not part: raise UnicodeError()
            encoding = 'utf-8'
        except UnicodeError:
            text = block.hex(' '); part = block; encoding = 'hex'
        next_offset = offset+len(part)
        return dict(file=fields['file'],sha256=hashed,encoding=encoding,text=text,
            offset=offset,total=fields['size'],next_offset=next_offset if next_offset<fields['size'] else None,
            source='归档旧文件原始字节；仅文本/十六进制查看，不作为当前安全证明')

    @app.get('/api/scans/{scan_id}/source-window')
    def source_lines(scan_id: str,file: str,line: int=1,before: int=10,after: int=30):
        from .source_view import source_window
        return source_window(EvidenceProvider(scan_path(scan_id)/'scan.db'),file,line=line,before=before,after=after)

    @app.get('/api/scans/{scan_id}/human')
    def human(scan_id: str, symbol_id: str):
        provider, reviews = stores(scan_id)
        fingerprint = provider.fingerprint(symbol_id)
        return dict(fingerprint=fingerprint, **reviews.current(symbol_id, fingerprint), history=reviews.history(symbol_id),
                    prior_reviews=reviews.prior(symbol_id,fingerprint))

    @app.post('/api/scans/{scan_id}/human')
    def save_human(scan_id: str, payload: dict):
        provider, reviews = stores(scan_id)
        if degraded_legacy(provider):
            raise ValueError('未验证原件归档没有可信变量证据，不能保存当前人工结论；请查看原文件或导入完整结果')
        symbol = payload['symbol_id']
        fingerprint = provider.fingerprint(symbol)
        if payload.get('fingerprint') != fingerprint:
            raise ValueError('确认依据不是当前完整证据，请重新打开变量')
        arguments = dict(reviewer=payload['reviewer'], comment=payload.get('comment', ''), expected_heads=payload.get('expected_heads', []))
        if payload.get('undo'):
            event = reviews.undo(symbol, fingerprint, **arguments)
        else:
            event = reviews.append(symbol, fingerprint, decision=payload['decision'],
                handling_status=payload.get('handling_status', 'TODO'), resolve=payload.get('resolve', False), **arguments)
        return dict(saved=True, event=event)

    @app.get('/api/scans/{scan_id}/position')
    def position(scan_id: str):
        return stores(scan_id)[1].position('workbench')

    @app.put('/api/scans/{scan_id}/position')
    def save_position(scan_id: str, payload: dict):
        stores(scan_id)[1].position('workbench', payload)
        return dict(saved=True)

    @app.post('/api/import')
    async def import_upload(request: Request):
        # Raw streaming body avoids loading an entire ZIP into server memory.
        work = no_links(data/'work'); work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='upload-', dir=work) as folder:
            upload = Path(folder)/'upload.ecra-report'
            total = 0
            with upload.open('xb') as stream:
                async for block in request.stream():
                    total += len(block)
                    if total>128*1024**3:
                        raise ValueError('上传包超过128GiB预算')
                    stream.write(block)
            try:
                incoming = await run_in_threadpool(_uploaded_manifest_shape, upload)
                if incoming is not None:
                    ident = incoming.get('scan_id')
                    if isinstance(ident,str) and IDENTITY.fullmatch(ident):
                        existing = no_links(data/'scans'/ident)
                        if (existing/'manifest.json').is_file() and (existing/'scan.db').is_file():
                            # Merging also reads the existing manifest. A bad
                            # target must not become another internal .get error.
                            try:
                                binding = await run_in_threadpool(lambda: EvidenceProvider(existing/'scan.db').metadata())
                                await run_in_threadpool(_display_manifest,existing/'manifest.json',binding)
                            except ValueError as exc:
                                raise ValueError('结果包导入阶段：已有扫描清单无法校验，本次未合并；已有证据与人工记录保留。'
                                                 '请在新的独立数据目录导入完整备份，或重新扫描。技术信息：'+str(exc)) from exc
                return await run_in_threadpool(import_report, upload, data)
            except (zipfile.BadZipFile, EOFError) as exc:
                return JSONResponse(dict(code='INVALID_REPORT_ARCHIVE',detail=str(exc),
                    error='结果包导入阶段失败：文件不是完整有效的 ZIP 结果包，或包内容已损坏。'
                          '本次未发布结果，已有扫描与人工记录保留；原上传文件未修改。'
                          '请重新获取完整的 .ecra-report 备份，在“数据与共享”重新导入。技术信息：'+str(exc)),status_code=400)

    @app.post('/api/migrations/preview')
    def migration_preview(payload: dict):
        return migrations.preview(payload['source'], payload['project_root'], allow_degraded=payload.get('allow_degraded',False))

    @app.post('/api/multicore/elf')
    async def multicore_elf(request: Request, name: str='firmware.elf'):
        import os
        import shutil
        import struct
        from ..storage_activity import DataActivity
        if len(name.encode('utf-8'))>1024:raise ValueError('ELF文件名过长')
        base=no_links(data/'work/multicore-elfs');base.mkdir(parents=True,exist_ok=True)
        identity=uuid.uuid4().hex
        with DataActivity(data),tempfile.TemporaryDirectory(prefix='elf-upload-',dir=base) as temporary:
            folder=Path(temporary);path=folder/'firmware.elf';size=0;hashed=hashlib.sha256()
            with path.open('xb') as stream:
                async for block in request.stream():
                    size+=len(block)
                    if size>2*1024**3:raise ValueError('ELF超过2GiB单文件导入预算；本次未提交合并')
                    if shutil.disk_usage(base).free<len(block)+512*1024**2:raise ValueError('工作盘剩余空间不足，请释放空间后重新上传ELF')
                    stream.write(block);hashed.update(block)
                stream.flush();os.fsync(stream.fileno())
            with path.open('rb') as stream:header=stream.read(20)
            if len(header)<20 or header[:7]!=b'\x7fELF\x01\x01\x01' or struct.unpack_from('<H',header,18)[0]!=40:
                raise ValueError('请选择真实ARM小端ELF32链接文件；未上传为可用多核输入')
            record=dict(format='ECRA_MULTICORE_ELF_V1',id=identity,name=name,bytes=size,sha256=hashed.hexdigest())
            from ..common import write_json
            write_json(folder/'input.json',record)
            folder.rename(base/identity)
        return record

    @app.post('/api/multicore/preview')
    def multicore_preview(payload: dict):
        from .multicore_inputs import prepare
        return prepare(data,payload.get('inputs'),payload.get('regions'))

    @app.post('/api/multicore/start')
    def multicore_start(payload: dict):
        from .multicore_inputs import start
        return start(data,payload.get('id'),payload.get('revision'),tasks,payload.get('resources'))

    @app.post('/api/migrations')
    def migration_start(payload: dict):
        return migrations.start(payload['source'], payload['project_root'], payload['revision'], allow_degraded=payload.get('allow_degraded',False))

    @app.get('/api/migrations')
    def migration_history(offset: int=0, limit: int=50):
        return migrations.history(offset,limit)

    @app.get('/api/migrations/{job_id}')
    def migration_status(job_id: str):
        return migrations.get(job_id)

    @app.post('/api/scans/{scan_id}/delta/import')
    async def delta_upload(scan_id: str, request: Request):
        raw = bytearray()
        async for block in request.stream():
            raw.extend(block)
            if len(raw)>256*1024**2:
                raise ValueError('人工增量超过256MiB预算')
        work = no_links(data/'work'); work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='delta-', dir=work) as folder:
            path = Path(folder)/'delta'; path.write_bytes(raw)
            return await run_in_threadpool(import_delta, path, scan_path(scan_id))

    @app.post('/api/scans/{scan_id}/export')
    def export(scan_id: str, payload: dict):
        kind=payload.get('kind','full')
        if not isinstance(kind,str) or kind not in {'full','delta'}:raise ValueError('请选择标准完整包或人工确认增量')
        compression=payload.get('compression','compact')
        if kind=='full' and (not isinstance(compression,str) or compression not in {'compact','deflate'}):
            raise ValueError('完整包压缩只支持 compact（省空间）或 deflate（快速）')
        exports = no_links(data/'exports'); exports.mkdir(exist_ok=True)
        ident = uuid.uuid4().hex
        delta = kind=='delta'
        name = ident + ('.ecra-review-delta' if delta else '.ecra-report')
        if delta:
            export_delta(scan_path(scan_id),exports/name)
            return dict(download='/api/download/'+name,filename=name)
        export_report(scan_path(scan_id),exports/name,compression=compression)
        import zipfile
        with zipfile.ZipFile(exports/name) as zipped:
            actual='compact' if zipped.getinfo('scan.db').compress_type==zipfile.ZIP_BZIP2 else 'deflate'
        return dict(download='/api/download/'+name,filename=name,compression=actual,
                    compression_fallback=actual!=compression)

    @app.get('/api/download/{name}')
    def download(name: str):
        return FileResponse(downloads.path(name), filename=name, media_type='application/octet-stream')

    @app.post('/api/download/{name}/ticket')
    def download_ticket(name: str):
        return downloads.issue(name)

    @app.get('/export-download/{ticket}')
    def native_download(ticket: str):
        from .downloads import DownloadExpired
        try:path=downloads.resolve(ticket)
        except DownloadExpired as exc:return JSONResponse(dict(error=str(exc)),status_code=410)
        return FileResponse(path,filename=path.name,media_type='application/octet-stream')

    @app.get('/api/storage/policy')
    def storage_policy():
        from ..storage_policy import status
        return status(data)

    @app.post('/api/storage/policy')
    def save_storage_policy(payload:dict):
        from ..storage_policy import save,PolicyConflict
        try:return save(data,mode=payload.get('mode'),revision=payload.get('revision'),repair=payload.get('repair') is True)
        except PolicyConflict as exc:return JSONResponse(dict(error=str(exc)),status_code=409)

    @app.get('/api/storage')
    def storage():
        from ..storage_usage import measure
        return measure(data)

    @app.get('/api/profiles')
    def profiles():
        root = no_links(data/'projects')
        items = []
        if root.exists():
            for path in root.glob('*/profiles/*.yaml'):
                no_links(path)
                items.append(dict(id=path.stem, project_id=path.parent.parent.name,
                                  yaml=path.read_bytes().decode('utf-8'), revision=hashlib.sha256(path.read_bytes()).hexdigest()))
                from ..config import configured_project_root
                items[-1]['project_root'] = str(configured_project_root(path))
                from ..config import read_yaml
                project=read_yaml(path).get('project',{})
                name=project.get('name') if isinstance(project,dict) else None
                items[-1]['name']=name if isinstance(name,str) and name.strip() else path.stem
        return dict(items=items)

    @app.get('/api/profiles/options')
    def profile_options():
        from .profile_options import OPTIONS
        return dict(items=OPTIONS)

    @app.post('/api/profiles/form')
    def profile_form(payload: dict):
        from .profile_forms import form_state
        return form_state(payload.get('yaml'))

    @app.post('/api/profiles/git-versions')
    def profile_git_versions(payload: dict):
        from .git_versions import inspect_versions
        return inspect_versions(payload.get('project_root'), data/'work/git-versions',
            **{key: payload[key] for key in ('base_ref','current_ref','include_uncommitted','search','offset','limit','build_mode') if key in payload})

    @app.post('/api/profiles/directories')
    def profile_directories(payload: dict):
        from .directories import browse
        return browse(**{key:payload[key] for key in ('path','root','after','search','limit','kind') if key in payload})

    @app.post('/api/profiles/form-merge')
    def profile_form_merge(payload: dict):
        from .profile_forms import merge_form,backup_original
        raw=payload.get('yaml');result=merge_form(raw,payload.get('changes'))
        if result['yaml']!=raw:result['backup']=backup_original(settings,raw)
        return result

    @app.get('/api/profiles/drafts/{identity}')
    def profile_draft(identity: str):
        from .profile_forms import read_backup
        return dict(yaml=read_backup(settings,identity),id=identity)

    @app.post('/api/storage/cleanup')
    def cleanup_start(payload: dict):
        operation=payload.get('operation')
        if operation in {'quarantine','purge'} and payload.get('confirmed') is not True:
            raise ValueError('请先核对预览，并明确确认本次隔离/永久释放范围')
        return cleanup.start(operation,payload.get('preview_id'))

    @app.get('/api/storage/cleanup/jobs')
    def cleanup_history(offset: int=0,limit: int=50):
        return cleanup.history(offset,limit)

    @app.get('/api/storage/cleanup/jobs/{job_id}')
    def cleanup_job(job_id: str):
        return cleanup.get(job_id)

    @app.get('/api/storage/cleanup/previews/{preview_id}')
    def cleanup_preview(preview_id: str,offset: int=0,limit: int=50):
        from ..garbage_collection import status
        return status(data,preview_id,offset=offset,limit=limit)

    def profile_path(project_id, profile_id):
        if not IDENTITY.fullmatch(project_id) or not IDENTITY.fullmatch(profile_id):
            raise ValueError('工程/配置身份无效')
        path = no_links(data/'projects'/project_id/'profiles'/(profile_id+'.yaml'))
        if not path.is_file():
            raise ValueError('配置不存在；请先保存独立配置')
        return path

    @app.get('/api/tasks')
    def list_tasks():
        return dict(items=tasks.list())

    @app.get('/api/review-materials')
    def review_materials():
        from .review_materials import describe
        return describe()

    @app.post('/api/review-materials')
    def save_review_materials(payload: dict):
        from .review_materials import save
        return save(data,payload)

    def profile_transaction(function):
        from functools import wraps
        @wraps(function)
        def serialized(payload: dict):
            with closing(sqlite3.connect(no_links(settings/'profiles.db'),timeout=10)) as conn, conn:
                conn.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT)')
                conn.execute('BEGIN IMMEDIATE')
                return function(payload)
        return serialized

    @app.post('/api/tasks')
    @profile_transaction
    def start_task(payload: dict):
        path = profile_path(payload['project_id'], payload['profile_id'])
        revision = payload.get('revision')
        if not isinstance(revision, str):
            raise ReviewConflict('配置已变化；请重新选择后扫描')
        return tasks.start(path, profile_id=payload['profile_id'], mode=payload.get('mode','scan'),
                           scan_id=payload.get('scan_id'), resources=payload.get('resources'),
                           expected_revision=revision, request_id=payload.get('request_id'))

    @app.get('/api/tasks/{task_id}')
    def task_detail(task_id: str, offset: int=0, limit: int=65536):
        return tasks.detail(task_id, offset=offset, limit=limit)

    @app.get('/api/tasks/{task_id}/plan')
    def build_plan(task_id: str, offset: int=0, limit: int=20):
        from .preflight import plan_page
        return plan_page(tasks.directory(task_id)/'preflight', offset=offset, limit=limit)

    @app.post('/api/tasks/{task_id}/stop')
    def stop_task(task_id: str):
        return tasks.stop(task_id)

    @app.post('/api/tasks/{task_id}/retry')
    def retry_task(task_id: str):
        folder = tasks.directory(task_id)
        saved = json.loads((folder/'task.json').read_text(encoding='utf-8'))
        if saved['state'] not in {'FAILED', 'INTERRUPTED'}:
            raise ValueError('只有失败/已停止任务可恢复；完成任务请从配置发起新扫描')
        return tasks.start(folder/'semantics.yaml', profile_id=saved['profile_id'],
                           retry_from=task_id,
                           mode=saved.get('mode','scan'),scan_id=saved['scan_id'],resources=dict(
                               preset='manual',peak_gib=saved['budget_bytes']/1024**3,
                               workers=saved.get('resource_policy',{}).get('workers',1)),
                           multicore=json.loads((folder/'multicore.json').read_text('utf-8')) if saved.get('mode')=='multicore' else None)

    @app.post('/api/profiles/check')
    def check_profile(payload: dict):
        from ..config import load_config, configured_project_root, read_yaml
        from ..portable import tool_path
        import shutil
        work = no_links(data/'work'); work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='profile-check-', dir=work) as folder:
            path = Path(folder)/'semantics.yaml'
            path.write_text(payload['yaml'], encoding='utf-8')
            raw = read_yaml(path)
            if not isinstance(raw,dict) or not isinstance(raw.get('project'),dict) or not Path(str(raw['project'].get('root',''))).is_absolute():
                raise ValueError('Studio project.root 必须是固件绝对路径，例如 D:/Firmware/Board；其他相对字段仍相对固件解释。')
            root = configured_project_root(path)
            if not root.is_dir():
                raise ValueError('工程目录不存在: '+str(root))
            cfg, _ = load_config(root, path)
            analysis = dict(cfg['analysis'])
            if analysis.get('output', {}).get('location', 'user') == 'user':
                analysis['output'] = dict(location='custom', custom_dir=str(data))
            ws = formal_workspace(root, analysis)
            if Path(ws.workspace_root) != data:
                raise ValueError('配置输出与当前 Studio 数据根不同；请使用 output.location: user。')
            checks = []
            for tool in ('cmake', 'arm-none-eabi-gcc', 'git'):
                repair = ''
                try:
                    resolved = tool_path(tool)
                    found = Path(resolved).is_file() or shutil.which(resolved) is not None
                except ValueError as exc:
                    resolved = str(exc); found = False; repair = str(exc)
                checks.append(dict(tool=tool, path=resolved, available=found,
                    repair='' if found else repair or '请在Portable工具清单中安装/核对 '+tool+'，并重新检查。'))
            return dict(project_id=ws.project_id, project_root=str(root), data_root=ws.workspace_root,
                        checks=checks, ready_for_scan=False,
                        note='配置与工具路径检查；启动扫描后才执行真实构建、Clang、输入闭包及持久化校验。')

    @app.post('/api/profiles')
    @profile_transaction
    def save_profile(payload: dict):
        checked = check_profile(payload)
        ident = payload.get('id') or uuid.uuid4().hex
        if not IDENTITY.fullmatch(ident):
            raise ValueError('配置身份无效')
        root = no_links(data/'projects'/checked['project_id']/'profiles'); root.mkdir(parents=True, exist_ok=True)
        target = no_links(root/(ident+'.yaml'))
        if target.exists():
            old = target.read_bytes()
            if payload.get('revision') != hashlib.sha256(old).hexdigest():
                raise ReviewConflict('配置已变化，请重新打开后另存或合并')
            history = no_links(root/'history'); history.mkdir(exist_ok=True)
            (history/(ident+'-'+uuid.uuid4().hex+'.yaml')).write_bytes(old)
        raw = payload['yaml'].encode('utf-8')
        with tempfile.NamedTemporaryFile(dir=root, suffix='.pending', delete=False) as stream:
            pending = Path(stream.name)
            try:
                stream.write(raw); stream.flush()
                import os
                os.fsync(stream.fileno())
            except BaseException:
                stream.close(); pending.unlink(missing_ok=True); raise
        try:
            pending.replace(target)
        finally:
            pending.unlink(missing_ok=True)
        return dict(saved=True, id=ident, project_id=checked['project_id'], revision=hashlib.sha256(raw).hexdigest())

    assets = Path(__file__).parent/'web'
    if assets.exists():
        app.mount('/', StaticFiles(directory=assets, html=True), name='studio')
    return app
