"""Conservative, configure-time proof for an omitted CMake target."""
from collections import Counter
import os
from pathlib import Path
import re
import subprocess

from .cmake_file_api import AutoTargetUnavailable
from .input_snapshot import read_consumed_text, record_consumed_file
from .path_io import filesystem_path, resolved_path
from .portable import resolved_executable, tool_environment
from .scan_stop import check_stop
from .workspace import no_links


def eligibility(analysis, project, build_firmware, protected):
    from .config import cmake_build_args_allow_auto_target
    settings = analysis['cmake']
    if protected or analysis.get('git_diff', {}).get('include_uncommitted'):
        return '受保护的工作输入沿用原构建计划'
    if not settings.get('build', True) or not build_firmware:
        return '本轮只配置，保持完整编译数据库'
    if project.get('cm4_enabled') or project.get('concurrency_model', 'single_core_preemptive') != 'single_core_preemptive':
        return '多核或非单核模型沿用原构建计划'
    if settings.get('generator', 'Ninja') not in {'Ninja', 'MinGW Makefiles'}:
        raise ValueError('自动固件构建需要 Ninja 或 MinGW Makefiles；本次未执行构建')
    args = settings.get('build_args', [])
    if not cmake_build_args_allow_auto_target(args):
        # Keep the independent build_args mode only for a user-directed build.
        if any(arg in {'--target', '-t'} and i+1 < len(args) and not args[i+1].startswith('-')
               for i, arg in enumerate(args)) or ('--' in args and args[args.index('--')+1:]
                and all(not arg.startswith('-') for arg in args[args.index('--')+1:])):
            return '使用 build_args 中显式指定的构建计划'
        raise ValueError('build_args 无法与自动目标安全组合；请使用 target 指定构建范围。本次未执行构建')
    return None


def select_firmware(graph, analysis, generator, full, closure, candidates, run):
    """Qualify each executable independently, before dispatching any build."""
    api = graph.api
    matches = []
    for key in graph.refs:
        target = graph.description(key)
        if target['type'] != 'EXECUTABLE':
            continue
        name = target['name']
        if not name or name.startswith('-') or any(ch in name for ch in '\r\n\x00'):
            raise ValueError('CMake codemodel 目标名称无效')
        try:
            artifact, evidence, linked_objects = firmware_evidence(graph, target, analysis)
            entries, files, rules, command = closure(target)
            identities = scope_identity(entries, api, generator=generator, targeted=True)
            if generator == 'Ninja':
                expected = Counter()
                for dependency in graph.closure(target).values():
                    expected.update(graph.compiled_sources(dependency))
                actual = Counter()
                for (source, _, _, _), count in identities.items():
                    actual[source] += count
                if expected != actual:
                    raise ValueError(f'{name} 的 File API 源码与 Ninja 闭包编译命令不一致')
                exported = [row for row in full if not row.get('output') or
                            api.build_path(Path(row['directory'])/row['output']) in files]
                original = scope_identity(exported, api, generator=generator, targeted=False)
                if identities - original:
                    raise ValueError(f'Ninja 目标 {name} 的编译参数与配置数据库不一致')
            # Build-only executables can legitimately use a host compiler.
            # Keep their rows in the build closure, but certify the image with
            # the compiler invocations that produced its own or linked objects.
            own = graph.object_directory(target)
            firmware_rows = [row for row in identities if row[2].is_relative_to(own) or row[2] in linked_objects]
            if linked_objects - {row[2] for row in firmware_rows}:
                raise ValueError(f'{name} 的链接对象缺少实际编译记录')
            machine = verify_compilers(api, target, firmware_rows, run)
        except AutoTargetUnavailable as exc:
            candidates.append(dict(target=name, eligible=False, reason=str(exc)))
            continue
        except (KeyError, IndexError, TypeError, OSError, ValueError) as exc:
            candidates.append(dict(target=name, eligible=False, reason=str(exc)))
            raise ValueError(f'目标 {name} 的编译或链接证据无法校验：{exc}。本次未执行构建。') from exc
        reason = f'{machine} 裸机链接，编译证据：' + '、'.join(
            f'{item["target"]} ({item["type"]}, {item["compile_entries"]})' for item in evidence)
        candidates.append(dict(target=name, eligible=True, reason=reason, compile_evidence=evidence))
        matches.append((name, entries, files, rules, command, artifact, reason))
    if len(matches) != 1:
        reason = '多个合格固件目标' if matches else '没有合格的可执行固件目标'
        detail = '；'.join(row['target']+'：'+row['reason'] for row in candidates)
        raise ValueError('。'.join(filter(None, (reason, detail, '请配置真实的 CMake target', '本次未执行构建。'))))
    return matches[0]


def firmware_evidence(graph, target, analysis):
    """Only a compiled source or an object actually consumed by the link is evidence."""
    api = graph.api
    key = target['id']
    owner = graph.config['projects'][graph.refs[key]['projectIndex']]
    if 'parentIndex' in owner or target.get('isGeneratorProvided'):
        raise AutoTargetUnavailable('目标不属于当前根工程')
    directory = api.build_path(target['paths']['build'])
    for path in {api.build/'CTestTestfile.cmake', directory/'CTestTestfile.cmake'}:
        if filesystem_path(path).exists():
            read_consumed_text(no_links(path), api.consumed)
            raise AutoTargetUnavailable('配置包含 CTest 测试，无法区分唯一固件意图')
    artifacts = [path for path in api.artifacts(target) if path.name == target.get('nameOnDisk')]
    if len(artifacts) != 1:
        raise AutoTargetUnavailable('没有唯一的可执行链接产物')
    linker_evidence(api, target, artifacts[0], analysis)

    linked_inputs = {resolved_path(api.root/source['path']) for source in target.get('sources', [])
                     if 'compileGroupIndex' not in source}
    contributors = []
    linked_objects = set()
    for dep in graph.closure(target).values():
        if dep['id'] != key:
            if dep['type'] != 'OBJECT_LIBRARY':
                continue
            used = linked_inputs.intersection(api.artifacts(dep))
            if not used:
                continue
            linked_objects.update(used)
        sources = graph.compiled_sources(dep)
        same_project = graph.refs[dep['id']]['projectIndex'] == graph.refs[key]['projectIndex']
        if sources and (same_project or any(path.is_relative_to(api.root) or path.is_relative_to(api.build)
                                            for path in sources)):
            contributors.append(dict(target=dep['name'], type=dep['type'], compile_entries=sum(sources.values())))
    if not contributors:
        raise AutoTargetUnavailable('没有可与自身源码或实际链接对象对应的工程编译组')
    return artifacts[0], sorted(contributors, key=lambda row: row['target']), linked_objects


def linker_evidence(api, target, artifact, analysis):
    from .compilation import split_command
    from .managed_build_closure import managed_artifact_paths

    flags = []
    for fragment in target.get('link', {}).get('commandFragments', []):
        if fragment['role'] != 'flags':
            continue
        for arg in split_command('ecra-dummy ' + fragment['fragment'])[1:]:
            if arg.startswith('-Wl,'):
                flags.extend(arg[4:].split(','))
            elif arg != '-Xlinker':
                flags.append(arg)
    scripts, maps = [], []
    for index, arg in enumerate(flags):
        for option, found in (('-T', scripts), ('--script', scripts), ('-Map', maps)):
            if arg == option and index+1 < len(flags):
                found.append(flags[index+1])
            elif arg.startswith(option+'='):
                found.append(arg[len(option)+1:])
            elif option == '-T' and arg.startswith('-T') and not arg.startswith(('-Ttext', '-Tdata', '-Tbss')):
                found.append(arg[2:])
    if not scripts and not ('-nostdlib' in flags and any(
            arg in {'-e', '--entry'} or arg.startswith('--entry=') for arg in flags)):
        raise AutoTargetUnavailable('链接命令没有可确认的裸机固件入口或链接脚本')
    directory = api.build_path(target['paths']['build'])
    for value in scripts:
        path = resolved_path(directory/value)
        if filesystem_path(path).is_file():
            record_consumed_file(path, api.consumed)
    bound = managed_artifact_paths(api.root, analysis, api.build)
    if bound is not None:
        actual_maps = {resolved_path(directory/value) for value in maps}
        if bound['elf'] != artifact or bound['map'] not in actual_maps:
            raise AutoTargetUnavailable('候选链接产物未证明与既有 ELF/MAP 约束一致')


def verify_compilers(api, target, identities, run):
    toolchains = api.object('toolchains', 1, optional=True)
    if toolchains is None:
        raise AutoTargetUnavailable('当前 CMake 不提供工具链 File API')
    tools = {row['language']: row['compiler'] for row in toolchains['toolchains']}
    driver = tools.get(target.get('link', {}).get('language'), {})
    if driver.get('id') != 'GNU' or not driver.get('path'):
        raise AutoTargetUnavailable('当前固件链接工具链不在自动识别范围')
    compiler = resolved_executable(driver['path'], api.build)
    expected = {resolved_executable(row['path'], api.build) for row in tools.values() if row.get('path')}
    actual = {resolved_executable(args[driver_index(args)], directory) for _, directory, _, args in identities}
    if not actual or actual - expected:
        raise AutoTargetUnavailable('实际编译驱动与固件链接工具链无法对应')
    for launcher in {resolved_executable(args[0], directory)
                     for _, directory, _, args in identities if driver_index(args)}:
        record_consumed_file(launcher, api.consumed)
    machines = set()
    for path in sorted(actual | {compiler}):
        check_stop()
        record_consumed_file(path, api.consumed)
        try:
            proc = run([str(path), '-dumpmachine'], cwd=api.build, env=tool_environment(), timeout=20)
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f'读取真实编译器目标超时: {path}') from exc
        if proc.returncode or not re.fullmatch(r'[\w.+-]+-(?:none-eabi(?:hf)?|none-elf|unknown-elf|elf)', proc.stdout.strip()):
            raise AutoTargetUnavailable('实际编译器不是可证明的裸机交叉工具链')
        machines.add(proc.stdout.strip())
    if len(machines) != 1:
        raise AutoTargetUnavailable('闭包存在不同的实际编译器目标平台')
    return machines.pop()


def driver_index(args):
    return int(Path(args[0]).stem.lower() in {'ccache', 'sccache'})


def scope_identity(rows, api, *, generator, targeted):
    """Compare commands as a multiset, retaining object and variant identity."""
    from .compilation import expand_response, source_language, split_command

    identities = Counter()
    for row in rows:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k] for k in ('directory', 'file')):
            raise ValueError('CMake 编译数据库条目无效')
        directory = api.build_path(row['directory'])
        source = resolved_path(directory/row['file'])
        output_dir = api.build if generator == 'MinGW Makefiles' else directory
        row_output = api.build_path(output_dir/row['output']) if row.get('output') else None
        original = row.get('arguments') or split_command(row.get('command', ''))
        if not original or not all(isinstance(arg, str) for arg in original):
            raise ValueError(f'CMake 编译命令无效: {source}')
        args = expand_response(original, directory, consumed_inputs=api.consumed)
        if not args or len(args) <= driver_index(args) or '-c' not in args or source_language(source, args) is None:
            raise ValueError('编译数据库包含暂不支持的编译命令格式')
        output_arg = args.index('-o')+1 if '-o' in args else len(args)
        if output_arg >= len(args):
            raise ValueError('编译命令无法对应对象输出')
        output = api.build_path(directory/args[output_arg])
        if os.name == 'nt' and generator == 'Ninja' and not targeted and row_output not in {None, output}:
            # Some CMake versions export an unquoted Ninja object path for
            # a subdirectory with spaces. Only join those tokens when the
            # resulting operand equals the separately exported object path.
            width = len(row['output'].split())
            end = output_arg + width
            if width > 1 and api.build_path(directory/' '.join(args[output_arg:end])) == row_output:
                args[output_arg:end] = [str(row_output)]
                output = row_output
        if row_output is not None and output != row_output:
            raise ValueError(f'CMake 编译命令与数据库的对象输出身份不一致: {output}')
        args[output_arg] = str(output)
        driver = driver_index(args)
        args[driver] = str(resolved_executable(args[driver], directory))
        source_arg = args.index('-c')+1
        if source_arg == len(args) or resolved_path(directory/args[source_arg]) != source:
            raise ValueError('编译命令的实际源码无法与数据库对应')
        args[source_arg] = str(source)
        if generator == 'Ninja' and targeted:
            # Ninja adds depfile bookkeeping, absent from CMake's exported
            # command. Normalize only its known object-bound triplet.
            for i in range(1, len(args)-4):
                if args[i:i+2] != ['-MD', '-MT'] or args[i+3] != '-MF':
                    continue
                depfile = resolved_path(directory/args[i+4])
                if resolved_path(directory/args[i+2]) == output and depfile == Path(str(output)+'.d'):
                    del args[i:i+5]
                    break
        identities[source, directory, output, tuple(args)] += 1
    return identities


def ninja_graph_evidence(api):
    """Bind both the manifest and its generated includes before using Ninja."""
    pending, seen = [api.build/'build.ninja'], set()
    while pending:
        path = no_links(pending.pop())
        if path in seen:
            continue
        seen.add(path)
        data = read_consumed_text(path, api.consumed)
        for value in re.findall(r'^(?:include|subninja) ([^\r\n]+)', data, re.M):
            # CMake's single-config generator emits literal includes.
            name = re.sub(r'\$([ :$])', lambda m: m[1], value)
            if '$' in name or not name:
                raise ValueError('Ninja 清单包含无法绑定的动态子清单')
            pending.append(api.build_path(name))
