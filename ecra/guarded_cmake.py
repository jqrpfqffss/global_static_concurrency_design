"""Read-only source CMake builds with sticky namespace-change detection.

Only newly owned private output directories receive a low-integrity label.
Original source, Git, configuration and tool directories are never relabelled.
"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import time
import threading
import uuid

from .workspace import no_links


class InputWatch:
    """A sticky kernel signal detects changes even when bytes are restored."""
    def __init__(self):
        if os.name != 'nt': raise ValueError('未提交CMake的只读构建保护目前需要Windows')
        self.api = ctypes.WinDLL('kernel32',use_last_error=True)
        self.api.FindFirstChangeNotificationW.argtypes = [wintypes.LPCWSTR,wintypes.BOOL,wintypes.DWORD]
        self.api.FindFirstChangeNotificationW.restype = wintypes.HANDLE
        self.api.FindCloseChangeNotification.argtypes = [wintypes.HANDLE]
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE,wintypes.DWORD]
        self.api.CreateFileW.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        self.api.CreateFileW.restype = wintypes.HANDLE
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.directories, self.files, self.ancestors = {}, {}, {}
    def directory(self, path):
        path = no_links(path)
        if any(path == other or path.is_relative_to(other) for other in self.directories): return
        handle = self.api.FindFirstChangeNotificationW(str(path),True,0x1|0x2|0x4|0x8|0x10|0x100)
        if handle in (None,ctypes.c_void_p(-1).value): raise ctypes.WinError(ctypes.get_last_error())
        self.directories[path] = handle
        # Keep every path component from being renamed out and replaced while
        # the recursive notification remains attached to the old object.
        for ancestor in (path,*path.parents):
            if ancestor in self.ancestors:continue
            locked=self.api.CreateFileW(str(ancestor),0x80000000,0x3,None,3,0x02000000,None)
            if locked in (None,ctypes.c_void_p(-1).value):raise ctypes.WinError(ctypes.get_last_error())
            self.ancestors[ancestor]=locked
    def file(self, path):
        path = no_links(path)
        if path in self.files: return
        handle = self.api.CreateFileW(str(path),0x80000000,0x1,None,3,0x80,None)
        if handle in (None,ctypes.c_void_p(-1).value): raise ctypes.WinError(ctypes.get_last_error())
        self.files[path] = handle
    def check(self):
        from .scan_stop import check_stop
        check_stop()
        for path, handle in self.directories.items():
            status = self.api.WaitForSingleObject(handle,0)
            if status == 0: raise ValueError('CMake输入目录在固定期间发生变化（即使已恢复也不接受）：'+str(path))
            if status != 258: raise ctypes.WinError(ctypes.get_last_error())
    def close(self):
        for handle in self.directories.values(): self.api.FindCloseChangeNotification(handle)
        for handle in self.files.values(): self.api.CloseHandle(handle)
        for handle in self.ancestors.values(): self.api.CloseHandle(handle)
        self.directories.clear(); self.files.clear(); self.ancestors.clear()
    def __enter__(self): return self
    def __exit__(self,*exc): self.close()


def require_protected_source(root):
    """A pre-existing low-labelled source cannot receive a read-only promise."""
    from .studio.write_guard import Windows
    api = Windows(); pointer = ctypes.c_void_p
    get = api.adv.GetNamedSecurityInfoW
    get.argtypes = [wintypes.LPWSTR,ctypes.c_int,wintypes.DWORD,pointer,pointer,pointer,
                    ctypes.POINTER(pointer),ctypes.POINTER(pointer)]
    get.restype = wintypes.DWORD
    ace_fn = api.adv.GetAce; ace_fn.argtypes = [pointer,wintypes.DWORD,ctypes.POINTER(pointer)]
    for base, dirs, files in os.walk(root,followlinks=False):
        for path in [Path(base),*(Path(base)/name for name in dirs+files)]:
            path = no_links(path); sacl = pointer(); descriptor = pointer()
            try:
                status = get(str(path),1,0x10,None,None,None,ctypes.byref(sacl),ctypes.byref(descriptor))
                if status: raise ctypes.WinError(status)
                if not sacl: continue  # Windows treats unlabelled files as medium.
                count = ctypes.c_ushort.from_address(sacl.value+4).value
                for index in range(count):
                    ace = pointer()
                    if not ace_fn(sacl,index,ctypes.byref(ace)): raise ctypes.WinError(ctypes.get_last_error())
                    kind = ctypes.c_ubyte.from_address(ace.value).value
                    flags = ctypes.c_ubyte.from_address(ace.value+1).value
                    if kind != 0x11 or flags & 8: continue
                    sid = ace.value+8; length = api.adv.GetSidSubAuthorityCount(sid)[0]
                    rid = api.adv.GetSidSubAuthority(sid,length-1)[0]
                    mask = ctypes.c_uint32.from_address(ace.value+4).value
                    if rid < 0x2000 or not mask & 1:
                        raise ValueError('原源码完整性标签不能保证只读，拒绝构建且不改变原权限：'+str(path))
            finally:
                if descriptor: api.kernel.LocalFree(descriptor)


class BuildExecutor:
    def __init__(self, namespace, source, watch):
        from .studio.write_guard import create_private_directory
        self.namespace = create_private_directory(namespace,source_root=source)
        self.source=source
        self.watch = watch; self.calls = []
        self.temp = self.namespace/'temp'; self.temp.mkdir()
        self.traces = []
        self.audit=no_links(self.namespace.parent/('working-cmake-audit-'+uuid.uuid4().hex));self.audit.mkdir()
        require_protected_source(self.audit)
    def __call__(self, argv, *, cwd=None, env=None, timeout=300, input=None, stdin=None, **options):
        if options or input is not None or stdin not in (None,subprocess.DEVNULL):
            raise ValueError('只读CMake执行器不接受未证明的子进程选项')
        from .portable import resolved_executable
        from .studio.write_guard import GuardedProcess
        from .studio.process_budget import ProcessBudget
        from .common import write_json
        self.watch.check()
        cwd = Path(cwd or os.getcwd()); original = list(map(str,argv))
        executable = no_links(resolved_executable(original[0],cwd))
        actual = [str(executable),*original[1:]]
        trace=None;pipe=None
        if '-S' in actual and executable.stem.lower() == 'cmake':
            trace = self.audit/('trace-'+str(len(self.calls))+'.jsonl')
            actual += ['--trace-expand','--trace-format=json-v1']
            self.traces.append(trace)
        child_env = dict(os.environ if env is None else env)
        child_env.update(TEMP=str(self.temp),TMP=str(self.temp),TMPDIR=str(self.temp))
        folder = self.namespace/('command-'+str(len(self.calls))); folder.mkdir()
        budget = ProcessBudget(16*1024**3); process = None; start = time.monotonic()
        row = dict(command=actual,cwd=str(cwd),complete=False); self.calls.append(row)
        try:
            with (folder/'stdout.log').open('xb') as output, (folder/'stderr.log').open('xb') as error:
                if trace is not None:pipe=_TracePipe(trace)
                process = GuardedProcess(actual,cwd=cwd,env=child_env,log=output,stderr_log=error if pipe is None else pipe.writer)
                if pipe is not None:pipe.writer.close()
                budget.assign(process); process.resume()
                while process.poll() is None:
                    self.watch.check()
                    if pipe is not None and pipe.error is not None:raise pipe.error
                    stop = os.environ.get('ECRA_JOB_STOP_FILE')
                    if stop and Path(stop).is_file(): raise KeyboardInterrupt('只读构建已停止，原固件保留')
                    if time.monotonic()-start > timeout: raise subprocess.TimeoutExpired(actual,timeout)
                    time.sleep(.05)
                code = process.wait(timeout=30)
                row.update(complete=True,exit_code=code,resources=budget.sample())
                if pipe is not None:
                    budget.close();pipe.finish()
            self.watch.check()
            if code==0 and '-S' in actual and executable.stem.lower()=='cmake':
                from .portable import read_cache
                from .working_cmake import audit_trace,input_path
                build=input_path(actual[actual.index('-B')+1])
                # Reject unproved generated commands before Ninja can run any
                # target, rather than discovering them after the build.
                audit_trace(self,dict(cmake_cache=read_cache(build)),self.source)
            return subprocess.CompletedProcess(original,code,
                (folder/'stdout.log').read_text('utf-8',errors='replace'),
                (trace if trace is not None else folder/'stderr.log').read_text('utf-8',errors='replace'))
        finally:
            budget.close()
            if process is not None: process.close()
            try:
                if pipe is not None:pipe.finish()
            except BaseException as exc:
                row['trace_error']=type(exc).__name__+': '+str(exc);raise
            finally:
                row['seconds'] = time.monotonic()-start
                write_json(folder/'execution.json',row)


class _TracePipe:
    """The Low CMake process can append pipe bytes but cannot erase the audit.

    A redirect file inside its writable build tree could be truncated by the
    very CMake script being audited. Only the parent writes this Medium file.
    """
    def __init__(self,path):
        reader,writer=os.pipe();self.writer=os.fdopen(writer,'wb',buffering=0);self.error=None
        def drain():
            try:
                with os.fdopen(reader,'rb',buffering=0) as source,Path(path).open('xb') as target:
                    for block in iter(lambda:source.read(65536),b''):target.write(block)
                    target.flush();os.fsync(target.fileno())
            except BaseException as exc:self.error=exc
        self.thread=threading.Thread(target=drain,daemon=True);self.thread.start()
    def finish(self):
        self.writer.close();self.thread.join(timeout=10)
        if self.thread.is_alive():raise ValueError('CMake审计管道未结束；保留日志且禁止准入')
        if self.error is not None:raise self.error
