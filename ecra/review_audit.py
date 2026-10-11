"""A source-only adversarial second pass. Original answers remain inspectable."""
import hashlib
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .common import digest, execute, read_json, write_json
from .review import (collect_evidence, parse_answer, resolve_command, verify_receipt,
                     validate_investigation, INVESTIGATION_PROMPT)
from .review_contract import CONTRACT_PROMPT, SCHEMA_VERSION
from .review_risk import validate_risk_result
from .review_context import review_context_section


AUDIT_PROMPT = '''对刚才的结论做反证复核。先前答案仅是待证假设，不是事实或验收真值。
只读真实源码与原始证据包，不修改工程，不读取测试真值或其他变量的复核答案。
必须主动寻找使先前结论不成立的路径，不为保持答案一致而辩护：
1. 对安全结论，逐字段枚举所有写入函数，特别核对 Reset/Start/Stop/错误恢复/溢出处理；不能把初始化之后重置队列 head/tail 的函数漏掉，不能在 main 也写 head 时仍套用单生产者单消费者证明。标志的检查和清零之间也可能丢失新事件。
2. 对确认结论，给出实际可成立的存储冲突和最短交错，业务影响另列。RMW 自身就是读取：没有额外业务消费者不能抹去 ++ 丢失更新、union/位域 RMW 覆盖另一字段写入等已经能证明的存储一致性问题；但只能说明实际丢失了什么，业务后果未证实就直说未证实。对齐字节的原子 store/store 或同级中断串行写入，不能仅因最后写入值随顺序不同而确认缺陷；必须另有源码支持的协议/完整更新约束。禁止虚构未来读者或跨字段约束，也禁止把“业务影响未知”直接等同于“已证明安全”。
3. 指针对象与其指向缓冲区分开。有 symbol_id 的变量项，status 必须绑定该对象本体；若指针初始化后从未改写，不能因为指向对象有 RMW 缺陷而把指针本身判 CONFIRMED。下游目标的真实风险另列并保留，不能替代本项证据。无 symbol_id 的缺口项仅复核 uncertainties 中列出的具体访问。指针快照过时本身不等于缺陷；必须证明违反当前已有的读取/所有权约束。无消费者、无生命周期约定时不要臆测帧头、双缓冲所有权、业务协议或未来新增代码。
4. 先确认本项目架构、目标核和调度配置。对同一 Cortex-M 核，main 不能抢占 ISR；IRQ 只有更高抢占优先级才能抢占正在运行的 ISR；同优先级不能相互抢占。不同核及 DMA 硬件可独立运行；本核关中断不自动保护另一个核。其他平台必须依据其实际调度规则，不能照搬 Cortex-M 规则。检查回调实参、过滤条件及 HAL 状态变化，不能让 main 在同核 ISR 尚未返回时开始下一次调用，也不能把被实参分支排除的入口列为真实访问者。
5. 修复建议必须覆盖忙状态和所有写点。例如不能仅把 memset 移到 DMA 启动之前，却在上一次 DMA 仍忙时再次 memset。若没有板上实验，不得写成已验证实测或“必然在某个时刻发生”。
6. 不能由合法源码行号推导整段推理必然正确。每项 claim 必须说明该行具体支持什么；若还需要另一行才能证明 IRQ 使能，应引用使能行，不能把 SetPriority 说成 EnableIRQ。
请自行读取被遗漏函数及调用者，明确修正或维持本项结论。当前证据足够时给 CONFIRMED / REVIEWED_SAFE / FALSE_POSITIVE；无法证明具体风险或安全时给 NEED_MORE_CONTEXT，写出具体缺失条件。不要为了二选一强行下结论。
首轮的静态规则和风险标签都只是待推翻的假设。风险答案须通过证据包里的可成立冲突对与源码引用校验；若静态事实错漏，按首轮相同的 risk_override 字段提供两个实际访问、调度、保护及错误结果的源码证据。不要因原答案是 CONFIRMED/LIKELY 就维持风险。
最终只输出一个与首轮相同字段的 JSON 对象，finding_id 必须保持不变。evidence 每项必须含 file、line、该行连续原文 quote、claim；quote 将逐字验证。reason 首句回答有问题、无问题或证据不足，并说明反证核对后是否修正首轮判断。
evidence.file 必须是已核对的工程相对路径；头文件目录请从源码或 project_evidence_path.source_files 查证，不要根据 .c 路径猜测。
必须包含非空字符串字段 reason、interleaving、protection、impact、fix、verification，以及 evidence 列表和合法 status。finding_id 必须逐字复制本条消息末尾 ID，不得根据上轮回答或记忆改写。
'''


def audit_reviews(root, out, cfg, reviews, progress=print, on_result=None, challenges=None,
                  review_context_path=None):
    folder = out/'review'
    audit_folder = folder/'audit'
    audit_folder.mkdir(parents=True, exist_ok=True)
    settings = cfg['review']
    command = resolve_command(settings.get('command', ['opencode']))

    def process(original):
        if original.get('state') not in {'DONE','FAILED'}:
            return original
        fid = original['finding_id']
        packet = folder/(fid+'.input.json')
        expected_type = ('VARIABLE' if read_json(packet)['finding'].get('symbol_id') else 'EVIDENCE_GAP') if packet.is_file() else None
        requirements = read_json(packet).get('investigation_requirements', []) if packet.is_file() else []
        prompt = (AUDIT_PROMPT + review_context_section(review_context_path)
                  + CONTRACT_PROMPT + INVESTIGATION_PROMPT + '\n本项 ID：' + fid)
        prompt += '\n本项 investigation 必须回答的精确 ID（仅以下清单；调用边、函数、IRQ 和生命周期仍须核查，但不逐 ID 复述）：\n'
        prompt += '\n'.join(r['id'] for r in requirements)
        if expected_type:
            prompt += '\n本项 review_type 必须为 ' + expected_type
        if challenges and fid in challenges:
            prompt += '\n额外待核实问题（这是复核问题，不是事实或指定答案）：\n' + challenges[fid]
        policy_digest = digest([prompt, Path(__file__).with_name('review_contract.py').read_text(encoding='utf-8'),
                                Path(__file__).with_name('review_risk.py').read_text(encoding='utf-8')])
        if original['state'] == 'DONE':
            verify_receipt(root, folder, original)
        audit_key = digest([original.get('execution',{}).get('stdout_sha256'), original.get('cache_key'), policy_digest,
                            settings.get('model'), settings.get('command')])
        cache = audit_folder/(fid+'.result.json')
        if cache.is_file():
            try:
                old = read_json(cache)
                if old.get('audit_key') == audit_key:
                    verify_receipt(root, folder, old)
                    return old
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                pass
        # The same completed audit can be reused by the normal review cache.
        if original.get('state') == 'DONE' and original.get('audit_prompt_digest') == policy_digest:
            return original
        first_log = original.get('execution',{}).get('stdout_file')
        if not first_log:
            attempts=sorted(folder.glob(fid+'.attempt*.jsonl'))
            first_log=attempts[-1].name if attempts else None
        raw = (folder/first_log).read_text(encoding='utf-8') if first_log else ''
        sessions = []
        for line in raw.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event,dict) and event.get('sessionID'):
                sessions.append(event['sessionID'])
        argv = command + ['run', '--agent', 'ecra-review', '--format', 'json']
        if sessions:
            argv += ['--session', sessions[-1]]
        else:
            argv += ['--file', str(packet)]
            prompt += '\n待反证的初稿或执行错误（不能当作证据）：' + json.dumps(original.get('answer',original.get('error')), ensure_ascii=False)
        if settings.get('model'):
            argv += ['--model', settings['model']]
        readable = {'*':'deny', **{ext:'allow' for ext in
            ('*.c','*.h','*.cc','*.cpp','*.cxx','*.hpp','*.hh','*.hxx','*.s','*.S','*.inc','*.ld','*.cmake','*CMakeLists.txt','*.ioc')}}
        for path in (packet, folder/'project-evidence.json', out/'facts.json'):
            readable[str(path)] = readable[path.as_posix()] = 'allow'
        permissions = {'*':'deny', 'read':readable}
        env = dict(os.environ, OPENCODE_PERMISSION=json.dumps(permissions),
            OPENCODE_CONFIG_CONTENT=json.dumps(dict(permission=permissions, share='disabled',
                agent={'ecra-review':dict(description='Read-only concurrency evidence reviewer',mode='primary',permission=permissions)})))
        progress('OpenCode 反证复核：' + fid)
        result = dict(original, state='FAILED', status=None, audit_key=audit_key)
        result.pop('answer', None)
        result.pop('cached', None)
        result['previous_reviews'] = original.get('previous_reviews',[]) + [dict(original)]
        result['attempts'] = list(original.get('attempts', []))
        for attempt in range(int(settings.get('retries',1))+1):
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
            name = f'{fid}.audit-{stamp}-{attempt}'
            started = datetime.now(timezone.utc).isoformat()
            record = dict(number=attempt, stage='audit', started=started, prompt_file=name+'.prompt.txt',
                          packet_file=packet.name, stdout_file=name+'.jsonl', stderr_file=name+'.stderr.txt',
                          model=settings.get('model','OpenCode configured default'))
            result['attempts'].append(record)
            result['execution'] = dict(started=started, attempt=attempt, model=record['model'],
                prompt_file=record['prompt_file'], packet_file=packet.name,
                stdout_file=record['stdout_file'], stderr_file=record['stderr_file'])
            write_json(cache,result)
            try:
                (folder/(name+'.prompt.txt')).write_text(prompt,encoding='utf-8')
                (folder/(name+'.jsonl')).write_text('',encoding='utf-8')
                (folder/(name+'.stderr.txt')).write_text('',encoding='utf-8')
                proc = execute(argv+['--',prompt],cwd=root,env=env,timeout=settings.get('timeout_seconds',300))
                (folder/(name+'.jsonl')).write_text(proc.stdout,encoding='utf-8')
                (folder/(name+'.stderr.txt')).write_text(proc.stderr,encoding='utf-8')
                if proc.returncode:
                    record['returncode'] = proc.returncode
                    raise ValueError(f'OpenCode audit exit={proc.returncode}: {proc.stderr[-500:]}')
                answer = parse_answer(proc.stdout,fid,root,require_quotes=True,require_schema=True,expected_type=expected_type)
                validate_investigation(answer, requirements)
                if packet.is_file():
                    validate_risk_result(answer, read_json(packet))
                result.update(state='DONE',status=answer['status'],answer=answer,
                    source_evidence=collect_evidence(root,answer), audit_prompt_digest=policy_digest,
                    execution=dict(started=started,finished=datetime.now(timezone.utc).isoformat(),
                        command=argv, model=settings.get('model','OpenCode configured default'),exit_code=0,
                        schema_version=SCHEMA_VERSION, review_type=answer['review_type'],
                        packet_file=packet.name if packet.is_file() else None,
                        packet_sha256=hashlib.sha256(packet.read_bytes()).hexdigest() if packet.is_file() else None,
                        stdout_file=name+'.jsonl',stderr_file=name+'.stderr.txt',
                        prompt_file=name+'.prompt.txt',prompt_sha256=hashlib.sha256((folder/(name+'.prompt.txt')).read_bytes()).hexdigest(),
                        stdout_sha256=hashlib.sha256((folder/(name+'.jsonl')).read_bytes()).hexdigest(),
                        stderr_sha256=hashlib.sha256((folder/(name+'.stderr.txt')).read_bytes()).hexdigest(),
                        evidence_validation='OpenCode 反证复核；原文与日志一致性校验，不等于硬件实测'))
                result.pop('error',None)
                record.update(state='DONE', finished=result['execution']['finished'], returncode=0,
                              stdout_sha256=result['execution']['stdout_sha256'])
                break
            except Exception as exc:
                invalid_config = 'Configuration is invalid at ' in str(exc)
                timed_out = isinstance(exc, TimeoutError) or type(exc).__name__ == 'TimeoutExpired'
                message = (f'OpenCode 反证调用超过 {settings.get("timeout_seconds", 300)} 秒'
                           if timed_out else str(exc))
                for stream,suffix in (('stdout','.jsonl'),('stderr','.stderr.txt')):
                    data=getattr(exc,stream,None)
                    if data:
                        (folder/(name+suffix)).write_text(data.decode('utf-8','replace') if isinstance(data,bytes) else data,encoding='utf-8')
                result.update(error=f'反证复核未通过：{type(exc).__name__}: {message[:1000]}',
                              error_type=type(exc).__name__, failure_stage='audit')
                record.update(state='FAILED', finished=datetime.now(timezone.utc).isoformat(),
                              error_type=type(exc).__name__, error_message=message,
                              timeout=timed_out)
                if invalid_config:
                    result.update(error_type='OpenCodeConfigurationError', failure_stage='configuration')
                    record['error_type'] = 'OpenCodeConfigurationError'
                result['execution'].update(finished=record['finished'],
                    returncode=record.get('returncode'), timeout=record['timeout'])
                for stream in ('stdout', 'stderr'):
                    log = folder/record[stream+'_file']
                    if log.is_file():
                        record[stream+'_sha256'] = hashlib.sha256(log.read_bytes()).hexdigest()
                write_json(cache,result)
                prompt += ('\n上次返回未通过校验，请纠正：' + result['error']
                           + '\n重新核对所有反证；候选不成立应给 REVIEWED_SAFE/FALSE_POSITIVE，'
                             '证据不足给 NEED_MORE_CONTEXT。不得为维持风险结论编造 risk_override。')
                if invalid_config:
                    break
        write_json(cache,result)
        return result

    results=[]
    def process_safely(original):
        try:
            return process(original)
        except Exception as exc:
            result = dict(original, state='FAILED', status=None,
                          error=f'反证复核准备失败：{type(exc).__name__}: {str(exc)[:1000]}',
                          error_type=type(exc).__name__, failure_stage='audit_prepare',
                          previous_reviews=original.get('previous_reviews', [])+[dict(original)])
            result.pop('answer', None)
            result.pop('cached', None)
            write_json(audit_folder/(original['finding_id']+'.result.json'),result)
            return result
    batch_size = settings.get('max_items', 0) or len(reviews) or 1
    batch_count = (len(reviews) + batch_size - 1) // batch_size
    for start in range(0, len(reviews), batch_size):
        batch = reviews[start:start + batch_size]
        number = start // batch_size + 1
        progress(f'OpenCode 反证复核：当前批次 {number}/{batch_count}，本批 {len(batch)} 项，已完成 {len(results)}/{len(reviews)}')
        if len(batch) == 1 or int(settings.get('workers',1)) == 1:
            for row in batch:
                results.append(process_safely(row))
                if on_result:
                    on_result(results)
        else:
            executor=ThreadPoolExecutor(max_workers=min(int(settings.get('workers',1)), len(batch)))
            try:
                futures=[executor.submit(process_safely,r) for r in batch]
                for future in as_completed(futures):
                    results.append(future.result())
                    if on_result:
                        on_result(results)
            finally:
                executor.shutdown(wait=True,cancel_futures=True)
        progress(f'OpenCode 反证批次 {number}/{batch_count} 完成，累计完成 {len(results)}/{len(reviews)}'
                 + ('，自动进入下一批' if number < batch_count else ''))
    mapping={r['finding_id']:r for r in results}
    return [mapping[r['finding_id']] for r in reviews]
