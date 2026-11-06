"""Optional guarded CMake subprocess executor; ordinary execution is unchanged."""
from contextvars import ContextVar
from .common import execute as ordinary_execute

BUILD_EXECUTOR = ContextVar('ecra_build_executor', default=None)
FROZEN_BUILD = ContextVar('ecra_frozen_build', default=None)


def execute(argv, **kwargs):
    executor = BUILD_EXECUTOR.get()
    return ordinary_execute(argv, **kwargs) if executor is None else executor(argv, **kwargs)
