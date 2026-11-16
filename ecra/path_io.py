"""Use extended Win32 paths for I/O while keeping ordinary path identities."""
import os
from pathlib import Path
import stat


_EXTENDED = '\\\\?\\'
_EXTENDED_UNC = _EXTENDED + 'UNC\\'


def filesystem_path(path):
    path = Path(path)
    if os.name != 'nt':
        return path
    value = os.path.normpath(str(path.absolute()))
    if value.startswith((_EXTENDED, '\\\\.\\')):
        return Path(value)
    if value.startswith('\\\\'):
        return Path(_EXTENDED_UNC + value[2:])
    return Path(_EXTENDED + value)


def ordinary_path(path):
    value = str(path)
    if value.startswith(_EXTENDED_UNC):
        return Path('\\\\' + value[len(_EXTENDED_UNC):])
    if value.startswith(_EXTENDED) and Path(value[len(_EXTENDED):]).is_absolute():
        return Path(value[len(_EXTENDED):])
    return Path(path)


def resolved_path(path):
    return ordinary_path(filesystem_path(path).resolve())


def is_link(info):
    return (stat.S_ISLNK(info.st_mode) or
            bool(getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT))


def lstat_if_present(path):
    try:
        return filesystem_path(path).lstat()
    except FileNotFoundError:
        # This is an existence query on the extended spelling. Callers that
        # require an existing object must still reject this result.
        return None
