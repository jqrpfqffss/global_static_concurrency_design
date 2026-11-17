"""The shared CLI/Studio/Portable no-model availability check."""
import uuid

from .common import write_json
from .opencode_command import resolve_command
from .opencode_storage import ReviewStorage
from .review_opencode_sessions import Runtime, store_identity
from .workspace import control_path


def check(settings, *, project=None, environment=None):
    out = control_path('opencode-checks', uuid.uuid4().hex)
    out.mkdir(parents=True)
    result = dict(ready=False, model_calls=0, diagnostics=str(out))
    runtime = None
    try:
        runtime = Runtime(resolve_command(settings.get('command', ['opencode'])),
                          timeout=settings.get('maintenance_timeout_seconds', 60))
        storage = ReviewStorage(out, project=project, settings=settings, environment=environment)
        runtime.context = dict(scope=storage.scope, data=storage.data, environment=storage.environment)
        with runtime.maintenance(storage.database, workdir=storage.scope, shared=storage.shared) as maintenance:
            runtime.probe(maintenance)
            if storage.shared and store_identity(storage.database, allow_missing=True):
                maintenance.check_shared_schema()
                runtime.capabilities['storage'] = 'READ_ONLY_COMPATIBLE'
        result.update(ready=True, database=str(storage.database), shared=storage.shared,
                      notice='入口和隔离存储已验证；认证有效性及模型事件完成状态仍须首次实际复核确认。')
    except (ValueError, OSError) as exc:
        result.update(error=str(exc), error_code=getattr(exc, 'code', 'initialization_failed'))
    if runtime:
        result.update(runtime.report())
    write_json(out/'result.json', result)
    return result
