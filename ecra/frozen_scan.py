"""Internal full-scan integration; formal dirty/Diff/resume remain gated.

The caller owns a complete pre-existing capture. Runtime view identities never
enter analysis configuration, cache keys or static report normalization.
"""
from pathlib import Path

from .working_compiler_view import ParentFiles, validate


def execution_workspace(root, analysis, compiler_view):
    """Reuse every formal path boundary; only the private dirty gate differs.

    A non-null view is subsequently fully verified before pin/base processing.
    Ordinary GUI/CLI calls never provide this internal argument.
    """
    from .workspace import formal_workspace
    if compiler_view is None:
        return formal_workspace(root, analysis)
    effective=dict(analysis,git_diff=dict(analysis.get('git_diff',{}),include_uncommitted=False))
    return formal_workspace(root, effective)


def check_mode(cfg, workspace, doctor_only):
    from .scan_persistence import is_canonical
    analysis = cfg['analysis']
    if workspace is None or not is_canonical(workspace.results_root):
        raise ValueError('冻结扫描验收必须使用显式独立原生工作区')
    diff=analysis['git_diff']
    if (doctor_only or (diff['enabled'] and (not diff.get('include_uncommitted') or diff.get('current_ref')!='HEAD')) or 'cmake' in analysis
            or analysis.get('auto_configure_cmake', False)
            or analysis.get('compile_database', 'auto') == 'auto'
            or not analysis.get('build_closure_only', True)):
        raise ValueError('冻结扫描内部验收仅支持显式编译数据库的完整/HEAD工作区比较；固定提交Diff/CMake/补充扫描尚未验收')
    out = Path(workspace.results_root)
    if (out/'scan.db').exists() or (out/'run.json').exists():
        raise ValueError('冻结扫描验收需要新的原生扫描目录；原有结果保留')


class ScanFiles(ParentFiles):
    """Verify original Git/index/files/namespace at every pipeline barrier."""
    def __init__(self, descriptor, root, cfg):
        validate(descriptor, root, cfg, reverify_original=True)
        super().__init__(descriptor, root, cfg)

    def assert_valid(self):
        if self.connection is None:
            raise ValueError('冻结父进程文件视图已经关闭')
        validate(dict(file=self.identity['file'], sha256=self.identity['sha256']),
                 self.record['root'], self.config, reverify_original=True)
