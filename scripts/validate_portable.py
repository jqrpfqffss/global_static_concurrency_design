"""Real Windows acceptance of an assembled OR extracted ECRA bundle.

Runs with the bundled interpreter, stdlib only until dependency probes. Logs
every command, return code and output. A failed check never publishes the ZIP.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import traceback


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def file_hashes(bundle):
    return {p.relative_to(bundle).as_posix(): sha256(p) for p in sorted(bundle.rglob('*'))
            if p.is_file() and p.name != 'FILES.sha256.json' and '__pycache__' not in p.parts}


def pe_imports(path):
    """Read normal and delay PE import descriptors without a developer tool."""
    data = Path(path).read_bytes()
    if data[:2] != b'MZ':
        raise ValueError(f'Expected Windows PE: {path}')
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    if data[offset:offset+4] != b'PE\0\0':
        raise ValueError(f'Invalid PE header: {path}')
    machine, count = struct.unpack_from('<HH', data, offset+4)
    optional_size = struct.unpack_from('<H', data, offset+20)[0]
    optional = offset+24
    magic = struct.unpack_from('<H', data, optional)[0]
    directory = optional + (112 if magic == 0x20b else 96)
    image_base = struct.unpack_from('<Q' if magic == 0x20b else '<I', data, optional+(24 if magic == 0x20b else 28))[0]
    sections = []
    for i in range(count):
        at = optional + optional_size + i*40
        size, address, raw_size, raw = struct.unpack_from('<IIII', data, at+8)
        sections.append((address, max(size, raw_size), raw))

    def physical(rva):
        for address, size, raw in sections:
            if address <= rva < address+size:
                return raw+rva-address
        if rva < len(data):
            return rva
        raise ValueError(f'Invalid PE RVA {rva}: {path}')

    def name(rva):
        at = physical(rva)
        return data[at:data.index(b'\0', at)].decode('ascii').lower()

    imports = set()
    for index, stride, name_offset in ((1, 20, 12), (13, 32, 4)):
        rva, size = struct.unpack_from('<II', data, directory+index*8)
        if not rva:
            continue
        at = physical(rva)
        for cursor in range(at, at+size, stride):
            descriptor = data[cursor:cursor+stride]
            if not any(descriptor):
                break
            dll = struct.unpack_from('<I', descriptor, name_offset)[0]
            if index == 13 and not struct.unpack_from('<I', descriptor)[0] & 1:
                dll -= image_base
            imports.add(name(dll))
    return machine, sorted(imports)


def verify_pe_dependencies(bundle):
    system = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    windows_dlls = set(('kernel32 kernelbase ntdll user32 advapi32 shell32 ole32 oleaut32 ws2_32 crypt32 bcrypt '
        'winhttp wininet secur32 version shlwapi gdi32 comdlg32 comctl32 rpcrt4 usp10 psapi dbghelp imagehlp '
        'netapi32 userenv normaliz dwmapi uxtheme oleacc setupapi winmm iphlpapi wldap32 mswsock propsys mpr '
        'winspool urlmon dxgi d3d11 dbgeng dbgcore cabinet cryptbase powrprof msvcrt ucrtbase wintrust authz '
        'advpack ncrypt hid dnsapi pdh wtsapi32 cfgmgr32 imm32 netutils msi').split())
    shared = [bundle/'runtime', bundle/'tools/cmake/bin', bundle/'tools/ninja',
              bundle/'tools/mingw/bin', bundle/'tools/mingw/opt/bin', bundle/'tools/arm-gcc/bin']
    evidence = {}
    for path in sorted(bundle.rglob('*')):
        if path.suffix.lower() not in {'.exe', '.dll', '.pyd'}:
            continue
        machine, imports = pe_imports(path)
        resolved = {}
        for dll in imports:
            if dll.startswith(('api-ms-', 'ext-ms-')):
                resolved[dll] = 'Windows API set'
                continue
            # VC++ redistributables are NOT part of Windows. They must be in
            # the package even if the development PC has them in System32.
            system_allowed = dll.removesuffix('.dll') in windows_dlls
            locations = [path.parent, *shared]
            found = next((p/dll for p in locations if (p/dll).is_file()), None)
            if found is None and system_allowed:
                folder = 'SysWOW64' if machine == 0x14c else 'System32'
                if (system/folder/dll).is_file():
                    found = system/folder/dll
            if found is None:
                raise ValueError(f'Missing runtime DLL {dll}, imported by {path}; include its matching redistributable runtime')
            if found.is_relative_to(bundle):
                dep_machine, _ = pe_imports(found)
                if dep_machine != machine:
                    raise ValueError(f'PE architecture mismatch: {path} -> {found}')
            resolved[dll] = str(found)
        evidence[path.relative_to(bundle).as_posix()] = dict(machine=hex(machine), imports=resolved)
    return evidence


class Acceptance:
    def __init__(self, bundle, work):
        self.bundle, self.work = bundle, work
        work.mkdir(parents=True, exist_ok=False)
        self.records = []
        self.report = dict(bundle=str(bundle), commands=self.records, result='RUNNING', opencode='NOT_TESTED')
        self.env = os.environ.copy()
        windows = Path(self.env.get('SystemRoot', r'C:\Windows'))
        self.env['PATH'] = os.pathsep.join(map(str, [bundle/'runtime', bundle/'tools/cmake/bin',
            bundle/'tools/ninja', bundle/'tools/mingw/bin', bundle/'tools/mingw/opt/bin', bundle/'tools/arm-gcc/bin',
            windows/'System32', windows, windows/'System32/Wbem', windows/'System32/WindowsPowerShell/v1.0']))
        self.env['ECRA_PORTABLE_ROOT'] = str(bundle)
        self.env['ECRA_CONFIG_HOME'] = str(bundle/'config')
        self.env['PYTHONDONTWRITEBYTECODE'] = '1'
        from ecra.portable import build_path
        tool_root = Path(build_path(bundle))
        self.env['PATH'] = os.pathsep.join(build_path(Path(p)) for p in self.env['PATH'].split(os.pathsep))
        # Remove compiler/include injection from the developer environment.
        for key in ('PYTHONPATH','PYTHONHOME','CC','CXX','ASM','CFLAGS','CXXFLAGS','LDFLAGS','CPATH',
                    'C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','LIBRARY_PATH','GCC_EXEC_PREFIX','COMPILER_PATH',
                    'CMAKE_GENERATOR','CMAKE_MAKE_PROGRAM','CMAKE_TOOLCHAIN_FILE','INCLUDE','LIB'):
            self.env.pop(key, None)
        self.cmake = tool_root/'tools/cmake/bin/cmake.exe'
        self.make = tool_root/'tools/mingw/bin/mingw32-make.exe'
        self.python = tool_root/'runtime/python.exe'
        self.gcc = tool_root/'tools/mingw/bin/gcc.exe'
        self.gpp = tool_root/'tools/mingw/bin/g++.exe'
        self.arm = tool_root/'tools/arm-gcc/bin/arm-none-eabi-gcc.exe'
        self.report['tool_root_alias'] = str(tool_root)

    def save(self):
        (self.work/'acceptance.json').write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')

    def command(self, label, args, allowed=(0,), cwd=None):
        args = list(map(str, args))
        # cmd.exe parses /c itself, rather than the Microsoft C argv rules.
        # Passing the last argument through list2cmdline would insert literal
        # backslash-quotes and fail on both ASCII and Unicode space paths.
        invocation = (subprocess.list2cmdline(args[:-1]) + ' ' + args[-1]
                      if Path(args[0]).name.lower() == 'cmd.exe' and args[-2].lower() == '/c' else args)
        proc = subprocess.run(invocation, cwd=cwd or self.work, env=self.env, capture_output=True,
                              encoding='utf-8', errors='replace', timeout=600)
        record = dict(label=label, command=args, cwd=str(cwd or self.work), exit_code=proc.returncode)
        if isinstance(invocation,str):
            record['windows_command_line'] = invocation
        log = self.work/(f'{len(self.records):02d}-' + re.sub(r'[^a-zA-Z0-9_-]', '_', label) + '.log')
        log.write_text(proc.stdout + '\nSTDERR:\n' + proc.stderr, encoding='utf-8')
        record['log'] = str(log)
        self.records.append(record)
        self.save()
        print(f'{label}: exit {proc.returncode}', flush=True)
        if proc.returncode not in allowed:
            raise ValueError(f'{label} failed: exit {proc.returncode}; {log}\n{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}')
        return proc.stdout + proc.stderr

    def versions(self):
        lock = json.loads((self.bundle/'portable-lock.json').read_text(encoding='utf-8-sig'))
        actual = self.command('Python', [self.python, '--version']).strip()
        if actual != 'Python ' + lock['versions']['python']:
            raise ValueError(f'Wrong Python version: {actual}')
        if Path(sys.executable).resolve() != self.python.resolve():
            raise ValueError(f'Validator must run with bundled Python: {sys.executable}')
        for name, pattern in lock['version_patterns'].items():
            exe = shutil.which(name, path=self.env['PATH'])
            if not exe or not Path(exe).resolve().is_relative_to(self.bundle):
                raise ValueError(f'PATH selected external/missing tool: {name}: {exe}')
            text = self.command(name, [exe, '--version']).strip().replace('\r\n','\n')
            if not re.search(pattern.replace('\\Z', '\\Z'), text):
                raise ValueError(f'Version/distribution mismatch: {name}: {text}')
        probe = """import sys, struct, json, sqlite3, ssl, multiprocessing, yaml, tempfile
from pathlib import Path
from ecra.manual_review import Ledger
from ecra.manual_server import make_server
from importlib.metadata import version
from clang import cindex
cindex.Index.create()
assert struct.calcsize('P') == 8
with tempfile.TemporaryDirectory() as folder:
    ledger = Ledger(Path(folder), 'portable-probe')
    assert ledger.history() == []
    ledger.backup(Path(folder)/'backup.sqlite3')
print(json.dumps({'python':sys.version.split()[0], 'PyYAML':version('PyYAML'), 'libclang':version('libclang'), 'libclang_loaded':True}))
"""
        text = self.command('Python dependencies and AST', [self.python, '-B','-c',probe])
        result = json.loads(text)
        if any(result[k] != v for k, v in lock['dependencies'].items()):
            raise ValueError(f'Dependency version mismatch: {result}')
        self.report['versions'] = result

    def inspect_build(self, build, compiler, make):
        from ecra.portable import read_cache
        cache = read_cache(build)
        for key, expected in (('CMAKE_C_COMPILER', compiler), ('CMAKE_MAKE_PROGRAM', make)):
            actual = Path(cache.get(key, '')).resolve()
            if actual != expected.resolve():
                raise ValueError(f'{key}: expected {expected}, actual {actual}')
        if cache.get('CMAKE_CXX_COMPILER'):
            expected = self.gpp if compiler == self.gcc else self.bundle/'tools/arm-gcc/bin/arm-none-eabi-g++.exe'
            if Path(cache['CMAKE_CXX_COMPILER']).resolve() != expected.resolve():
                raise ValueError(f'C++ compiler mixed with wrong toolchain: {cache}')
        database = json.loads((build/'compile_commands.json').read_text(encoding='utf-8'))
        if not database:
            raise ValueError(f'Empty compile database: {build}')
        from ecra.compilation import split_command
        for entry in database:
            command = entry.get('arguments') or split_command(entry['command'])
            path = Path(command[0]).resolve()
            if not path.is_relative_to(compiler.parent.resolve()):
                raise ValueError(f'External/wrong compiler in database: {command}')

    def ecra(self, command, config, *extra):
        line = subprocess.list2cmdline([str(self.bundle/'ecra.cmd'),command,'--config',str(config),*extra])
        return [os.environ.get('COMSPEC', r'C:\Windows\System32\cmd.exe'),'/d','/s','/c','"'+line+'"']

    def builds(self):
        from ecra.portable import build_path
        native = self.work/'native C C++ 中文'
        native.mkdir()
        (native/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
project(ecra_native C CXX)
add_executable(native main.c helper.cpp)
''', encoding='utf-8')
        (native/'main.c').write_text('int helper(void); int main(void){return helper()==42?0:1;}\n', encoding='utf-8')
        (native/'helper.cpp').write_text('''#include <thread>
#include <vector>
#include <numeric>
extern "C" int helper(void){
    std::vector<int> values{20,22}; int result=0;
    std::thread worker([&]{result=std::accumulate(values.begin(),values.end(),0);});
    worker.join(); return result;
}
''', encoding='utf-8')
        for generator, directory, make in (('MinGW Makefiles','mingw',self.make),
                ('Ninja','ninja',Path(build_path(self.bundle/'tools/ninja/ninja.exe')))):
            build = native/directory
            self.command(generator+' configure', [self.cmake,'-S',build_path(native),'-B',build_path(build),'-G',generator,
                '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DCMAKE_MAKE_PROGRAM:FILEPATH='+str(make),
                '-DCMAKE_C_COMPILER:FILEPATH='+str(self.gcc),'-DCMAKE_CXX_COMPILER:FILEPATH='+str(self.gpp)])
            self.inspect_build(build,self.gcc,make)
            self.command(generator+' build', [self.cmake,'--build',build_path(build),'--verbose'])
            self.command(generator+' execute', [build/'native.exe'])
        firmware = self.work/'STM32 Cortex M3 中文'
        firmware.mkdir()
        (firmware/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
project(ecra_stm32 C CXX ASM)
add_executable(firmware main.c helper.cpp startup.S)
target_compile_options(firmware PRIVATE -mcpu=cortex-m3 -mthumb -ffreestanding -ffunction-sections -fdata-sections)
target_compile_definitions(firmware PRIVATE STM32F103xB USE_HAL_DRIVER)
target_link_options(firmware PRIVATE -mcpu=cortex-m3 -mthumb -nostdlib -Wl,--gc-sections -T${CMAKE_SOURCE_DIR}/stm32.ld)
set_target_properties(firmware PROPERTIES SUFFIX ".elf")
''', encoding='utf-8')
        (firmware/'toolchain.cmake').write_text('''set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)
set(CMAKE_C_COMPILER arm-none-eabi-gcc)
set(CMAKE_CXX_COMPILER arm-none-eabi-g++)
set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
''', encoding='utf-8')
        (firmware/'main.c').write_text('''#include <stdint.h>
volatile uint32_t shared_count;
int main(void){for(;;){shared_count++;}}
void TIM2_IRQHandler(void){shared_count++;}
''', encoding='utf-8')
        (firmware/'helper.cpp').write_text('extern "C" unsigned helper(unsigned n){return n+1;}\n', encoding='utf-8')
        (firmware/'startup.S').write_text('''.syntax unified
.cpu cortex-m3
.thumb
.section .isr_vector,"a",%progbits
.word 0x20005000
.word Reset_Handler
.section .text.Reset_Handler,"ax",%progbits
.thumb_func
.global Reset_Handler
Reset_Handler:
 bl main
 b .
''', encoding='utf-8')
        (firmware/'stm32.ld').write_text('''ENTRY(Reset_Handler)
MEMORY { FLASH(rx) : ORIGIN = 0x08000000, LENGTH = 64K
RAM(rwx) : ORIGIN = 0x20000000, LENGTH = 20K }
SECTIONS { .isr_vector : { KEEP(*(.isr_vector)) } > FLASH
.text : { *(.text*) *(.rodata*) } > FLASH
.data : { *(.data*) } > RAM AT> FLASH
.bss : { *(.bss*) *(COMMON) } > RAM }
''', encoding='utf-8')
        config = self.work/'fixture-semantics.json'
        data = dict(version=1,project=dict(root=str(firmware),chip='STM32F103',core='Cortex-M3'),
            analysis=dict(cmake=dict(build_dir='build/ecra',generator='MinGW Makefiles',build=True,clean_before_configure=True,
                toolchain_file='toolchain.cmake'),include_dirs=['.'],exclude_dirs=['build','.ecra'],
                auto_system_includes=True,expected_defines=['STM32F103xB','USE_HAL_DRIVER']),
            contexts=[dict(id='main',kind='MAIN',functions=['main'])], review=dict(enabled=False,command=['opencode']))
        config.write_text(json.dumps(data), encoding='utf-8')
        # Reproduce upgrades from unmarked/manual build trees. These stale paths
        # must survive both doctor and run while the real build uses a sibling.
        legacy = firmware/'build/ecra'
        legacy.mkdir(parents=True)
        (legacy/'keep.txt').write_text('existing user build', encoding='utf-8')
        (legacy/'CMakeCache.txt').write_text('CMAKE_GENERATOR:INTERNAL=Ninja\n', encoding='utf-8')
        (legacy/'compile_commands.json').write_text('["stale database"]', encoding='utf-8')
        legacy_files = {p.name: p.read_bytes() for p in legacy.iterdir()}
        build = firmware/'build/ecra-ecra'
        # Test the actual CMD launcher as well, including Chinese/space paths.
        help_text = self.command('ecra.cmd help', [os.environ.get('COMSPEC', r'C:\Windows\System32\cmd.exe'),
            '/d','/s','/c','""'+str(self.bundle/'ecra.cmd')+'" --help"'])
        for command in ('run','doctor','review','report','status','init','serve'):
            if command not in help_text:
                raise ValueError(f'CLI missing: {command}')
        self.command('ecra.cmd doctor configure only', self.ecra('doctor',config))
        self.inspect_build(build,self.arm,self.make)
        doctor = json.loads((firmware/'.ecra/doctor.json').read_text(encoding='utf-8'))
        if Path(doctor['compile_database']).resolve() != (build/'compile_commands.json').resolve():
            raise ValueError('Doctor did not use the isolated build database')
        stale = build/'stale-ecra-output.txt'
        stale.write_text('remove only ECRA output', encoding='utf-8')
        self.command('ecra.cmd run no review real ARM build and scan', self.ecra('run',config,'--no-review'), allowed=(2,))
        self.inspect_build(build,self.arm,self.make)
        if stale.exists() or {p.name: p.read_bytes() for p in legacy.iterdir()} != legacy_files:
            raise ValueError('Isolated build cleanup did not preserve the existing user build')
        image = build/'firmware.elf'
        header = image.read_bytes()[:20]
        if header[:4] != b'\x7fELF' or struct.unpack_from('<H',header,18)[0] != 40:
            raise ValueError(f'Not an ARM ELF firmware: {image}')
        facts = json.loads((firmware/'.ecra/facts.json').read_text(encoding='utf-8'))
        shared = next((v for v in facts['variables'] if v['name'] == 'shared_count'), None)
        if not shared or len(shared.get('writers',[])) < 2:
            raise ValueError('AST/global-variable/concurrent writer extraction regression')
        manual_probe = '''import sys, json, threading, http.client
from pathlib import Path
from ecra.manual_server import make_server
root, config = map(Path, sys.argv[1:])
with make_server(root, str(config)) as server:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    conn = http.client.HTTPConnection(*server.server_address, timeout=30)
    conn.request('GET', '/api/state')
    state = json.loads(conn.getresponse().read())
    assert state['valid'] and state['rows']
    record = state['rows'][0]
    data = dict(record, decision='CONFIRMED_RISK', reason='Portable acceptance', reviewer='validator', report_fingerprint=state['report_fingerprint'])
    conn.close()
    conn = http.client.HTTPConnection(*server.server_address, timeout=30)
    conn.request('POST', '/api/decision', json.dumps(data).encode(), {'Content-Type':'application/json', 'Origin':'http://'+server.authority, 'X-ECRA-Token':state['token']})
    response = conn.getresponse()
    saved = json.loads(response.read())
    assert response.status == 200, saved
    assert saved['progress']['counts']['CONFIRMED_RISK'] >= 1
    conn.close()
    server.shutdown()
    thread.join()
with make_server(root, str(config)) as restarted:
    assert any(row['decision']=='CONFIRMED_RISK' for row in restarted.app.refresh())
print('Manual review HTTP, SQLite WAL and restart: PASS')
'''
        self.command('Manual review persistence and HTTP', [self.python, '-B', '-c', manual_probe, str(firmware), str(config)])
        self.command('ecra.cmd review disabled interface', self.ecra('review',config),allowed=(2,))
        self.command('ecra.cmd report', self.ecra('report',config),allowed=(2,))
        status = json.loads(self.command('ecra.cmd status', self.ecra('status',config,'--json')))
        if not status.get('resumable'):
            raise ValueError(f'Scan not resumable: {status}')
        for filename in ('index.html','facts.db','reports/global_static_concurrency.json'):
            if not (firmware/'.ecra'/filename).is_file():
                raise ValueError(f'ECRA output missing: {filename}')
        if not image.is_file():
            raise ValueError('Firmware not linked')
        # build:false must configure/export without starting a build.
        data['analysis']['cmake'].update(build_dir='build/configure-only',build=False)
        config2 = self.work/'configure-only.json'
        config2.write_text(json.dumps(data), encoding='utf-8')
        self.command('ecra.cmd build false', self.ecra('run',config2,'--no-review'),allowed=(2,))
        if (firmware/'build/configure-only/firmware.elf').exists():
            raise ValueError('build:false unexpectedly built firmware')
        self.report['opencode'] = 'NOT_TESTED: external installation/provider required; review disabled interface passed'

    def run(self):
        try:
            for name in ('ecra.cmd','run_ecra.py','README.txt','VERSION.txt','portable-lock.json',
                         'config/semantics.yaml','config/review_context.md','config/concurrency_cases.md',
                         'manual-review.md','ecra/manual_review.py','ecra/manual_server.py','ecra/manual_ui.py',
                         'runtime/python.exe','runtime/python310.zip','runtime/python310._pth',
                         'runtime/msvcp140.dll','tools/cmake/bin/cmake.exe','tools/ninja/ninja.exe',
                         'tools/mingw/bin/gcc.exe','tools/mingw/bin/g++.exe','tools/mingw/bin/mingw32-make.exe',
                         'tools/arm-gcc/bin/arm-none-eabi-gcc.exe'):
                if not (self.bundle/name).is_file():
                    raise ValueError(f'Required deliverable missing: {name}')
            forbidden = {'opencode.exe','opencode.cmd','opencode.ps1','node.exe','npm.cmd'}
            for file in self.bundle.rglob('*'):
                if file.is_file() and file.name.lower() in forbidden:
                    raise ValueError(f'OpenCode/Node/npm must not be distributed: {file}')
            adapter = json.loads((self.bundle/'tools/mingw/make-utf8.json').read_text(encoding='utf-8'))
            if not adapter['non_resource_sections_unchanged'] or sha256(self.bundle/'tools/mingw/bin/mingw32-make.exe') != adapter['artifact_sha256']:
                raise ValueError('Make UTF-8 adaptation integrity failed')
            import importlib.util
            spec = importlib.util.spec_from_file_location('make_manifest_recipe',self.bundle/'tools/mingw/portable-make-utf8.py')
            recipe = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(recipe)
            if recipe.sections((self.bundle/'tools/mingw/bin/mingw32-make.exe').read_bytes()) != adapter['source_sections']:
                raise ValueError('GNU Make non-resource code sections differ from verified source')
            expected = json.loads((self.bundle/'FILES.sha256.json').read_text(encoding='utf-8'))
            actual = file_hashes(self.bundle)
            if actual != expected:
                changed = [k for k in expected.keys() | actual.keys() if expected.get(k) != actual.get(k)]
                raise ValueError(f'Bundle file integrity mismatch: {changed[:20]}')
            self.versions()
            deps = verify_pe_dependencies(self.bundle)
            (self.work/'pe-dependencies.json').write_text(json.dumps(deps,indent=2),encoding='utf-8')
            self.builds()
            self.report['result'] = 'PASS'
        except Exception as exc:
            self.report.update(result='FAIL',error=str(exc),traceback=traceback.format_exc())
            raise
        finally:
            self.save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--work',type=Path)
    parser.add_argument('--write-hashes',action='store_true')
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    if args.write_hashes:
        (bundle/'FILES.sha256.json').write_text(json.dumps(file_hashes(bundle),indent=2),encoding='utf-8')
        return
    if os.name != 'nt' or not args.work:
        parser.error('Windows and a new --work directory are required')
    # This file is also copied to the root of the deliverable.
    sys.path.insert(0,str(bundle))
    Acceptance(bundle,args.work.resolve()).run()


if __name__ == '__main__':
    main()
