"""The shared CLI/Studio/Portable no-model availability check."""
import uuid

from .common import write_json
from .opencode_command import resolve_command
from .opencode_storage import ReviewStorage
from .review_opencode_sessions import Runtime
from .workspace import control_path


def check(settings, *, project=None, environment=None):
    out = control_path('opencode-checks', uuid.uuid4().hex)
    out.mkdir(parents=True)
    result = dict(ready=False, stage='local_configuration', cli_launch_attempts=0, model_calls=0, diagnostics=str(out))
    runtime = None
    try:
        runtime = Runtime(resolve_command(settings.get('command', ['opencode'])),
                          timeout=settings.get('maintenance_timeout_seconds', 60))
        storage = ReviewStorage(out, project=project, settings=settings, environment=environment)
        storage.prepare(runtime)
        with storage.call():
            pass  # Validate the same local directories/environment without launching OpenCode.
        result.update(ready=True, database=str(storage.database), shared=storage.shared,
                      config_sources=storage.config_sources,
                      notice='仅本地配置和启动路径检查通过；未启动 OpenCode，未验证认证、模型或清理能力。')
    except (ValueError, OSError) as exc:
        result.update(error=str(exc), error_code=getattr(exc, 'code', 'initialization_failed'))
    if runtime:
        result.update(runtime.report())
    write_json(out/'result.json', result)
    return result
