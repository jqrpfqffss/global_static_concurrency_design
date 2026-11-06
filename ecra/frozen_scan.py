"""Fixed logical Clang inputs and replay for explicit compilation databases.

The caller owns a complete pre-existing capture. Runtime view identities never
enter analysis configuration, cache keys or static report normalization.
"""
from pathlib import Path
from contextlib import contextmanager

from .working_compiler_view import ParentFiles, validate


def execution_workspace(root, analysis, compiler_view):
    """Reuse every formal path boundary; only the private dirty gate differs.

    A non-null view is subsequently fully verified before pin/base processing.
    Broker-owned GUI/CLI capture supplies this internal argument. CMake and
    unproved build modes remain blocked by the separate configuration policy.
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
    if (doctor_only or (diff['enabled'] and (not diff.get('include_uncommitted') or diff.get('current_ref')!='HEAD'))
            or analysis.get('auto_configure_cmake', False)
            or (analysis.get('compile_database', 'auto') == 'auto' and 'cmake' not in analysis)
            or not analysis.get('build_closure_only', True)):
        raise ValueError('冻结扫描内部验收仅支持显式编译数据库的完整/HEAD工作区比较；固定提交Diff/CMake/补充扫描尚未验收')
    if 'cmake' in analysis:
        from .working_cmake import policy
        policy(analysis)
    out = Path(workspace.results_root)
    if (out/'scan.db').exists() or (out/'run.json').exists():
        raise ValueError('冻结扫描验收需要新的原生扫描目录；原有结果保留')


class ScanFiles(ParentFiles):
    """Verify original Git/index/files/namespace at every pipeline barrier."""
    def __init__(self, descriptor, root, cfg, *, review_config_path=None):
        self.review_config_path=review_config_path
        self.watch=None
        from .working_compiler_view import _load
        folder,record=_load(descriptor,root,cfg)
        if record.get('format')!='ECRA_FROZEN_COMPILER_VIEW_V3':
            validate(descriptor, root, cfg, reverify_original=True,review_config_path=review_config_path)
            super().__init__(descriptor, root, cfg)
            return
        from .guarded_cmake import InputWatch
        watch=InputWatch()
        try:
            # Capture-level Git/audit files may legitimately be materialized
            # by baseline consumers. Watch immutable compiler copies, and keep
            # the original full source/Git proof at every barrier separately.
            watch.directory(record['repository_root']);watch.directory(folder)
            from .working_snapshot import _git
            repository=Path(record['repository_root'])
            for option in ('--git-dir','--git-common-dir'):
                name=Path(_git(repository,'rev-parse',option).decode('utf-8').strip())
                watch.directory(name if name.is_absolute() else repository/name)
            for path in record['external_directories']:watch.directory(path)
            for path in record['external_files']:watch.file(path)
            # Mount the sticky guards before the complete initial validation.
            # Subsequent barriers can prove no change without rehashing every
            # SDK byte. The canonical publisher still does a full final audit.
            validate(descriptor,root,cfg,reverify_original=True,review_config_path=review_config_path)
            super().__init__(descriptor,root,cfg)
            watch.check();self.watch=watch
        except BaseException:
            if getattr(self,'connection',None) is not None:super().close()
            watch.close();raise

    def assert_valid(self):
        if self.connection is None:
            raise ValueError('冻结父进程文件视图已经关闭')
        if self.watch is not None:
            from .working_compiler_view import _load
            self.watch.check()
            _load(dict(file=self.identity['file'],sha256=self.identity['sha256']),self.record['root'],self.config)
            from .working_snapshot import validate as validate_working
            validate_working(self.record['capture'],self.record['root'],self.config,reverify_original=True)
            return
        validate(dict(file=self.identity['file'], sha256=self.identity['sha256']),
                 self.record['root'], self.config, reverify_original=True,review_config_path=self.review_config_path)

    def close(self):
        try:super().close()
        finally:
            if self.watch is not None:self.watch.close();self.watch=None


@contextmanager
def replay_files(capsule,root,cfg,*,config_path=None):
    identity=capsule.get('frozen_view')
    if identity is None:
        yield None
        return
    base={'file','sha256','original_final_reverification_required'}
    legacy=isinstance(identity,dict) and set(identity)==base|{'formal_dirty_enabled'} and identity['formal_dirty_enabled'] is False
    modern=(isinstance(identity,dict) and set(identity)==base|{'proof_scope'}
        and identity['proof_scope'] in {'COMPLETE_LOGICAL_CLANG_INPUTS_V1','COMPLETE_GUARDED_CMAKE_INPUTS_V1'})
    if not (legacy or modern) or identity['original_final_reverification_required'] is not True:
        raise ValueError('冻结父进程输入证明字段不完整或版本未知；不能忽略视图身份读取实时源码')
    from .dirty_inputs import supported
    supported(cfg['analysis'])
    descriptor={key:identity[key] for key in ('file','sha256')}
    with ScanFiles(descriptor,root,cfg,review_config_path=config_path) as view:
        if view.identity!=identity:raise ValueError('冻结输入闭包与原视图证明不一致')
        yield view
        view.assert_valid()


def saved_reader(root,out,cfg,state):
    """Bind later Packet/source reads to the exact verified closure bytes."""
    from contextlib import nullcontext
    import hashlib
    import json
    expected=state.get('input_closure_sha256')
    if not expected:return nullcontext(None)
    raw=(Path(out)/'input_closure.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError('扫描输入闭包在复验后变化，不能构造复核证据')
    return replay_files(json.loads(raw),root,cfg,config_path=Path(root)/state['config_file'])
