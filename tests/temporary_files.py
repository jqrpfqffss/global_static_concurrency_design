"""Remove owned generated files after Windows releases their image handles."""
import os
from pathlib import Path
import time


def remove_generated_file(path, root, *, retries=6):
    path, expected_root = Path(path), Path(root).absolute()
    root = expected_root.resolve()
    if root != expected_root or path.parent.resolve() != root or path.name not in {'replay','replay.exe'}:
        raise ValueError('Refusing cleanup outside the owned generated replay file')
    for attempt in range(retries+1):
        try:
            path.unlink(missing_ok=True)
            return
        except OSError as exc:
            if os.name != 'nt' or getattr(exc,'winerror',None) not in (32,33) or attempt==retries:
                raise
            time.sleep(.05*2**attempt)
