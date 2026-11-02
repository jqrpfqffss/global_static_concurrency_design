"""Stable local startup preferences, separate from replaceable app/data roots."""
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
    from .workspace import studio_data_root
    if os.name == 'nt':
        raw = os.environ.get('LOCALAPPDATA', '')
        if not Path(raw).is_absolute():
            raise PreferenceError('LOCALAPPDATA不可用，无法保存启动目录')
        home = Path(raw)/'ECRAStudio'
    else:
        home = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'ECRAStudio'
    return studio_data_root(home)


def read_preferences():
    from .workspace import no_links, studio_data_root
    file = no_links(preference_home()/'preferences.json')
    if not file.exists():
        return dict(revision='missing', status='MISSING', selected=None, error=None, payload=None, raw=None)
    if file.stat().st_size > 1024*1024:
        raise PreferenceError('启动设置超过1MiB；请保留原件并从明确数据目录启动恢复：'+str(file))
    raw = file.read_bytes()
    result = dict(revision=_hash(raw), status='INVALID', selected=None, error=None, payload=None, raw=raw)
    try:
        payload = json.loads(raw.decode('utf-8'))
        if (not isinstance(payload, dict) or payload.get('format') != 'ECRA_STUDIO_PREFERENCES'
                or type(payload.get('version')) is not int or payload['version'] != 1):
            raise ValueError('启动设置协议不支持')
        target = payload.get('data_root')
        if not isinstance(target, str) or not Path(target).is_absolute():
            raise ValueError('已保存的数据目录不是绝对路径')
        selected = studio_data_root(target)
        from .config import TOOL_ROOT
        if selected == Path(selected.anchor) or Path(TOOL_ROOT).resolve().is_relative_to(selected):
            raise ValueError('数据目录不能是盘根或程序安装目录的父目录')
        if not Path(selected.anchor).exists():
            raise ValueError('已保存数据目录所在磁盘当前不可用')
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
        return dict(root=studio_data_root(explicit), source='STARTUP_ARGUMENT', warning=None)
    if os.environ.get('ECRA_DATA_ROOT'):
        return dict(root=studio_data_root(), source='ENVIRONMENT', warning=None)
    try:
        state = read_preferences()
        if state['status'] == 'INVALID':
            raise PreferenceError(state['error'])
        if state['selected']:
            return dict(root=studio_data_root(state['selected']), source='GUI_DEFAULT', warning=None)
    except (PreferenceError, OSError) as exc:
        return dict(root=studio_data_root(default_user_data_root()), source='RECOVERY_DEFAULT',
                    warning=str(exc)+'。当前在系统默认目录恢复设置，原数据目录未搬迁；请到设置页核对。')
    return dict(root=studio_data_root(default_user_data_root()), source='SYSTEM_DEFAULT', warning=None)


def status(current, source, warning=None):
    state = read_preferences()
    return dict(current_root=str(current), source=source, startup_warning=warning,
                selected_root=state['selected'], revision=state['revision'], preference_status=state['status'],
                error=state['error'], preference_file=str(preference_home()/'preferences.json'),
                precedence='启动参数 > ECRA_DATA_ROOT > GUI保存的默认值 > 系统默认',
                explicit_override=source in {'STARTUP_ARGUMENT', 'ENVIRONMENT'})


def _target(path, current):
    from .workspace import no_links, studio_data_root
    from .config import TOOL_ROOT, configured_project_root
    if not isinstance(path, str) or not path or not Path(path).is_absolute():
        raise ValueError('请选择数据目录的绝对路径，例如 D:/ECRA-data')
    target = studio_data_root(path)
    current = no_links(current)
    if target == Path(target.anchor) or Path(TOOL_ROOT).resolve().is_relative_to(target):
        raise ValueError('数据目录不能是盘根或程序安装目录的父目录')
    if target != current and (target.is_relative_to(current) or current.is_relative_to(target)):
        raise ValueError('请选择与当前数据根无父子关系的另一独立目录')
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
            with os.scandir(target) as entries:
                if next(entries, None) is not None:
                    raise ValueError('目标非空且不是已登记Studio数据根；旧.ecra/workspace请从数据与共享迁移')
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
    from .workspace import no_links
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
        payload.update(format='ECRA_STUDIO_PREFERENCES', version=1, data_root=str(target))
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
