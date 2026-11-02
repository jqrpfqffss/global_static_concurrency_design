"""Small display provenance; never evidence of safety or current-source validity."""
import hashlib
from pathlib import PurePosixPath, PureWindowsPath


def _text(value):
    return value if isinstance(value, str) and value else None


def capture(config_raw, config_file, coverage):
    """Only call with the exact config bytes already checked against InputSnapshot."""
    import yaml
    record = dict(version=1, config_file=str(config_file), config_sha256=hashlib.sha256(config_raw).hexdigest())
    if len(config_raw) > 256*1024:
        return dict(record, note='配置超过显示元数据解析上限；完整原文仍归档，名称与配置目标未提取。')
    cfg = yaml.safe_load(config_raw.decode('utf-8-sig'))
    if not isinstance(cfg, dict): return record
    project = cfg.get('project', {})
    analysis = cfg.get('analysis', {})
    cmake = analysis.get('cmake', {}) if isinstance(analysis, dict) else {}
    cache = coverage.get('cmake_cache', {})
    record.update(project_name=_text(project.get('name')) if isinstance(project, dict) else None,
                  configured_target=_text(cmake.get('target')) if isinstance(cmake, dict) else None,
                  build_variant=_text(cache.get('CMAKE_BUILD_TYPE')) if isinstance(cache, dict) else None)
    return record


def query(provider):
    """Resolve bounded archived scalars, without rebuilding any evidence object."""
    oversized = []
    def scalar(root, path):
        try:
            node = provider.node(provider.resolve(root, path), limit=1)
        except KeyError:
            return None
        if node['kind'] not in {'str', 'bool', 'int', 'null'}: return None
        if node.get('segmented'):
            oversized.append('/'.join([root, *path])); return None
        return node.get('value')
    def archived(key): return scalar('provenance', ['display_identity', key])
    root = scalar('report', ['workspace', 'project_root']) or scalar('provenance', ['project_root'])
    name = archived('project_name')
    origin = '归档配置声明'
    if not name:
        name = (PureWindowsPath(root).name if '\\' in root else PurePosixPath(root).name) if isinstance(root, str) else None
        origin = '归档工程根目录名；未记录工程显示名称' if name else '未记录工程名称或根目录'
    pin = {key: scalar('report', ['git_diff', 'pin', key]) for key in
           ['base_ref', 'current_ref', 'base_sha', 'head_sha', 'include_uncommitted']}
    return dict(project_name=name, project_name_source=origin, project_root=root,
                configured_target=archived('configured_target'),
                build_variant=archived('build_variant') or scalar('report', ['coverage', 'cmake_cache', 'CMAKE_BUILD_TYPE']),
                compile_database=scalar('report', ['coverage', 'compile_database']),
                config_file=archived('config_file'), config_sha256=archived('config_sha256'),
                metadata_note=archived('note'),
                generated_at=scalar('report', ['generated_at']),
                recorded_git_commit=scalar('report', ['git_commit']), diff=pin if any(v is not None for v in pin.values()) else None,
                analysis_status=scalar('report', ['analysis_status']), oversized_fields=oversized,
                note='身份只说明本归档的来源；不表示当前源码已重验、芯片自动识别或全工程安全。')
