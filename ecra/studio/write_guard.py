"""Windows low-integrity write guard; NOT integrated with formal scans yet.

This is an execution prerequisite, not proof of input/build equivalence. It only
labels a newly created private directory, never a firmware/install directory.
Normal medium-integrity files remain readable and cannot be written by the
low-integrity child. An explicit inherited-handle list avoids leaking unrelated
parent handles. Unsupported hosts fail; there is no unrestricted fallback.
"""
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import subprocess

from ..workspace import no_links


class SidAttributes(ctypes.Structure):
    _fields_=[('sid',ctypes.c_void_p),('attributes',w.DWORD)]


class Startup(ctypes.Structure):
    _fields_=[('cb',w.DWORD),('reserved',w.LPWSTR),('desktop',w.LPWSTR),('title',w.LPWSTR),
        *[(name,w.DWORD) for name in ['x','y','xsize','ysize','xchars','ychars','fill','flags']],
        ('show',w.WORD),('reserved2size',w.WORD),('reserved2',ctypes.c_void_p),
        ('stdin',w.HANDLE),('stdout',w.HANDLE),('stderr',w.HANDLE)]


class StartupEx(ctypes.Structure):
    _fields_=[('startup',Startup),('attributes',ctypes.c_void_p)]


class ProcessInfo(ctypes.Structure):
    _fields_=[('process',w.HANDLE),('thread',w.HANDLE),('pid',w.DWORD),('tid',w.DWORD)]


class Windows:
    def __init__(self):
        if os.name!='nt':raise ValueError('Windows write guard requires Windows')
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True);self.adv=ctypes.WinDLL('advapi32',use_last_error=True)
        def define(dll,name,arguments,result=w.BOOL):
            fn=getattr(dll,name);fn.argtypes=arguments;fn.restype=result;return fn
        pointer=ctypes.c_void_p;handle_pointer=ctypes.POINTER(w.HANDLE)
        define(self.kernel,'GetCurrentProcess',[],w.HANDLE)
        define(self.kernel,'CloseHandle',[w.HANDLE])
        define(self.kernel,'LocalFree',[pointer],pointer)
        define(self.kernel,'DuplicateHandle',[w.HANDLE,w.HANDLE,w.HANDLE,handle_pointer,w.DWORD,w.BOOL,w.DWORD])
        define(self.kernel,'GetExitCodeProcess',[w.HANDLE,ctypes.POINTER(w.DWORD)])
        define(self.kernel,'WaitForSingleObject',[w.HANDLE,w.DWORD],w.DWORD)
        define(self.kernel,'TerminateProcess',[w.HANDLE,w.UINT])
        define(self.kernel,'ResumeThread',[w.HANDLE],w.DWORD)
        define(self.kernel,'InitializeProcThreadAttributeList',[pointer,w.DWORD,w.DWORD,ctypes.POINTER(ctypes.c_size_t)])
        define(self.kernel,'UpdateProcThreadAttribute',[pointer,w.DWORD,ctypes.c_size_t,pointer,ctypes.c_size_t,pointer,pointer])
        define(self.kernel,'DeleteProcThreadAttributeList',[pointer],None)
        define(self.adv,'OpenProcessToken',[w.HANDLE,w.DWORD,handle_pointer])
        define(self.adv,'CreateRestrictedToken',[w.HANDLE,w.DWORD,w.DWORD,pointer,w.DWORD,pointer,w.DWORD,pointer,handle_pointer])
        define(self.adv,'ConvertStringSidToSidW',[w.LPCWSTR,ctypes.POINTER(pointer)])
        define(self.adv,'GetLengthSid',[pointer],w.DWORD)
        define(self.adv,'SetTokenInformation',[w.HANDLE,ctypes.c_int,pointer,w.DWORD])
        define(self.adv,'GetTokenInformation',[w.HANDLE,ctypes.c_int,pointer,w.DWORD,ctypes.POINTER(w.DWORD)])
        define(self.adv,'GetSidSubAuthorityCount',[pointer],ctypes.POINTER(ctypes.c_ubyte))
        define(self.adv,'GetSidSubAuthority',[pointer,w.DWORD],ctypes.POINTER(w.DWORD))
        define(self.adv,'ConvertStringSecurityDescriptorToSecurityDescriptorW',[w.LPCWSTR,w.DWORD,ctypes.POINTER(pointer),pointer])
        define(self.adv,'GetSecurityDescriptorSacl',[pointer,ctypes.POINTER(w.BOOL),ctypes.POINTER(pointer),ctypes.POINTER(w.BOOL)])
        define(self.adv,'SetNamedSecurityInfoW',[w.LPWSTR,ctypes.c_int,w.DWORD,pointer,pointer,pointer,pointer],w.DWORD)
        define(self.adv,'CreateProcessAsUserW',[w.HANDLE,w.LPCWSTR,w.LPWSTR,pointer,pointer,w.BOOL,w.DWORD,pointer,w.LPCWSTR,ctypes.POINTER(StartupEx),ctypes.POINTER(ProcessInfo)])

    @staticmethod
    def check(value):
        if not value:raise ctypes.WinError(ctypes.get_last_error())
        return value

    def integrity(self,token):
        size=w.DWORD();self.adv.GetTokenInformation(token,25,None,0,ctypes.byref(size))
        buffer=ctypes.create_string_buffer(size.value)
        self.check(self.adv.GetTokenInformation(token,25,buffer,size,ctypes.byref(size)))
        sid=SidAttributes.from_buffer(buffer).sid
        count=self.adv.GetSidSubAuthorityCount(sid)[0]
        return self.adv.GetSidSubAuthority(sid,count-1)[0]

    def low_token(self):
        original=w.HANDLE();restricted=w.HANDLE();sid=ctypes.c_void_p()
        try:
            self.check(self.adv.OpenProcessToken(self.kernel.GetCurrentProcess(),0x8b,ctypes.byref(original)))
            if self.integrity(original)<0x2000:raise ValueError('The write-guard broker must have ordinary medium or higher integrity')
            self.check(self.adv.CreateRestrictedToken(original,1,0,None,0,None,0,None,ctypes.byref(restricted)))
            self.check(self.adv.ConvertStringSidToSidW('S-1-16-4096',ctypes.byref(sid)))
            length=self.adv.GetLengthSid(sid);buffer=ctypes.create_string_buffer(ctypes.sizeof(SidAttributes)+length)
            label=SidAttributes.from_buffer(buffer);label.sid=ctypes.addressof(buffer)+ctypes.sizeof(SidAttributes);label.attributes=0x20
            ctypes.memmove(label.sid,sid,length)
            self.check(self.adv.SetTokenInformation(restricted,25,buffer,len(buffer)))
            if self.integrity(restricted)!=0x1000:raise ValueError('Low integrity token was not established')
            result=restricted.value;restricted.value=None;return result
        finally:
            if original:self.kernel.CloseHandle(original)
            if restricted:self.kernel.CloseHandle(restricted)
            if sid:self.kernel.LocalFree(sid)


def create_private_directory(path,*,source_root):
    """Only change a fresh owned output directory, never an existing tree."""
    api=Windows();path=no_links(path)
    if path.exists():raise FileExistsError('Existing directories must never be relabelled')
    source_root=no_links(source_root);installation=Path(__file__).resolve().parents[2]
    if not source_root.is_dir():raise ValueError('Original source root must exist')
    if any(path==root or path.is_relative_to(root) or root.is_relative_to(path) for root in [source_root,installation]):
        raise ValueError('Private write scope overlaps original source or software installation')
    path.mkdir(parents=True,exist_ok=False)
    descriptor=ctypes.c_void_p()
    try:
        api.check(api.adv.ConvertStringSecurityDescriptorToSecurityDescriptorW('S:(ML;OICI;NW;;;LW)',1,ctypes.byref(descriptor),None))
        present=w.BOOL();defaulted=w.BOOL();sacl=ctypes.c_void_p()
        api.check(api.adv.GetSecurityDescriptorSacl(descriptor,ctypes.byref(present),ctypes.byref(sacl),ctypes.byref(defaulted)))
        error=api.adv.SetNamedSecurityInfoW(str(path),1,0x10,None,None,None,sacl)
        if error:raise ctypes.WinError(error)
        (path/'.ecra-write-guard').write_text('LOW_INTEGRITY_PRIVATE_DIRECTORY_V1\n',encoding='ascii')
        return path
    finally:
        if descriptor:api.kernel.LocalFree(descriptor)


class GuardedProcess:
    """Starts suspended. Caller assigns its Job before explicitly resuming."""
    def __init__(self,argv,*,cwd,env,log):
        import msvcrt
        self.api=api=Windows();self.args=list(map(str,argv));self._handle=None;self._thread=None;self.returncode=None
        executable=Path(self.args[0])
        if not executable.is_absolute() or not executable.is_file():raise ValueError('Use an existing absolute executable path')
        token=api.low_token();duplicates=[];attributes=None;attributes_ready=False
        try:
            def duplicate(raw):
                handle=w.HANDLE();api.check(api.kernel.DuplicateHandle(api.kernel.GetCurrentProcess(),raw,api.kernel.GetCurrentProcess(),ctypes.byref(handle),0,True,2))
                duplicates.append(handle.value);return handle.value
            with open(os.devnull,'rb') as null:
                stdin=duplicate(msvcrt.get_osfhandle(null.fileno()))
            stdout=duplicate(msvcrt.get_osfhandle(log.fileno()))
            size=ctypes.c_size_t();api.kernel.InitializeProcThreadAttributeList(None,1,0,ctypes.byref(size))
            attributes=ctypes.create_string_buffer(size.value)
            api.check(api.kernel.InitializeProcThreadAttributeList(attributes,1,0,ctypes.byref(size)));attributes_ready=True
            handles=(w.HANDLE*2)(stdin,stdout)
            api.check(api.kernel.UpdateProcThreadAttribute(attributes,0,0x20002,handles,ctypes.sizeof(handles),None,None))
            startup=StartupEx();startup.startup.cb=ctypes.sizeof(StartupEx);startup.attributes=ctypes.addressof(attributes)
            startup.startup.flags=0x100|1;startup.startup.show=0
            startup.startup.stdin=stdin;startup.startup.stdout=stdout;startup.startup.stderr=stdout
            command=ctypes.create_unicode_buffer(subprocess.list2cmdline(self.args))
            environment=ctypes.create_unicode_buffer('\0'.join(key+'='+value for key,value in sorted(env.items(),key=lambda item:item[0].upper()))+'\0\0')
            info=ProcessInfo();flags=0x4|0x400|0x80000|0x8000000  # suspended, Unicode env, explicit handle list, no window
            api.check(api.adv.CreateProcessAsUserW(token,str(executable),command,None,None,True,flags,environment,str(cwd),ctypes.byref(startup),ctypes.byref(info)))
            self._handle=info.process;self._thread=info.thread;self.pid=info.pid
        finally:
            if attributes_ready:api.kernel.DeleteProcThreadAttributeList(attributes)
            for handle in duplicates:api.kernel.CloseHandle(handle)
            api.kernel.CloseHandle(token)

    def resume(self):
        if self._thread:
            if self.api.kernel.ResumeThread(self._thread)==0xffffffff:raise ctypes.WinError(ctypes.get_last_error())
            self.api.kernel.CloseHandle(self._thread);self._thread=None

    def poll(self):
        if self.returncode is None:
            if self.api.kernel.WaitForSingleObject(self._handle,0)==0:
                code=w.DWORD();self.api.check(self.api.kernel.GetExitCodeProcess(self._handle,ctypes.byref(code)));self.returncode=code.value
        return self.returncode

    def wait(self,timeout=None):
        result=self.api.kernel.WaitForSingleObject(self._handle,0xffffffff if timeout is None else max(0,int(timeout*1000)))
        if result==258:raise subprocess.TimeoutExpired(self.args,timeout)
        if result!=0:raise ctypes.WinError(ctypes.get_last_error())
        return self.poll()

    def terminate(self):
        if self.poll() is None:self.api.check(self.api.kernel.TerminateProcess(self._handle,1))

    def close(self):
        if self._thread:self.api.kernel.CloseHandle(self._thread);self._thread=None
        if self._handle:self.api.kernel.CloseHandle(self._handle);self._handle=None
