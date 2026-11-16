"""Tool-local startup preferences with relative, relocation-safe selections."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from contextlib import contextmanager


class PreferenceError(ValueError):
    pass


class PreferenceConflict(ValueError):
    pass


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def preference_home():
    from .workspace import control_path
    return control_path('preferences')


def legacy_home():
    if os.name == 'nt':
        value = os.environ.get('LOCALAPPDATA')
        return Path(value)/'ECRAStudio' if value and Path(value).is_absolute() else None
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'ECRAStudio'


def read_preferences():
    from .workspace import managed_root, no_links, studio_data_root
    file = no_links(preference_home()/'preferences.json')
    if not file.exists():
        old = legacy_home()
        if old is None or not (old/'preferences.json').is_file():
            return dict(revision='missing', status='MISSING', selected=None, error=None, payload=None, raw=None)
        file = no_links(old/'preferences.json')  # Previous selections are read-only.
    if file.stat().st_size > 1024*1024:
        raise PreferenceError('启动设置超过1MiB；请保留原件并从明确数据目录启动恢复：'+str(file))
    raw = file.read_bytes()
    result = dict(revision=_hash(raw), status='INVALID', selected=None, error=None, payload=None, raw=raw)
    try:
        payload = json.loads(raw.decode('utf-8'))
        if (not isinstance(payload, dict) or payload.get('format') != 'ECRA_STUDIO_PREFERENCES'
                or type(payload.get('version')) is not int or payload['version'] != 1):
            raise ValueError('启动设置协议不支持')
        if 'workspace_relative' in payload:
            value = payload['workspace_relative']
            if not isinstance(value, str) or Path(value).anchor or '..' in Path(value).parts:
                raise ValueError('相对工具数据目录无效')
            target = managed_root()/value
        else:
            target = payload.get('data_root')
            if not isinstance(target, str) or not Path(target).is_absolute():
                raise ValueError('已保存的数据目录不是绝对路径')
        selected = studio_data_root(target)
        if not selected.is_dir():
            raise ValueError(f'已保存数据目录不存在: {selected}；请核对解压或迁移位置')
        result.update(status='VALID', selected=str(selected), payload=payload)
    except (ValueError, OSError, UnicodeError) as exc:
        result['error'] = '无法使用已保存的启动设置：'+str(exc)+'；原件保留于 '+str(file)
    return result


def preferred_data_root(default):
    state = read_preferences()
    if state['status'] == 'INVALID':
        raise PreferenceError(state['error'])
    return Path(state['selected']) if state['selected'] else default


def startup_selection(explicit=None):
    """Reuse the workspace resolver; only a bad saved default enters recovery."""
    from .workspace import studio_data_root, default_user_data_root
    if explicit is not None:
        if os.environ.get('ECRA_DATA_ROOT'):
            studio_data_root(os.environ['ECRA_DATA_ROOT'], label='ECRA_DATA_ROOT')
        return dict(root=studio_data_root(explicit, label='--data-root'), source='STARTUP_ARGUMENT', warning=None)
    if os.environ.get('ECRA_DATA_ROOT'):
        return dict(root=studio_data_root(), source='ENVIRONMENT', warning=None)
    try:
        state = read_preferences()
        if state['status'] == 'INVALID':
            raise PreferenceError(state['error'])
        if state['selected']:
            return dict(root=studio_data_root(state['selected']), source='GUI_DEFAULT', warning=None)
    except PreferenceError as exc:
        return dict(root=studio_data_root(default_user_data_root()), source='RECOVERY_DEFAULT',
                    warning=str(exc)+'。正在使用工具内 workspace；可在设置页修复，旧数据可进行只读迁移。')
    return dict(root=studio_data_root(default_user_data_root()), source='TOOL_DEFAULT', warning=None)


def status(current, source, warning=None):
    state = read_preferences()
    return dict(current_root=str(current), source=source, startup_warning=warning,
                selected_root=state['selected'], revision=state['revision'], preference_status=state['status'],
                error=state['error'], preference_file=str(preference_home()/'preferences.json'),
                precedence='启动参数 > ECRA_DATA_ROOT > GUI保存的默认值 > 工具目录内 workspace',
                explicit_override=source in {'STARTUP_ARGUMENT', 'ENVIRONMENT'})


def _target(path, current):
    from .workspace import managed_root, no_links, studio_data_root
    from .config import configured_project_root
    if not isinstance(path, str) or not path or not Path(path).is_absolute():
        raise ValueError('请选择工具 workspace 内的数据根绝对路径')
    target = studio_data_root(path)
    current = no_links(current)
    projects = no_links(current/'projects')
    if projects.exists():
        for profile in projects.glob('*/profiles/*.yaml'):
            firmware = configured_project_root(no_links(profile)).resolve()
            if target == firmware or target.is_relative_to(firmware) or firmware.is_relative_to(target):
                raise ValueError('数据目录与已登记固件目录重叠：'+str(firmware))
    if target.exists() and not target.is_dir():
        raise ValueError('数据目录路径已被普通文件占用')
    if not Path(target.anchor).exists():
        raise ValueError('目标磁盘当前不可用')
    marker = no_links(target/'settings/device.json')
    if marker.is_file():
        if marker.stat().st_size > 4096:
            raise ValueError('目标Studio设备声明过大；请核对原目录')
        raw = marker.read_bytes()
        device = json.loads(raw.decode('utf-8'))
        if not isinstance(device, dict) or not isinstance(device.get('device'), str) or not device['device'].startswith('device-'):
            raise ValueError('目标Studio设备声明损坏；请保留原件')
        kind, marker_hash = 'REGISTERED', _hash(raw)
    else:
        if target.exists():
            infrastructure = {'.ecra', 'a', 'data-roots'} if target == managed_root() else set()
            if any(path.name not in infrastructure for path in target.iterdir()):
                raise ValueError(f'目标非空且未登记为 Studio 数据根: {target}；已有结果可从数据与共享迁移')
        kind, marker_hash = 'EMPTY', None
    existing = target
    while not existing.exists():
        existing = existing.parent
    stat = existing.stat()
    binding = dict(path=str(target), kind=kind, existing_parent=str(existing),
                   device=stat.st_dev, inode=stat.st_ino, marker_sha256=marker_hash)
    plan = _hash(json.dumps(binding, sort_keys=True, ensure_ascii=True).encode('utf-8'))
    return dict(path=str(target), kind=kind, plan_id=plan,
                description='已有Studio数据根，重启后打开其中历史。' if kind=='REGISTERED' else '空数据目录，重启后接入工程或导入归档。',
                activation='保存成功后关闭软件，再次双击ECRA.cmd；当前窗口与运行任务继续使用原目录。',
                retention='旧工程、扫描与人工记录保留在原根。数据目录选择不等于完整数据搬迁。')


def preview(path, current):
    result = _target(path, current)
    result['revision'] = read_preferences()['revision']
    return result


@contextmanager
def _settings_lock(home):
    from .storage_activity import DataActivity
    lease = DataActivity(home, exclusive=True)
    try:
        lease.__enter__()
    except ValueError as exc:
        raise PreferenceConflict('另一窗口正在保存启动设置；请稍后重新读取并检查目录') from exc
    try:
        yield
    finally:
        lease.__exit__(None, None, None)


def save(path, current, *, plan_id, revision, repair=False):
    from .workspace import managed_root, no_links
    from .common import replace_file
    home = preference_home()
    home.mkdir(parents=True, exist_ok=True)
    with _settings_lock(home):
        state = read_preferences()
        if revision != state['revision']:
            raise PreferenceConflict('启动设置已由另一窗口修改；请重新读取并检查目录')
        plan = _target(path, current)
        if plan_id != plan['plan_id']:
            raise PreferenceConflict('目标目录或归属已改变；请重新检查目录')
        if state['status']=='INVALID' and repair is not True:
            raise ValueError('请明确同意备份损坏启动设置后再保存')
        target = no_links(plan['path'])
        target.mkdir(parents=True, exist_ok=True)
        # This explicit save is the first write to a chosen empty root.
        # Never leave probe bytes or touch existing scan/human databases.
        with tempfile.TemporaryFile(prefix='.ecra-write-check-', dir=target) as stream:
            stream.write(b'ECRA startup directory check');stream.flush();os.fsync(stream.fileno())
        no_links(target)
        if state['raw'] is not None:
            backups = no_links(home/'preferences-backups');backups.mkdir(exist_ok=True)
            backup = no_links(backups/(state['revision']+'.json'))
            try:
                with backup.open('xb') as stream:
                    stream.write(state['raw']);stream.flush();os.fsync(stream.fileno())
            except FileExistsError:
                if backup.read_bytes()!=state['raw']:
                    raise ValueError('启动设置备份摘要冲突；原设置保留')
        payload = dict(state['payload'] or {})
        payload.pop('data_root', None)
        payload.update(format='ECRA_STUDIO_PREFERENCES', version=1,
                       workspace_relative=target.relative_to(managed_root()).as_posix())
        raw = json.dumps(payload, ensure_ascii=True, indent=2).encode('utf-8')+b'\n'
        pending = None
        try:
            with tempfile.NamedTemporaryFile(prefix='preferences-',suffix='.pending',dir=home,delete=False) as stream:
                pending = no_links(stream.name);stream.write(raw);stream.flush();os.fsync(stream.fileno())
            replace_file(pending, no_links(home/'preferences.json'))
        finally:
            if pending is not None:pending.unlink(missing_ok=True)
        return dict(saved=True, selected_root=str(target), revision=_hash(raw),
                    activation=plan['activation'], retention=plan['retention'])
