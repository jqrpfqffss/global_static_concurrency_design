"""Strict wire parsers for the local OpenCode protocol (never model prose)."""
import json
import re
from pathlib import Path


class ProtocolError(ValueError):
    code = 'protocol_unsupported'


class AuthenticationRequired(ProtocolError):
    code = 'authentication_required'


class VersionOutputError(ProtocolError):
    code = 'version_output_invalid'


def redactor(environment):
    """Build an in-memory scrubber; never serialize credentials or full env."""
    values = set()
    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if re.search(r'key|token|secret|password|access|refresh', key, re.I) and isinstance(item, str):
                    values.add(item)
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    for key, value in environment.items():
        if value and re.search(r'KEY|TOKEN|SECRET|PASSWORD|AUTH', key, re.I):
            values.add(value)
        if key in {'OPENCODE_AUTH_CONTENT', 'OPENCODE_CONFIG_CONTENT'}:
            try:
                collect(json.loads(value))
            except (ValueError, TypeError):
                pass
    for key, name in [('XDG_DATA_HOME', 'opencode/auth.json'), ('XDG_CONFIG_HOME', 'opencode/opencode.json')]:
        if not environment.get(key):
            continue
        path = Path(environment[key])/name
        try:
            if path.is_file() and path.stat().st_size < 2**20:
                collect(json.loads(path.read_text('utf-8-sig')))
        except (OSError, ValueError):
            pass
    def scrub(text):
        for value in sorted(filter(None, values), key=len, reverse=True):
            text = text.replace(value, '<redacted>')
        text = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1<redacted>@', text)
        return re.sub(r'(?i)(bearer\s+)[\w.\-]+', r'\1<redacted>', text)
    return scrub


ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))')
VERSION_LINE = re.compile(r'(?:(?:x?opencode(?:\s+version)?|version)\s*[:=]?\s+)?v?'
                          r'(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)', re.I)
# This banner is supplied by the enterprise distribution. No arbitrary log
# lines, dates, Bun resource versions, or JSON fragments are discarded.
BANNERS = frozenset({'欢迎使用研发工具|xOpenCode'})
LOGIN = re.compile(r'^(?:请输入域账号\s*[:：]|请输入域密码\s*[:：]|Enter domain (?:account|password)\s*:)\s*$', re.I)


def clean(text):
    return ANSI.sub('', text).lstrip('\ufeff')


def interactive_prompt(text):
    return any(LOGIN.fullmatch(line.strip()) for line in clean(text).splitlines())


def protocol_text(text):
    lines = clean(text).splitlines()
    return '\n'.join(line for line in lines if line.strip() not in BANNERS).strip()


def parse_version(stdout, stderr='', returncode=0):
    if interactive_prompt(stdout) or interactive_prompt(stderr):
        raise AuthenticationRequired('OpenCode 要求输入域账号；请通过发行版正式登录入口完成认证，ECRA 不提交账号密码')
    if returncode != 0:
        raise VersionOutputError(f'OpenCode 版本命令非零退出：{returncode}')
    found = set()
    product = 'OpenCode'
    for stream in (stdout, stderr):
        for line in clean(stream).splitlines():
            line = line.strip()
            if not line:
                continue
            if line in BANNERS:
                product = 'xOpenCode'
                continue
            match = VERSION_LINE.fullmatch(line)
            if not match:
                raise VersionOutputError('OpenCode 版本输出含未识别内容；请查看脱敏诊断')
            found.add(match['version'])
            if line.lower().startswith('xopencode'):
                product = 'xOpenCode'
    if len(found) != 1:
        raise VersionOutputError('OpenCode 版本输出缺少唯一版本（缺失或冲突）')
    return product, found.pop()


def unique_json(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ProtocolError('OpenCode JSON 对象含重复字段')
    return obj


def parse_json(text):
    try:
        return json.loads(protocol_text(text), object_pairs_hook=unique_json)
    except (ValueError, RecursionError) as exc:
        raise ProtocolError('OpenCode 未返回完整、唯一的 JSON 文档') from exc


def validate_run(raw):
    """Require an identified completed step, not merely plausible answer text."""
    from .review_opencode_sessions import session_from_jsonl
    sid, _, problem = session_from_jsonl(raw)
    if problem:
        raise ProtocolError(problem)
    events = []
    for line in protocol_text(raw).splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line, object_pairs_hook=unique_json)
        except (ValueError, RecursionError) as exc:
            raise ProtocolError('OpenCode JSONL 含非协议行或截断事件') from exc
        if not isinstance(event, dict) or event.get('type') not in {
                'text', 'tool_use', 'step_start', 'step_finish', 'reasoning', 'error'}:
            raise ProtocolError('OpenCode JSONL 事件类型未验证')
        if event['type'] == 'error':
            from .review import ReviewExecutionError, _provider_error_message
            raise ReviewExecutionError(_provider_error_message(event))
        events.append(event)
    finishes = [e for e in events if e['type'] == 'step_finish']
    if not finishes or finishes[-1]['part'].get('reason') not in {'stop', 'end_turn'}:
        raise ProtocolError('OpenCode 未提供已完成的最终 step_finish，保留会话和原始输出')
    return sid
