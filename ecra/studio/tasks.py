"""Persistent real scan tasks. One process tree owns the shared scan budget."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid

from ..common import write_json, read_json
from ..workspace import no_links
from ..report_package import IDENTITY
from .process_budget import ProcessBudget


def now():
    return datetime.now(timezone.utc).isoformat()


class TaskManager:
    def __init__(self, data):
        self.data = Path(data)
        self.work = no_links(self.data/'work/tasks'); self.work.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.active = None
        from ..storage_activity import DataActivity
        try:
            lease=DataActivity(self.data,exclusive=True,purpose='scan-budget').__enter__()
        except ValueError:
            pass  # another Studio instance still owns these running tasks
        else:
            try:
                for path in self.work.glob('*/task.json'):
                    value = read_json(no_links(path))
                    if value['state'] in {'RUNNING', 'STOP_REQUESTED'}:
                        value.update(state='INTERRUPTED', finished=now(), error='上次监督器退出；保留完整 TU 缓存与诊断，可重新校验输入后恢复。')
                        write_json(path, value)
            finally:lease.__exit__(None,None,None)

    def list(self):
        return sorted((read_json(no_links(path)) for path in self.work.glob('*/task.json')),
                      key=lambda item:item['started'], reverse=True)

    def directory(self, ident):
        if not IDENTITY.fullmatch(ident):
            raise ValueError('任务身份无效')
        folder = no_links(self.work/ident)
        if not (folder/'task.json').is_file():
            raise ValueError('任务不存在')
        return folder

    def start(self, profile_path, *, profile_id, mode='scan', scan_id=None,resources=None):
        from ..config import load_config, configured_project_root
        from ..workspace import formal_workspace
        root = configured_project_root(profile_path)
        cfg, _ = load_config(root, profile_path)
        from .resource_policy import policy
        limits=policy(resources)
        # Validate relative to the service's explicitly selected data root.
        analysis = dict(cfg['analysis'])
        if analysis.get('output', {}).get('location', 'user') == 'user':
            analysis['output'] = dict(location='custom', custom_dir=str(self.data))
        ws = formal_workspace(root, analysis)
        if Path(ws.workspace_root) != self.data:
            raise ValueError('配置的数据根与当前 Studio 不同；请在配置中使用 output.location: user，或从该数据根启动 Studio。')
        if mode not in {'scan','review','review-failed'}:
            raise ValueError('未知任务模式')
        if mode!='scan':
            from ..scan_store import EvidenceProvider
            if not isinstance(scan_id,str) or not IDENTITY.fullmatch(scan_id):
                raise ValueError('复核扫描身份无效')
            out=no_links(self.data/'scans'/scan_id)
            if not (out/'scan_state.json').is_file() or not root.is_dir():
                raise ValueError('归档缺少本机恢复检查点或原源码；可浏览证据，不能重新证明。')
            if EvidenceProvider(out/'scan.db').metadata()['project_id']!=ws.project_id:
                raise ValueError('复核配置与扫描工程身份不符')
        with self.lock:
            if self.active is not None:
                raise ValueError('共享扫描预算正在使用；请等待当前任务完成或安全停止。')
            from contextlib import ExitStack
            from ..storage_activity import DataActivity
            ownership=ExitStack()
            ownership.enter_context(DataActivity(self.data))
            try:
                ownership.enter_context(DataActivity(self.data,exclusive=True,purpose='scan-budget'))
                ident = uuid.uuid4().hex
                folder = no_links(self.work/ident); folder.mkdir()
                (folder/'semantics.yaml').write_bytes(Path(profile_path).read_bytes())
                # Preserve the existing adjacent-library contract when the task's
                # config is fixed outside the editable profile directory.
                for name in ('review_context.md','concurrency_cases.md'):
                    source=no_links(Path(profile_path).parent/name)
                    if source.is_file():
                        (folder/name).write_bytes(source.read_bytes())
                value = dict(id=ident, scan_id=ident if mode=='scan' else scan_id, mode=mode,
                             project_id=ws.project_id, project_root=str(root),
                             profile_id=profile_id, state='RUNNING', started=now(),budget_bytes=limits['peak_bytes'],resource_policy=limits,
                             previous_scan_available=any((self.data/'scans').glob('*/manifest.json')),
                             checkpoint_mode='INPUT_VERIFIED_TU_CACHE', samples=[], resources={})
                write_json(folder/'task.json', value)
                budget = ProcessBudget(value['budget_bytes'])
                ownership.callback(budget.close)
                stream = (folder/'console.log').open('wb')
                ownership.callback(stream.close)
                from .resource_policy import temporary_environment
                env = temporary_environment(folder,os.environ); env['PYTHONIOENCODING']='utf-8'
                env['ECRA_DATA_ROOT']=str(self.data)
                env['ECRA_RESOURCE_PRESSURE_FILE']=str(folder/'resource-pressure.json')
                env['ECRA_EXTRACTION_WORKERS']=str(limits['workers'])
                tool = Path(__file__).resolve().parents[2]
                env['PYTHONPATH']=str(tool)+os.pathsep+env.get('PYTHONPATH','')
                args = [sys.executable,'-B','-m','ecra.studio.task_worker', '--config',str(folder/'semantics.yaml'),
                    '--data-root',str(self.data),'--scan-id',value['scan_id'],'--profile-id',profile_id,'--mode',mode,
                    '--gate',str(folder/'start'), '--stop',str(folder/'stop'), '--result',str(folder/'worker-result.json')]
                process = None
                try:
                    process = subprocess.Popen(args, cwd=tool, env=env, stdout=stream, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                    budget.assign(process)
                    (folder/'start').write_text('OWNED',encoding='ascii')
                except BaseException as exc:
                    if process is not None:
                        process.terminate(); process.wait()
                    stream.close(); budget.close()
                    value.update(state='FAILED',error=str(exc),finished=now()); write_json(folder/'task.json',value)
                    raise
                self.active = (ident,process,budget)
                threading.Thread(target=self.monitor,args=(folder,value,process,budget,stream,ownership),daemon=True).start()
                return value
            except BaseException:
                ownership.close()
                self.active=None
                raise

    def monitor(self, folder, value, process, budget, stream,ownership):
        try:
            samples=0
            while process.poll() is None:
                try:
                    value['resources'] = budget.sample()
                    sample = dict(timestamp=now(), **value['resources'])
                    import shutil
                    from ..scan_diagnostics import memory
                    system=memory()
                    sample.update({key:system[key] for key in ('system_commit_bytes','system_commit_limit_bytes',
                        'system_physical_total_bytes','system_physical_available_bytes') if key in system})
                    sample['disk_free_bytes']=shutil.disk_usage(self.data).free
                    value['resources'].update({key:sample[key] for key in sample if key.startswith(('system_','disk_'))})
                    soft=sample.get('private_bytes',0)>=value['resource_policy']['soft_bytes'] or sample.get('system_physical_available_bytes',2**63)<2*1024**3
                    write_json(folder/'resource-pressure.json',dict(parallel_limit=1 if soft else value['resource_policy']['workers']))
                    if soft:value['resource_notice']='达到软阈值：后续TU降至单并行，保留全部事实。'
                    else:value.pop('resource_notice',None)
                    if sample.get('private_bytes',0)>=value['budget_bytes']*.9 or sample.get('system_physical_available_bytes',2**63)<512*1024**2 or sample['disk_free_bytes']<512*1024**2:
                        (folder/'stop').write_text(now(),encoding='ascii')
                        value['error']='接近资源硬阈值，已请求安全停止；保存已验证TU，上一有效快照保留。调整预算或释放空间后恢复。'
                    # Display history is bounded; the full measurements append
                    # to a durable JSONL receipt, never into an evidence cap.
                    with (folder/'resources.jsonl').open('a',encoding='utf-8') as output:
                        output.write(json.dumps(sample)+'\n')
                    value['samples'] = [*value['samples'][-119:], sample]
                    samples+=1
                    if samples % 6 == 0:
                        scan_folder = self.data/'scans'/value['scan_id']
                        size = 0
                        for file in scan_folder.rglob('*'):
                            try:
                                if no_links(file).is_file():
                                    size += file.stat().st_size
                            except FileNotFoundError:
                                pass
                        value['task_disk_bytes'] = size
                    if (folder/'stop').is_file():
                        value['state'] = 'STOP_REQUESTED'
                    write_json(folder/'task.json',value)
                except (OSError, ValueError) as exc:
                    value['monitor_error'] = str(exc)
                threading.Event().wait(.5)
            value.update(exit_code=process.returncode, finished=now())
            published = (self.data/'scans'/value['scan_id']/'manifest.json').is_file()
            result=read_json(folder/'worker-result.json') if (folder/'worker-result.json').is_file() else {}
            if result.get('error'):
                value['error']=result['error']
            value['state'] = 'COMPLETE' if process.returncode in {0,1,2} and published and result.get('operation_completed') else (
                'INTERRUPTED' if process.returncode==130 else 'FAILED')
            value['published'] = published
            write_json(folder/'task.json',value)
        finally:
            ownership.close()
            with self.lock:
                self.active = None

    def detail(self, ident, *, offset=0, limit=65536):
        if type(offset) is not int or offset<0 or not 1<=limit<=65536:
            raise ValueError('日志游标无效')
        folder = self.directory(ident)
        value = read_json(folder/'task.json')
        log = folder/'console.log'
        with log.open('rb') as stream:
            stream.seek(offset)
            raw = stream.read(limit)
        value['log'] = dict(text=raw.decode('utf-8',errors='replace'), offset=offset,
                            next_offset=offset+len(raw), total=log.stat().st_size)
        diagnostics = self.data/'scans'/value['scan_id']/'diagnostics'
        for key, name in [('stages','scan_stages.json'),('failure','exception.json'),('memory','memory_profile.json'),('tu_cache','tu_cache.json'),('progress','scan_progress.json')]:
            path = diagnostics/name
            if path.is_file():
                value[key] = read_json(path)
        return value

    def stop(self, ident):
        with self.lock:
            if self.active is None or self.active[0] != ident:
                raise ValueError('任务已停止或不属于本监督器')
            (self.directory(ident)/'stop').write_text(now(),encoding='ascii')
        return dict(state='STOP_REQUESTED')

    def close(self):
        with self.lock:
            if self.active:
                ident, process, budget = self.active
                (self.directory(ident)/'stop').write_text(now(),encoding='ascii')
        # Server shutdown must not leave compilation/AI subprocesses behind.
        if self.active:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                budget.close()
                if os.name != 'nt':
                    process.terminate()
