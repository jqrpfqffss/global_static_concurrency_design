import ctypes
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from tests.temporary_files import remove_generated_file


class GeneratedFileCleanupTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows sharing violation')
    def test_actual_windows_lock_is_retried_until_owned_handle_is_released(self):
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,
                                    ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
        kernel.CreateFileW.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        kernel.CloseHandle.restype=ctypes.c_int
        with tempfile.TemporaryDirectory(prefix='ecra test lock ') as folder:
            root=Path(folder).resolve();path=root/'replay.exe';path.write_bytes(b'owned lock fixture')
            handle=kernel.CreateFileW(str(path),0x80000000,0,None,3,0x80,None)
            if handle==ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            release=threading.Timer(.2,lambda:kernel.CloseHandle(handle))
            release.start()
            try:
                remove_generated_file(path,root)
                self.assertFalse(path.exists())
            finally:
                release.join()

    def test_scope_and_unrelated_permissions_remain_strict(self):
        with tempfile.TemporaryDirectory(prefix='ecra test cleanup ') as folder:
            root=Path(folder).resolve()
            with self.assertRaises(ValueError):
                remove_generated_file(root.parent/'replay.exe',root)
            error=PermissionError('persistent access denial');error.winerror=5
            with patch.object(Path,'unlink',side_effect=error) as unlink,self.assertRaises(PermissionError):
                remove_generated_file(root/'replay.exe',root)
            self.assertEqual(unlink.call_count,1)
