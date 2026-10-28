"""Immutable report history without copying complete large evidence twice."""
import os
from pathlib import Path
import re
import shutil

_ATOMIC_FILES = frozenset({
    'facts.json', 'facts.db',
    'inventory/global_static_inventory.json',
    'reports/global_static_concurrency.json',
    'reports/root_cause_v2.json',
    'inventory/global_static_inventory.md',
    'reports/global_static_concurrency.md',
    'reports/unknown_contexts.md',
})
_HASH_FILE = re.compile(r'[0-9a-f]{64}\.(?:css|html|json)\Z')


def copy_snapshot_file(source, destination, *, root):
    """Link only known atomically replaced artifacts; copy mutable files.

    A later atomic replacement creates a different inode and leaves history
    intact. On unsupported/different volumes retain the ordinary copy path.
    This function never removes or edits the source or prior history.
    """
    source, destination, root = Path(source), Path(destination), Path(root)
    try:
        relative = source.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = None
    immutable = (relative in _ATOMIC_FILES or
        (source.parent.name == 'html_details' and relative is not None and
         _HASH_FILE.fullmatch(source.name)))
    if immutable and not source.is_symlink():
        try:
            os.link(source, destination)
            return str(destination)
        except OSError:
            pass
    return shutil.copy2(source, destination)
