"""Experimental test reserve that releases private Windows commit immediately."""
import ctypes
import mmap
import os


def python_reserve():
    return ([object() for _ in range(128)] + [float(i) for i in range(128)] +
            [bytes(size) for size in range(0, 480, 8) for _ in range(128)])


class CommitReserve:
    def __init__(self, size=8*1024*1024):
        self.mapping = None
        self.pointer = None
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            allocate = kernel.VirtualAlloc
            allocate.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.c_ulong]
            allocate.restype = ctypes.c_void_p
            self.free = kernel.VirtualFree
            self.free.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong]
            self.free.restype = ctypes.c_int
            address = allocate(None, size, 0x3000, 0x04)
            if not address:
                raise ctypes.WinError(ctypes.get_last_error())
            self.pointer = ctypes.c_void_p(address)
            self.zero = ctypes.c_size_t(0)
            self.release = ctypes.c_ulong(0x8000)
        else:
            self.mapping = mmap.mmap(-1, size)

    def close(self):
        if self.pointer is not None:
            if not self.free(self.pointer, self.zero, self.release):
                raise ctypes.WinError(ctypes.get_last_error())
            self.pointer = None
        if self.mapping is not None:
            self.mapping.close()
            self.mapping = None

    def __del__(self):
        try:
            self.close()
        except (OSError, AttributeError):
            pass
