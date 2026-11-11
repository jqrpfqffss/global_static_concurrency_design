"""Persistent real scan tasks. One process tree owns the shared scan budget."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

from ..common import write_json, read_json
from ..resource_control import EVENT_LOG, PRESSURE_FILE, PRESSURE_NAME
from ..scan_diagnostics import diagnostic_log
from ..workspace import no_links
from ..report_package import IDENTITY
from .process_budget import ProcessBudget
from .task_records import display_record


def now():
    return datetime.now(timezone.utc).isoformat()


def read_task_json(path):
    """Brief Windows replacement/sharing races, never a stale-data fallback."""
    path = no_links(path)
    for attempt in range(5):
        try:
            return read_json(path)
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(.02 * (attempt + 1))


def supervisor_log(folder, message):
    try:
        with (folder/'supervisor.log').open('a', encoding='utf-8') as output:
            output.write(f'{now()} {message}\n')
    except OSError as exc:
        diagnostic_log(f'{folder}：{message}\n监督器日志写入失败：{exc}')


def terminate_owned(process, budget):
    if os.name == 'nt':
        budget.close()  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    elif process.poll() is None:
        process.terminate()


def resource_sample(budget, data):
    from ..scan_diagnostics import memory
    sample = dict(timestamp=now())
    errors = {}
    try:
        sample.update(budget.sample())
    except (OSError, ValueError) as exc:
        errors['job'] = str(exc)
    try:
        sample.update({key: value for key, value in memory().items() if key.startswith('system_')})
    except (OSError, ValueError) as exc:
        errors['host'] = str(exc)
    try:
        sample['disk_free_bytes'] = shutil.disk_usage(data).free
    except (OSError, ValueError) as exc:
        errors['disk'] = str(exc)
    if errors:
        sample['sample_errors'] = errors
    return sample


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
                    value = self.record(path)
                    if value['state'] in {'RUNNING', 'STOP_REQUESTED'}:
                        value.update(state='INTERRUPTED', finished=now(), error='上次监督器退出；保留完整 TU 缓存与诊断，可重新校验输入后恢复。')
                        write_json(path, value)
            finally:lease.__exit__(None,None,None)

    def list(self):
        return sorted((self.record(path) for path in self.work.glob('*/task.json')),
                      key=lambda item:item['started'], reverse=True)

    def record(self, path):
        return display_record(path, read_task_json, ident=path.parent.name,
            states={'RUNNING','STOP_REQUESTED','COMPLETE','FAILED','INTERRUPTED'},
            validate=lambda value:isinstance(value.get('mode'),str)
                and value['mode'] in {'scan','precheck','review','review-failed','multicore'}
                and isinstance(value.get('scan_id'),str) and IDENTITY.fullmatch(value['scan_id']),
            action='请保留此文件供排查；从已保存工程配置重新发起任务，或打开历史中的有效扫描。')

    def directory(self, ident):
        if not IDENTITY.fullmatch(ident):
            raise ValueError('任务身份无效')
        folder = no_links(self.work/ident)
        if not (folder/'task.json').is_file():
            raise ValueError('任务不存在')
        return folder

    def start(self, profile_path, *, profile_id, mode='scan', scan_id=None, resources=None,
              multicore=None, retry_from=None, expected_revision=None, request_id=None):
        from ..config import load_config, configured_project_root
        from ..workspace import formal_workspace
        from ..data_transfer import relocated_task_config
        raw = Path(profile_path).read_bytes()
        if expected_revision is not None and hashlib.sha256(raw).hexdigest() != expected_revision:
            from ..human_reviews import ReviewConflict
            raise ReviewConflict('配置已变化；请重新选择后扫描')
        if request_id is not None and (mode not in {'scan','precheck'} or not isinstance(request_id,str)
                                       or not re.fullmatch(r'[0-9a-f]{32}',request_id)):
            raise ValueError('任务请求编号无效')
        execution_config,relocation=relocated_task_config(self.data,profile_path,raw)
        root = configured_project_root(profile_path)
        cfg, _ = load_config(root, profile_path)
        if relocation:cfg['analysis']['output']=dict(location='user')
        from .resource_policy import policy
        limits=policy(resources,configured_workers=cfg['analysis'].get('extraction_workers'))
        from .resource_policy import host_pressure
        from ..scan_diagnostics import memory
        pressure=host_pressure(memory())
        if pressure['stop']:raise ValueError(pressure['reason']+'；暂不启动扫描，请待提交额度/内存恢复后重试。')
        if mode not in {'scan','precheck','review','review-failed','multicore'}:
            raise ValueError('未知任务模式')
        if retry_from is not None:
            previous=self.directory(retry_from);previous_task=read_task_json(previous/'task.json')
            if (no_links(profile_path)!=previous/'semantics.yaml' or previous_task.get('state') not in {'FAILED','INTERRUPTED'}
                    or previous_task.get('mode')!=mode or previous_task.get('profile_id')!=profile_id):
                raise ValueError('恢复配置、模式或状态与原任务不符')
        if mode=='multicore':
            if (not isinstance(multicore,dict) or multicore.get('format')!='ECRA_MULTICORE_PLAN_V1'
                    or not isinstance(multicore.get('id'),str) or not IDENTITY.fullmatch(multicore['id'])
                    or not isinstance(multicore.get('inputs'),list) or len(multicore['inputs'])<2):
                raise ValueError('多核派生任务须先固定全部归档配置、扫描和ELF输入')
            plan_folder=no_links(self.data/'work/multicore-plans'/multicore['id'])
            for index,item in enumerate(multicore['inputs']):
                if not isinstance(item,dict) or not isinstance(item.get('elf_id'),str) or not IDENTITY.fullmatch(item['elf_id']):
                    raise ValueError('多核ELF上传身份无效')
                if no_links(item['config'])!=plan_folder/'inputs'/str(index)/'config.yaml':
                    raise ValueError('多核归档配置越出受控输入计划')
                if no_links(item['elf'])!=no_links(self.data/'work/multicore-elfs'/item['elf_id']/'firmware.elf'):
                    raise ValueError('多核ELF越出已上传输入目录')
            if no_links(profile_path)!=no_links(multicore['inputs'][0]['config']):
                # A retry uses the task's byte-identical primary config copy.
                from ..report_package import sha256
                if sha256(profile_path)!=multicore['inputs'][0]['config_sha256']:
                    raise ValueError('多核主配置与固定输入计划不符')
        # Derived combinations read already selected archives and never build.
        # Their original config output setting does not select the destination.
        analysis = dict(output=dict(location='custom',custom_dir=str(self.data))) if mode=='multicore' else dict(cfg['analysis'])
        if analysis.get('output', {}).get('location', 'user') == 'user':
            analysis['output'] = dict(location='custom', custom_dir=str(self.data))
        ws = formal_workspace(root, analysis)
        if Path(ws.workspace_root) != self.data:
            raise ValueError('配置的数据根与当前 Studio 不同；请在配置中使用 output.location: user，或从该数据根启动 Studio。')
        if mode not in {'scan','precheck','multicore'}:
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
                from ..storage_policy import snapshot as storage_snapshot
                fixed_storage=storage_snapshot(self.data)
                write_json(folder/'storage-policy.json',fixed_storage)
                (folder/'semantics.yaml').write_bytes(execution_config)
                if retry_from is not None:
                    write_json(folder/'retry-source.json',dict(source_task=retry_from))
                if mode=='multicore':write_json(folder/'multicore.json',multicore)
                # Native scan and manual/retry review all consume adjacent task
                # documents. Resolve the profile/default sources before freezing.
                from .review_materials import stage_for_task
                materials=stage_for_task(profile_path,folder,mode,cfg,retry=retry_from is not None)
                from ..report_package import sha256
                value = dict(id=ident, scan_id=ident if mode in {'scan','precheck','multicore'} else scan_id, mode=mode,
                             project_id=ws.project_id, project_root=str(root),
                             profile_id=profile_id, profile_revision=sha256(folder/'semantics.yaml'), state='RUNNING', started=now(),budget_bytes=limits['peak_bytes'],resource_policy=limits,
                             build_mode='cmake' if 'cmake' in cfg['analysis'] else 'database',
                             previous_scan_available=any((self.data/'scans').glob('*/manifest.json')),
                             checkpoint_mode='INPUT_VERIFIED_TU_CACHE',storage_policy=fixed_storage, samples=[], resources={})
                if relocation:value['data_relocation']=relocation
                if request_id is not None:value['request_id']=request_id
                value['review_materials']=materials
                if retry_from is not None:value['retry_from']=retry_from
                write_json(folder/'task.json', value)
                if mode=='multicore':
                    value['checkpoint_mode']='RETRY_DERIVATION_FROM_FIXED_INPUTS'
                    write_json(folder/'task.json',value)
                elif mode in {'review','review-failed'}:
                    value['checkpoint_mode']='REVALIDATE_INPUTS_AND_RETRY_REVIEW_MODE'
                    write_json(folder/'task.json',value)
                try:
                    pressure_file = folder/PRESSURE_NAME
                    try:
                        # Start conservatively until the first process-tree and disk sample.
                        write_json(pressure_file, dict(parallel_limit=1))
                    except OSError as exc:
                        raise ValueError(f'资源调度信息初始化失败，扫描未启动。{pressure_file}：{exc}') from exc
                    budget = ProcessBudget(value['budget_bytes'])
                    ownership.callback(budget.close)
                    stream = ownership.enter_context((folder/'console.log').open('wb'))
                    if materials['status']=='FROZEN':
                        for name,record in materials['documents'].items():
                            stream.write(('复核资料已冻结：'+name+' · '+str(record['bytes'])+' 字节 · SHA-256 '+record['sha256']+'\n').encode('utf-8'))
                        stream.flush()
                    from .resource_policy import temporary_environment
                    env = temporary_environment(folder,os.environ); env['PYTHONIOENCODING']='utf-8'
                    if not env.get('PYTHONHASHSEED'):
                        env['PYTHONHASHSEED']='0'
                    env['ECRA_DATA_ROOT']=str(self.data)
                    env[PRESSURE_FILE]=str(pressure_file)
                    env['ECRA_EXTRACTION_WORKERS']=str(limits['workers'])
                    tool = Path(__file__).resolve().parents[2]
                    env['PYTHONPATH']=str(tool)+os.pathsep+env.get('PYTHONPATH','')
                    args = [sys.executable,'-B','-m','ecra.studio.task_worker', '--config',str(folder/'semantics.yaml'),
                        '--data-root',str(self.data),'--scan-id',value['scan_id'],'--profile-id',profile_id,'--mode',mode,
                        '--gate',str(folder/'start'), '--stop',str(folder/'stop'), '--result',str(folder/'worker-result.json')]
                    assigned = False

                    def release_process():
                        try:
                            if process.poll() is None:
                                if assigned:
                                    terminate_owned(process, budget)
                                else:
                                    process.terminate()
                                process.wait(timeout=10)
                        finally:
                            if hasattr(process, 'close'):
                                process.close()

                    if os.name=='nt':
                        from .write_guard import OwnedProcess
                        process=OwnedProcess(args,cwd=tool,env=env,log=stream)
                    else:
                        process=subprocess.Popen(args,cwd=tool,env=env,stdout=stream,stderr=subprocess.STDOUT)
                    ownership.callback(release_process)
                    budget.assign(process)
                    assigned = True
                    if os.name=='nt':
                        process.resume()
                    (folder/'start').write_text('OWNED',encoding='ascii')
                    self.active = (ident,process,budget)
                    threading.Thread(target=self.monitor,args=(folder,value,process,budget,stream,ownership),daemon=True).start()
                except BaseException as exc:
                    value.update(state='FAILED',error=str(exc),finished=now(),published=False)
                    supervisor_log(folder, f'任务启动失败：{exc!r}；原始原因：{exc.__cause__!r}')
                    try:
                        write_json(folder/'task.json',value)
                    except OSError as error:
                        supervisor_log(folder, f'无法保存失败任务状态：{error}')
                    raise
                return value
            except BaseException:
                try:
                    ownership.close()
                except (OSError, subprocess.TimeoutExpired) as error:
                    diagnostic_log(f'任务启动资源回收失败：{error}')
                finally:
                    self.active=None
                raise

    def monitor(self, folder, value, process, budget, stream,ownership):
        from .resource_policy import host_pressure
        stop_file = folder/'stop'
        try:
            samples=0
            while process.poll() is None:
                sample = resource_sample(budget, self.data)
                pressure = sample['host_pressure'] = host_pressure(sample)
                value['resources'] = {key: item for key, item in sample.items() if key != 'timestamp'}
                soft = sample.get('private_bytes', 0) >= value['resource_policy']['soft_bytes'] or pressure['soft']
                reasons = []
                if sample.get('private_bytes', 0) >= value['budget_bytes']*.9:
                    reasons.append('任务进程树接近提交预算硬阈值')
                if pressure['stop']:
                    reasons.append(pressure['reason'])
                if sample.get('disk_free_bytes', float('inf')) < 512*1024**2:
                    reasons.append('工作盘可用空间低于 512 MiB')
                stop_failed = False
                if reasons and value['state'] != 'STOP_REQUESTED':
                    reason = '；'.join(reasons)
                    try:
                        requested = not stop_file.is_file()
                        if requested:
                            stop_file.write_text(now(), encoding='ascii')
                    except OSError as exc:
                        stop_failed = True
                        sample['stop_write_error'] = str(exc)
                        value['error'] = f'{reason}。停止信号写入失败，监督器将结束所属任务进程。{exc}'
                        supervisor_log(folder, value['error'])
                        try:
                            with self.lock:
                                terminate_owned(process, budget)
                        except OSError as error:
                            supervisor_log(folder, f'结束所属任务进程失败：{error}')
                    else:
                        value['state'] = 'STOP_REQUESTED'
                        if requested:
                            value['error'] = reason+'。已请求安全停止，已保存的数据和上一份有效扫描保留。'
                            supervisor_log(folder, value['error'])

                try:
                    write_json(folder/PRESSURE_NAME, dict(parallel_limit=1 if soft or 'sample_errors' in sample else value['resource_policy']['workers']))
                except OSError as exc:
                    message = f'资源调度信息发布失败。{folder/PRESSURE_NAME}：{exc}'
                    if value.get('pressure_publish_error') != message:
                        supervisor_log(folder, message)
                    value['pressure_publish_error'] = sample['pressure_publish_error'] = message
                    value.pop('resource_notice', None)
                else:
                    value.pop('pressure_publish_error', None)
                    if soft:
                        value['resource_notice'] = (pressure['reason'] or '达到软阈值')+'；后续 TU 降至单并行。'
                    else:
                        value.pop('resource_notice', None)

                try:
                    # Display history is bounded; the full measurements append
                    # to a durable JSONL receipt, never into an evidence cap.
                    with (folder/'resources.jsonl').open('a',encoding='utf-8') as output:
                        output.write(json.dumps(sample)+'\n')
                except OSError as exc:
                    supervisor_log(folder, f'资源采样写入失败：{exc}')
                try:
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
                    if not stop_failed and stop_file.is_file():
                        value['state'] = 'STOP_REQUESTED'
                    write_json(folder/'task.json',value)
                except (OSError, ValueError) as exc:
                    value['monitor_error'] = str(exc)
                    supervisor_log(folder, f'任务资源状态写入失败：{exc}')
                threading.Event().wait(.5)
            value.update(exit_code=process.returncode, finished=now())
            published = (self.data/'scans'/value['scan_id']/'manifest.json').is_file()
            try:
                result=read_task_json(folder/'worker-result.json') if (folder/'worker-result.json').is_file() else {}
                if (not isinstance(result,dict) or type(result.get('exit_code')) is not int or result['exit_code'] != process.returncode
                        or type(result.get('operation_completed')) is not bool
                        or (result['operation_completed'] and result.get('error'))):
                    raise ValueError('工作进程完成收据缺失、字段无效或退出状态不一致')
                if result.get('error'):
                    value['error']=result['error']
                checked = False
                if value['mode']=='precheck' and (folder/'preflight/preflight.json').is_file():
                    preflight=read_task_json(folder/'preflight/preflight.json')
                    if not isinstance(preflight,dict) or type(preflight.get('passed')) is not bool:
                        raise ValueError('编译输入检查收据字段无效')
                    checked=preflight['passed']
                value['state'] = 'COMPLETE' if process.returncode in {0,1,2} and (checked if value['mode']=='precheck' else published) and result['operation_completed'] else (
                    'INTERRUPTED' if process.returncode==130 else 'FAILED')
            except (OSError,ValueError,TypeError) as exc:
                value['state']='INTERRUPTED' if process.returncode==130 else 'FAILED'
                receipt_error='任务已退出，但完成状态未能校验：'+str(exc)+'。原收据、日志与已发布结果保留；请查看本任务日志。'
                value['error']=' '.join(filter(None, (value.get('error'), receipt_error)))
            if value['state']=='INTERRUPTED' and not value.get('error') and (folder/'stop').is_file():
                value['error']='任务已响应安全停止请求。'
            value['published'] = published
            try:
                write_json(folder/'task.json',value)
            except OSError as exc:
                supervisor_log(folder, f'任务最终状态写入失败：{exc}。实际退出状态：{value}')
        finally:
            with self.lock:
                try:
                    ownership.close()
                except (OSError, subprocess.TimeoutExpired) as exc:
                    supervisor_log(folder, f'任务资源回收失败：{exc}')
                finally:
                    self.active = None

    def detail(self, ident, *, offset=0, limit=65536):
        if type(offset) is not int or offset<0 or not 1<=limit<=65536:
            raise ValueError('日志游标无效')
        folder = self.directory(ident)
        value = self.record(folder/'task.json')
        if value.get('metadata_error'):
            value['log']=dict(text='',offset=0,next_offset=0,total=0)
            return value

        def diagnostic(path,kind=dict):
            try:
                result=read_task_json(path)
                if not isinstance(result,kind):raise ValueError('诊断字段结构无效')
                return result
            except (OSError,ValueError,TypeError) as exc:
                value.setdefault('diagnostic_errors',[]).append('任务诊断无法读取：'+str(path)+'。'+str(exc)+'；原文件保留，请结合任务状态与日志排查。')
                return None

        if (folder/'reused-working-inputs.json').is_file():
            reused=diagnostic(folder/'reused-working-inputs.json')
            if reused is not None:
                if 'source_task' in reused and 'proof' in reused:
                    value['reused_working_inputs']=dict(source_task=reused['source_task'],proof=reused['proof'])
                else:value.setdefault('diagnostic_errors',[]).append('复用输入诊断缺少来源任务或校验证据；请核对 '+str(folder/'reused-working-inputs.json'))
        log = folder/'console.log'
        try:
            with log.open('rb') as stream:
                stream.seek(offset)
                raw = stream.read(limit)
            value['log'] = dict(text=raw.decode('utf-8',errors='replace'), offset=offset,
                                next_offset=offset+len(raw), total=log.stat().st_size)
        except OSError as exc:
            value['log']=dict(text='',offset=offset,next_offset=offset,total=offset,
                error='任务日志无法读取：'+str(log)+'。'+str(exc)+'；任务状态与原文件保留。')
        diagnostics = self.data/'scans'/value['scan_id']/'diagnostics'
        value['progress_kind']='TU_EXTRACTION'
        if value['mode'] in {'review','review-failed'}:
            diagnostics=folder/'review-diagnostics'
            value['progress_kind']='AI_REVIEW'
        if value['mode'] in {'scan','precheck'} and not diagnostics.exists() and (folder/'fixed-inputs/diagnostics').is_dir():
            diagnostics=folder/'fixed-inputs/diagnostics'
            value['progress_kind']='WORKING_INPUT_INVENTORY'
        if value['mode']=='multicore':diagnostics=folder/'multicore-diagnostics'
        preflight = folder/'preflight/preflight.json'
        preflight_diagnostics = preflight.parent/'diagnostics'
        fixed_diagnostics = folder/'fixed-inputs/diagnostics'
        if value['mode'] in {'scan','precheck'} and preflight.is_file():
            check=diagnostic(preflight)
            if check is not None:value['preflight']=check
            if value['mode']=='precheck' or value['progress_kind']=='WORKING_INPUT_INVENTORY' or not diagnostics.exists():
                diagnostics=preflight_diagnostics
                value['progress_kind']='COMPILE_INPUT_PRECHECK'
        stage_folders = [diagnostics]
        if value['mode'] in {'scan','precheck'}:
            stage_folders = list(dict.fromkeys([fixed_diagnostics, preflight_diagnostics, diagnostics]))
        for stage_folder in stage_folders:
            path = stage_folder/'scan_stages.json'
            if path.is_file():
                stages = diagnostic(path,list)
                if stages is not None:value.setdefault('stages',[]).extend(stages)
        for key, name in [('failure','exception.json'),('memory','memory_profile.json'),('tu_cache','tu_cache.json'),('progress','scan_progress.json')]:
            path = diagnostics/name
            if path.is_file():
                result=diagnostic(path)
                if result is not None:value[key]=result
        if value['mode'] == 'scan' and (diagnostics/EVENT_LOG).is_file():
            try:
                with (diagnostics/EVENT_LOG).open('rb') as stream:
                    offset = max(0, stream.seek(0, os.SEEK_END) - 65536)
                    stream.seek(offset)
                    if offset:
                        stream.readline()  # discard a possibly partial first record
                    complete = stream.read().rpartition(b'\n')[0]
                if complete:
                    control = json.loads(complete.rsplit(b'\n', 1)[-1])
                    if not isinstance(control, dict):
                        raise ValueError('资源调度诊断字段结构无效')
                    value['resource_control'] = control
            except (OSError, ValueError) as exc:
                value.setdefault('diagnostic_errors', []).append(f'无法读取资源调度诊断：{exc}。请查看任务日志。')
        if (value.get('failure') or {}).get('resource_control'):
            value['resource_control'] = value['failure']['resource_control']
        return value

    def stop(self, ident):
        with self.lock:
            if self.active is None or self.active[0] != ident:
                raise ValueError('任务已停止或不属于本监督器')
            folder = self.directory(ident)
            try:
                (folder/'stop').write_text(now(), encoding='ascii')
            except OSError as exc:
                message = f'用户请求停止，停止信号写入失败。{exc}'
                supervisor_log(folder, message)
                _, process, budget = self.active
                try:
                    terminate_owned(process, budget)
                except OSError as error:
                    supervisor_log(folder, f'结束所属任务进程失败：{error}')
                raise ValueError(message+' 请查看任务状态与日志。') from exc
        return dict(state='STOP_REQUESTED')

    def close(self):
        with self.lock:
            if not self.active:
                return
            ident, process, budget = self.active
            folder = self.directory(ident)
            try:
                (folder/'stop').write_text(now(), encoding='ascii')
            except OSError as exc:
                supervisor_log(folder, f'监督器退出时停止信号写入失败：{exc}')
            # Hold the process handle until shutdown has stopped the task.
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                terminate_owned(process, budget)
