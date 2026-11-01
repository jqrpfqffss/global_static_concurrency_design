"""Windows benchmark observer metrics; never substitutes zeros for failures.

FileStandardInfo allocation excludes directory/MFT metadata and alternate data
streams. A directory walk is a sampled lower bound, not an instantaneous peak.
PDH paging counters are host-wide, not attributable to one ECRA process.
"""
import ctypes
from ctypes import wintypes as w
import math
import os
from pathlib import Path
import time


class FileStandardInfo(ctypes.Structure):
    _fields_=[('allocated',ctypes.c_longlong),('end',ctypes.c_longlong),('links',w.DWORD),('delete',w.BYTE),('directory',w.BYTE)]


class FileIdInfo(ctypes.Structure):
    _fields_=[('volume',ctypes.c_ulonglong),('identity',w.BYTE*16)]


class FileAllocation:
    def __init__(self):
        if os.name!='nt':raise OSError('Windows allocation information required')
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        self.api.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE];self.api.CreateFileW.restype=w.HANDLE
        self.api.GetFileInformationByHandleEx.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD];self.api.GetFileInformationByHandleEx.restype=w.BOOL
        self.api.CloseHandle.argtypes=[w.HANDLE];self.api.CloseHandle.restype=w.BOOL

    def __call__(self,path):
        return self.information(path)[0]

    def information(self,path):
        name=str(Path(path).absolute())
        if not name.startswith('\\\\?\\'):name='\\\\?\\UNC\\'+name[2:] if name.startswith('\\\\') else '\\\\?\\'+name
        handle=self.api.CreateFileW(name,0x80,7,None,3,0x200000,None)
        if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        try:
            attributes=(w.DWORD*2)()
            if not self.api.GetFileInformationByHandleEx(handle,9,attributes,ctypes.sizeof(attributes)):raise ctypes.WinError(ctypes.get_last_error())
            if attributes[0]&0x400:raise ValueError('Allocation observer refuses a reparse point')
            info=FileStandardInfo()
            if not self.api.GetFileInformationByHandleEx(handle,1,ctypes.byref(info),ctypes.sizeof(info)):raise ctypes.WinError(ctypes.get_last_error())
            if info.directory or info.allocated<0:raise ValueError('Expected a regular file allocation')
            identity=FileIdInfo()
            if not self.api.GetFileInformationByHandleEx(handle,18,ctypes.byref(identity),ctypes.sizeof(identity)):raise ctypes.WinError(ctypes.get_last_error())
            return info.allocated,(identity.volume,bytes(identity.identity))
        finally:self.api.CloseHandle(handle)


def directory_size(folder):
    start=time.monotonic();allocation=FileAllocation();pending=[str(folder)];seen=set()
    result=dict(files=0,logical_bytes=0,allocated_bytes=0,unique_files=0,sampling_partial=False,unmeasured_files=0)
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    try:
                        info=entry.stat(follow_symlinks=False)
                        if entry.is_symlink() or info.st_file_attributes&0x400:raise ValueError('Unexpected link in owned benchmark output')
                        if entry.is_dir(follow_symlinks=False):pending.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            result['files']+=1;result['logical_bytes']+=info.st_size
                            size,identity=allocation.information(entry.path)
                            if identity not in seen:
                                result['allocated_bytes']+=size;seen.add(identity);result['unique_files']+=1
                    except FileNotFoundError:result['sampling_partial']=True
                    except OSError:result['sampling_partial']=True;result['unmeasured_files']+=1
        except FileNotFoundError:result['sampling_partial']=True
        except OSError:result['sampling_partial']=True;result['unmeasured_files']+=1
    result['observation_seconds']=time.monotonic()-start
    return result


class CounterValue(ctypes.Structure):
    _fields_=[('status',w.DWORD),('value',ctypes.c_double)]


class PagingRates:
    paths=dict(pages_input_per_second=r'\Memory\Pages Input/sec',pages_output_per_second=r'\Memory\Pages Output/sec')
    def __init__(self):
        if os.name!='nt':raise OSError('Windows PDH required')
        self.api=ctypes.WinDLL('pdh',use_last_error=True);self.query=w.HANDLE();self.counters={}
        self.api.PdhOpenQueryW.argtypes=[w.LPCWSTR,ctypes.c_size_t,ctypes.POINTER(w.HANDLE)]
        self.api.PdhAddEnglishCounterW.argtypes=[w.HANDLE,w.LPCWSTR,ctypes.c_size_t,ctypes.POINTER(w.HANDLE)]
        self.api.PdhCollectQueryData.argtypes=[w.HANDLE]
        self.api.PdhGetFormattedCounterValue.argtypes=[w.HANDLE,w.DWORD,ctypes.POINTER(w.DWORD),ctypes.POINTER(CounterValue)]
        self.api.PdhCloseQuery.argtypes=[w.HANDLE]
        for name in ['PdhOpenQueryW','PdhAddEnglishCounterW','PdhCollectQueryData','PdhGetFormattedCounterValue','PdhCloseQuery']:getattr(self.api,name).restype=w.DWORD
        def check(code):
            if code:raise OSError('PDH status '+hex(code))
        try:
            check(self.api.PdhOpenQueryW(None,0,ctypes.byref(self.query)))
            for name,path in self.paths.items():
                counter=w.HANDLE();check(self.api.PdhAddEnglishCounterW(self.query,path,0,ctypes.byref(counter)));self.counters[name]=counter
            check(self.api.PdhCollectQueryData(self.query))
        except BaseException:self.close();raise

    def sample(self):
        status=self.api.PdhCollectQueryData(self.query)
        if status:return dict(available=False,collect_status=hex(status))
        values={};errors={}
        for name,counter in self.counters.items():
            value=CounterValue();status=self.api.PdhGetFormattedCounterValue(counter,0x200|0x8000,None,ctypes.byref(value))
            if status or value.status not in {0,1} or not math.isfinite(value.value) or value.value<0:
                errors[name]=dict(api_status=hex(status),counter_status=hex(value.status))
            else:values[name]=value.value
        return dict(available=not errors,values=values,errors=errors,scope='HOST_WIDE_NOT_ATTRIBUTABLE_TO_ECRA')

    def close(self):
        if self.query:self.api.PdhCloseQuery(self.query);self.query=w.HANDLE()
