"""Enable Windows' per-process UTF-8 code page on the bundled GNU Make.

Only the executable manifest is updated. Verify every non-resource PE section
is unchanged and preserve source/artifact SHA256 and original manifests. This
does not change GNU Make's implementation, version, thread model or imports.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET


def sections(data):
    pe = struct.unpack_from('<I',data,0x3c)[0]
    count = struct.unpack_from('<H',data,pe+6)[0]
    size = struct.unpack_from('<H',data,pe+20)[0]
    result = {}
    for index in range(count):
        at = pe+24+size+40*index
        name = data[at:at+8].rstrip(b'\0').decode('ascii')
        virtual_size, _, raw_size, raw = struct.unpack_from('<IIII',data,at+8)
        if not name.startswith('.rsrc'):
            result[name] = hashlib.sha256(data[raw:raw+min(virtual_size,raw_size)]).hexdigest()
    return result


def enable(path, report, expected_source_sha256):
    api = ctypes.WinDLL('kernel32',use_last_error=True)
    api.LoadLibraryExW.argtypes = [wintypes.LPCWSTR,wintypes.HANDLE,wintypes.DWORD]
    api.LoadLibraryExW.restype = wintypes.HMODULE
    api.FindResourceExW.argtypes = [wintypes.HMODULE,ctypes.c_void_p,ctypes.c_void_p,wintypes.WORD]
    api.FindResourceExW.restype = wintypes.HANDLE
    api.LoadResource.argtypes = [wintypes.HMODULE,wintypes.HANDLE]
    api.LoadResource.restype = wintypes.HANDLE
    api.SizeofResource.argtypes = [wintypes.HMODULE,wintypes.HANDLE]
    api.LockResource.argtypes = [wintypes.HANDLE]
    api.LockResource.restype = ctypes.c_void_p
    api.FreeLibrary.argtypes = [wintypes.HMODULE]
    api.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR,wintypes.BOOL]
    api.BeginUpdateResourceW.restype = wintypes.HANDLE
    api.UpdateResourceW.argtypes = [wintypes.HANDLE,ctypes.c_void_p,ctypes.c_void_p,wintypes.WORD,ctypes.c_void_p,wintypes.DWORD]
    api.EndUpdateResourceW.argtypes = [wintypes.HANDLE,wintypes.BOOL]
    language_callback = ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HMODULE,ctypes.c_void_p,ctypes.c_void_p,wintypes.WORD,wintypes.LPARAM)
    api.EnumResourceLanguagesW.argtypes = [wintypes.HMODULE,ctypes.c_void_p,ctypes.c_void_p,language_callback,wintypes.LPARAM]
    original = path.read_bytes()
    if hashlib.sha256(original).hexdigest() != expected_source_sha256.lower():
        raise ValueError(f'Unexpected upstream Make SHA256: {path}')
    module = api.LoadLibraryExW(str(path),None,0x22)
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())
    manifests = {}
    try:
        languages = []
        callback = language_callback(lambda handle,kind,name,lang,extra: languages.append(lang) or True)
        api.EnumResourceLanguagesW(module,24,1,callback,0)
        for lang in languages:
            info = api.FindResourceExW(module,24,1,lang)
            pointer = api.LockResource(api.LoadResource(module,info))
            manifests[lang] = ctypes.string_at(pointer,api.SizeofResource(module,info))
    finally:
        api.FreeLibrary(module)
    pending = []
    for lang, data in (manifests or {0: b'<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0"/>'}).items():
        root = ET.fromstring(data.rstrip(b'\0'))
        application = root.find('{urn:schemas-microsoft-com:asm.v3}application')
        if application is None:
            application = ET.SubElement(root,'{urn:schemas-microsoft-com:asm.v3}application')
        settings = application.find('{urn:schemas-microsoft-com:asm.v3}windowsSettings')
        if settings is None:
            settings = ET.SubElement(application,'{urn:schemas-microsoft-com:asm.v3}windowsSettings')
        tag = '{http://schemas.microsoft.com/SMI/2019/WindowsSettings}activeCodePage'
        page = settings.find(tag)
        if page is None:
            page = ET.SubElement(settings,tag)
        page.text = 'UTF-8'
        pending.append((lang,ET.tostring(root,encoding='utf-8',xml_declaration=True)))
    handle = api.BeginUpdateResourceW(str(path),False)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        for lang, data in pending:
            buffer = ctypes.create_string_buffer(data)
            if not api.UpdateResourceW(handle,24,1,lang,buffer,len(data)):
                raise ctypes.WinError(ctypes.get_last_error())
    except Exception:
        api.EndUpdateResourceW(handle,True)
        raise
    if not api.EndUpdateResourceW(handle,False):
        raise ctypes.WinError(ctypes.get_last_error())
    actual = path.read_bytes()
    if sections(original) != sections(actual):
        path.write_bytes(original)
        raise ValueError('Non-resource PE sections changed; upstream Make restored')
    result = dict(adapter='Windows activeCodePage UTF-8 manifest',source_sha256=hashlib.sha256(original).hexdigest(),
                  artifact_sha256=hashlib.sha256(actual).hexdigest(),non_resource_sections_unchanged=True,
                  source_sections=sections(original),
                  original_manifests={str(k):v.decode('utf-8-sig') for k,v in manifests.items()})
    report.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--make',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--expected-source-sha256',required=True)
    args = parser.parse_args()
    enable(args.make.resolve(),args.report.resolve(),args.expected_source_sha256)
