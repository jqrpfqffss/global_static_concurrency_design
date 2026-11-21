"""Bind Studio retries to the selection made by their original CMake configure."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from .common import digest, read_json, write_json
from .input_snapshot import verify_consumed_files
from .report_package import IDENTITY, sha256
from .workspace import no_links


_task = ContextVar('cmake_target_task', default=None)
_side = ContextVar('cmake_target_side', default='current')
protected_baseline = ContextVar('cmake_target_protected_baseline', default=False)
_NAME = 'cmake-target-checkpoint.json'


@contextmanager
def baseline_selection(protected):
    side = _side.set('baseline')
    mode = protected_baseline.set(protected)
    try:
        yield
    finally:
        protected_baseline.reset(mode)
        _side.reset(side)


@contextmanager
def task_selection(folder):
    """A task may reconfigure, but only after checking the original proof."""
    folder = no_links(folder)
    records = {}
    recipe = folder/'retry-source.json'
    if recipe.exists():
        reference = read_json(no_links(recipe))
        source_id = reference.get('source_task')
        if not isinstance(source_id, str) or not IDENTITY.fullmatch(source_id):
            raise ValueError('恢复 CMake 目标的任务来源无效')
        previous = no_links(folder.parent/source_id)
        path = no_links(previous/_NAME)
        if path.exists():
            saved = read_json(path)
            records = saved.get('records')
            if (saved.get('version') != 1 or not isinstance(records, dict)
                    or set(records) - {'current', 'baseline'} or saved.get('digest') != digest(records)
                    or saved.get('config_sha256') != sha256(folder/'semantics.yaml')
                    or saved['config_sha256'] != sha256(no_links(previous/'semantics.yaml'))):
                raise ValueError('原 CMake 目标检查点损坏或配置已改变；请发起新扫描')
    path = no_links(folder/_NAME)
    if records:
        _write(path, records)
    token = _task.set((path, records))
    try:
        yield
    finally:
        _task.reset(token)


def _write(path, records):
    write_json(path, dict(version=1, records=records, digest=digest(records),
                          config_sha256=sha256(path.parent/'semantics.yaml')))


def check_previous_selection(root, build, eligible):
    state = _task.get()
    prior = state[1].get(_side.get()) if state is not None else None
    if prior is None:
        return
    if not prior.get('selection', {}).get('effective_target'):
        raise ValueError('旧检查点没有已验证的 CMake 逻辑目标；请发起新扫描')
    if not eligible or prior['source'] != str(root) or prior['build'] != str(build):
        raise ValueError('恢复时 CMake 目标的工程/构建目录身份已改变；请发起新扫描')
    # Before an owned clean would discard the actual graph, reject missing,
    # replaced or edited evidence from the original attempt.
    verify_consumed_files(prior['inputs'])


def save_selection(root, build, decision, inputs, index):
    state = _task.get()
    if state is None:
        return
    path, records = state
    side = _side.get()
    # The original replies are checked byte for byte before cleaning and the
    # new replies are fully validated. A fresh configure can reorder File API
    # descriptions (and rename their content-addressed files) without changing
    # the decision. Compare the decision, actual graph and commands across runs.
    stable = {file: row['sha256'] for file, row in inputs.items()
              if Path(file).parent != index.parent and file != str(build/'CMakeCache.txt')}
    signature = digest([decision, stable])
    if side in records and records[side]['signature'] != signature:
        raise ValueError('重新配置的 CMake 目标或选择依据与原检查点不同；请发起新扫描')
    records[side] = dict(source=str(root), build=str(build), signature=signature,
                         selection=decision, inputs={file:dict(status='OK', sha256=row['sha256'])
                                                     for file, row in inputs.items()})
    _write(path, records)
