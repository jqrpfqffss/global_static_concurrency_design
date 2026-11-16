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
        return '当前生成器未启用自动目标'
    if not cmake_build_args_allow_auto_target(settings.get('build_args', [])):
        return 'build_args 中有目标、原生工具参数或可能改变构建范围的选项'
    return None


def firmware_candidate(api, variant):
    """Identify the executable in this project and distinguish it from its file."""
    config = api.configuration(variant)
    references = {row['id']: row for row in config['targets']}
    if len(references) != len(config['targets']):
        raise ValueError('CMake codemodel 目标身份重复')
    targets = {key: api.target(row) for key, row in references.items()}
    edges = {key: {row['id'] for row in target.get('dependencies', [])} for key, target in targets.items()}
    if any(deps - targets.keys() for deps in edges.values()):
        raise ValueError('CMake codemodel 目标依赖缺少对应记录')
    candidates = [key for key, target in targets.items() if target['type'] == 'EXECUTABLE']
    if len(candidates) != 1:
        reason = '没有可执行目标' if not candidates else '配置有多个可执行目标：' + ', '.join(
            sorted(targets[key]['name'] for key in candidates))
        raise AutoTargetUnavailable(reason)
    key, = candidates
    target, row = targets[key], references[key]
    directory = api.build_path(target['paths']['build'])
    owner = config['projects'][row['projectIndex']]
    if 'parentIndex' in owner or target.get('isGeneratorProvided') or not target.get('compileGroups'):
        raise AutoTargetUnavailable('可执行目标没有当前根工程的固件编译证据')
    for path in {api.build/'CTestTestfile.cmake', directory/'CTestTestfile.cmake'}:
        if filesystem_path(path).exists():
            read_consumed_text(no_links(path), api.consumed)
            raise AutoTargetUnavailable('配置包含 CTest 测试，无法区分唯一固件意图')
    name = target['name']
    if not name or name.startswith('-') or any(ch in name for ch in '\r\n\x00'):
        raise ValueError('CMake codemodel 目标名称无效')
    artifacts = [path for path in api.artifacts(target) if path.name == target.get('nameOnDisk')]
    if len(artifacts) != 1:
        raise AutoTargetUnavailable('没有唯一的可执行链接产物')

    def reachable(first):
        result, pending = set(), [first]
        while pending:
            node = pending.pop()
            if node not in result:
                result.add(node)
                pending.extend(edges[node])
        return result

    upstream = reachable(key)
    # Only a separate downstream utility may be elided. Upstream utilities
    # (generators etc.) stay in the real build, whatever their type/name.
    downstream = set()
    for other, desc in targets.items():
        if other in upstream or desc['type'] != 'UTILITY' or desc.get('isGeneratorProvided'):
            continue
        if key not in reachable(other):
            raise AutoTargetUnavailable('配置还有无法证明是固件下游的独立自定义目标')
        downstream.add(api.build_path(Path(desc['paths']['build'])/'CMakeFiles'/desc['name']))
    return target, artifacts[0], downstream


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


def driver_index(args):
    return int(Path(args[0]).stem.lower() in {'ccache', 'sccache'})


def scope_identity(rows, api, analysis, *, generator, targeted, effective=True):
    """Compare commands as a multiset, retaining object and variant identity."""
    from .compilation import (expand_response, linked_input_filters, linked_input_selected,
                              excluded, source_language, split_command)
    from .common import relative

    filters = linked_input_filters(api.root, analysis.get('build_closure', {}))
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
        if effective and (not linked_input_selected(source, directory, row, original, filters,
                                                   api.build if targeted and generator == 'MinGW Makefiles' else None)
                          or excluded(relative(source, api.root), analysis.get('exclude', []))):
            continue
        args = expand_response(original, directory, consumed_inputs=api.consumed)
        if not args or len(args) <= driver_index(args) or '-c' not in args or source_language(source, args) is None:
            raise AutoTargetUnavailable('编译数据库包含暂不支持的编译命令格式')
        output_arg = args.index('-o')+1 if '-o' in args else len(args)
        if output_arg >= len(args):
            raise AutoTargetUnavailable('编译命令无法对应对象输出')
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
            raise AutoTargetUnavailable('编译命令的实际源码无法与数据库对应')
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
                raise AutoTargetUnavailable('Ninja 清单包含无法绑定的动态子清单')
            pending.append(api.build_path(name))


def verify_ninja_default(api, raw, default, artifact, downstream):
    def by_output(rows):
        result = {}
        for row in rows:
            directory = api.build_path(row['directory'])
            path = api.build_path(directory/row['output'])
            if path in result:
                raise ValueError(f'Ninja 目标规则有重复的输出: {path}')
            result[path] = row
        return result

    selected, all_outputs = by_output(raw), by_output(default)
    if artifact not in selected:
        raise ValueError('Ninja 目标入口没有 codemodel 声明的链接产物')
    if any(all_outputs.get(path) != row for path, row in selected.items()):
        raise AutoTargetUnavailable('候选的真实编译/链接规则不是默认构建的一部分')
    if all_outputs.keys() - selected.keys() - downstream:
        raise AutoTargetUnavailable('默认构建还有无法归为固件下游的独立规则')
