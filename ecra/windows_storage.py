"""Handle-bound Windows allocation and transparent, byte-verified compression."""
import ctypes
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path
import time


class StandardInfo(ctypes.Structure):
    _fields_=[('allocated',ctypes.c_longlong),('end',ctypes.c_longlong),('links',w.DWORD),('delete',w.BYTE),('directory',w.BYTE)]


class IdInfo(ctypes.Structure):
    _fields_=[('volume',ctypes.c_ulonglong),('identity',w.BYTE*16)]


def _extended(path):
    name=str(Path(path).absolute())
    return name if name.startswith('\\\\?\\') else '\\\\?\\UNC\\'+name[2:] if name.startswith('\\\\') else '\\\\?\\'+name


class WindowsFiles:
    def __init__(self):
        if os.name!='nt':raise OSError('实际文件分配量仅支持Windows')
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        signatures={
            'CreateFileW':([w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE],w.HANDLE),
            'GetFileInformationByHandleEx':([w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD],w.BOOL),
            'GetFinalPathNameByHandleW':([w.HANDLE,w.LPWSTR,w.DWORD,w.DWORD],w.DWORD),
            'DeviceIoControl':([w.HANDLE,w.DWORD,ctypes.c_void_p,w.DWORD,ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD),ctypes.c_void_p],w.BOOL),
            'ReadFile':([w.HANDLE,ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD),ctypes.c_void_p],w.BOOL),
            'SetFilePointerEx':([w.HANDLE,ctypes.c_longlong,ctypes.c_void_p,w.DWORD],w.BOOL),
            'FlushFileBuffers':([w.HANDLE],w.BOOL),'CloseHandle':([w.HANDLE],w.BOOL),
            'GetVolumePathNameW':([w.LPCWSTR,w.LPWSTR,w.DWORD],w.BOOL),
            'GetDiskFreeSpaceW':([w.LPCWSTR,ctypes.POINTER(w.DWORD),ctypes.POINTER(w.DWORD),ctypes.POINTER(w.DWORD),ctypes.POINTER(w.DWORD)],w.BOOL),
            'GetVolumeInformationW':([w.LPCWSTR,w.LPWSTR,w.DWORD,ctypes.POINTER(w.DWORD),ctypes.POINTER(w.DWORD),ctypes.POINTER(w.DWORD),w.LPWSTR,w.DWORD],w.BOOL)}
        for name,(args,result) in signatures.items():
            fn=getattr(self.api,name);fn.argtypes=args;fn.restype=result

    def checked(self,result):
        if not result:raise ctypes.WinError(ctypes.get_last_error())
        return result

    def open(self,path,*,write=False):
        # Compression owns an exclusive handle. The leaf may never be followed
        # as a reparse point, even if a path is replaced after validation.
        handle=self.api.CreateFileW(_extended(path),0xC0000000 if write else 0x80,0 if write else 7,None,3,0x200000,None)
        if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def information(self,handle):
        attributes=(w.DWORD*2)();self.checked(self.api.GetFileInformationByHandleEx(handle,9,attributes,ctypes.sizeof(attributes)))
        if attributes[0]&0x400:raise ValueError('拒绝链接或重解析文件')
        standard=StandardInfo();self.checked(self.api.GetFileInformationByHandleEx(handle,1,ctypes.byref(standard),ctypes.sizeof(standard)))
        if standard.directory or standard.allocated<0:raise ValueError('只接受普通文件')
        ident=IdInfo();self.checked(self.api.GetFileInformationByHandleEx(handle,18,ctypes.byref(ident),ctypes.sizeof(ident)))
        return dict(allocated_bytes=standard.allocated,logical_bytes=standard.end,links=standard.links,
                    identity=[ident.volume,bytes(ident.identity).hex()],attributes=attributes[0])

    def allocation(self,path):
        handle=self.open(path)
        try:return self.information(handle)
        finally:self.api.CloseHandle(handle)

    def final_path(self,handle):
        buffer=ctypes.create_unicode_buffer(32768);count=self.checked(self.api.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0))
        if count>=len(buffer):raise ValueError('文件最终路径过长')
        name=buffer.value
        if name.startswith('\\\\?\\UNC\\'):name='\\\\'+name[8:]
        elif name.startswith('\\\\?\\'):name=name[4:]
        return Path(name)

    def compression_supported(self,path):
        volume=ctypes.create_unicode_buffer(32768);self.checked(self.api.GetVolumePathNameW(_extended(path),volume,len(volume)))
        flags=w.DWORD();system=ctypes.create_unicode_buffer(64)
        self.checked(self.api.GetVolumeInformationW(volume,None,0,None,None,ctypes.byref(flags),system,len(system)))
        sectors=w.DWORD();bytes_per_sector=w.DWORD();free=w.DWORD();total=w.DWORD()
        self.checked(self.api.GetDiskFreeSpaceW(volume,ctypes.byref(sectors),ctypes.byref(bytes_per_sector),ctypes.byref(free),ctypes.byref(total)))
        return system.value=='NTFS' and bool(flags.value&0x10) and sectors.value*bytes_per_sector.value<=4096

    def hash(self,handle):
        self.checked(self.api.SetFilePointerEx(handle,0,None,0));buffer=ctypes.create_string_buffer(1024**2);count=w.DWORD();digest=hashlib.sha256()
        while True:
            self.checked(self.api.ReadFile(handle,buffer,len(buffer),ctypes.byref(count),None))
            if not count.value:break
            digest.update(memoryview(buffer).cast('B')[:count.value])
        return digest.hexdigest()

    def compress(self,path):
        from .workspace import no_links
        expected=no_links(path);started=time.monotonic();handle=self.open(expected,write=True)
        result=dict(path=str(expected),status='FAILED',byte_verified=False)
        try:
            if self.final_path(handle)!=expected:raise ValueError('压缩文件的实际最终路径已改变')
            # Unsupported filesystems may also lack FileIdInfo. Determine that
            # capability before requiring the NTFS identity contract.
            if not self.compression_supported(expected):result.update(status='SKIPPED_UNSUPPORTED_FILESYSTEM');return result
            before=self.information(handle);result['before']=before
            # Do not change other names of the same file, encrypted files, or
            # files outside Microsoft's documented single-file size range.
            if before['links']!=1:result.update(status='SKIPPED_MULTIPLE_LINKS');return result
            if before['attributes']&0x4000:result.update(status='SKIPPED_ENCRYPTED');return result
            if before['logical_bytes']>30_000_000_000:result.update(status='SKIPPED_FILE_OVER_30GB');return result
            before_hash=self.hash(handle);result['before_sha256']=before_hash
            returned=w.DWORD();kind=w.USHORT(1)
            self.checked(self.api.DeviceIoControl(handle,0x9C040,ctypes.byref(kind),ctypes.sizeof(kind),None,0,ctypes.byref(returned),None))
            self.checked(self.api.FlushFileBuffers(handle))
            after=self.information(handle);after_hash=self.hash(handle);result.update(after=after,after_sha256=after_hash)
            actual=w.USHORT()
            self.checked(self.api.DeviceIoControl(handle,0x9003C,None,0,ctypes.byref(actual),ctypes.sizeof(actual),ctypes.byref(returned),None))
            if (before_hash!=after_hash or before['logical_bytes']!=after['logical_bytes'] or before['identity']!=after['identity']
                    or after['links']!=1 or self.final_path(handle)!=expected or not actual.value):
                raise ValueError('压缩前后字节、逻辑长度、文件身份或压缩状态不一致；本轮不得有效发布')
            result.update(status='COMPRESSED',byte_verified=True,compression_format=actual.value,
                          allocated_reduction_bytes=before['allocated_bytes']-after['allocated_bytes'])
            return result
        finally:
            result['seconds']=time.monotonic()-started
            self.api.CloseHandle(handle)
