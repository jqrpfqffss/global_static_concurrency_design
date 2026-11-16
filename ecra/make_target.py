"""Prove a CMake Makefiles target closure from the generated build graph."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

from .cmake_file_api import AutoTargetUnavailable, FileAPI
from .input_snapshot import read_consumed_text
from .path_io import filesystem_path, resolved_path
from .workspace import no_links


def target_entries(root, build, database, generator, target, consumed, *, auto=False):
    def read(path):
        return read_consumed_text(no_links(path), consumed)

    def make_path(value):
        # CMake emits one Makefile2 prerequisite per line, including escaped spaces.
        return api.build_path(value.replace(r'\ ', ' ').replace(r'\#', '#'))

    try:
        api = FileAPI(root, build, consumed, generator)
        config = api.configuration()
        matches = [row for row in config['targets'] if row['name'] == target]
        if len(matches) != 1:
            raise ValueError('当前 CMake 配置中没有唯一同名目标')
        selected = matches[0]
        directories = config['directories']

        def target_dir(row):
            return api.build_path(Path(directories[row['directoryIndex']]['build'])/'CMakeFiles'/
                                  (row['name']+'.dir'))

        targets = {target_dir(row): row for row in config['targets']}
        if len(targets) != len(config['targets']):
            raise ValueError('目标构建目录有歧义')

        # File API describes the sources per target. Makefile2 is authoritative
        # for which target rules the generator actually invokes.
        graph = defaultdict(set)
        read(build/'Makefile')
        rules = read(build/'CMakeFiles/Makefile2').replace('\r\n', '\n')
        for rule, prerequisite in re.findall(r'^([^\t#\n].*?\.dir)/all:[ \t]*(.*)$',
                                              rules, re.M):
            edges = graph[make_path(rule)]
            if prerequisite:
                if not prerequisite.endswith('.dir/all'):
                    raise ValueError('无法识别 Makefile2 目标依赖: '+prerequisite)
                edges.add(make_path(prerequisite.removesuffix('/all')))

        rows = json.loads(read(database))
        if auto and rows and all(isinstance(row, dict) and 'output' not in row for row in rows):
            raise AutoTargetUnavailable('当前 CMake Makefiles 不导出对象输出字段')
        by_output = defaultdict(list)
        # Makefile generators export output relative to the top-level binary
        # tree even when the compile command runs from a subdirectory.
        for row in rows:
            if not row.get('output'):
                raise ValueError('compile_commands.json 缺少对象输出字段')
            by_output[api.build_path(row['output'])].append(row)

        aliases = re.findall(r'^'+re.escape(target)+r':[ \t]+(.+)/rule$', rules, re.M)
        if len(aliases) != 1 or make_path(aliases[0]) != target_dir(selected):
            raise ValueError('Makefile2 目标入口与 CMake File API 不一致')
        pending = [target_dir(selected)]
        visited, outputs, external, dependencies = set(), set(), set(), set()
        while pending:
            directory = pending.pop()
            if directory in visited:
                continue
            if not directory.is_relative_to(build) or directory not in graph:
                raise ValueError('Makefile2 缺少可验证的目标规则: '+str(directory))
            visited.add(directory)
            pending.extend(graph[directory])
            row = targets[directory]
            description = api.target(row)
            dependencies.update(dep['id'] for dep in description.get('dependencies', []))
            sources = Counter(resolved_path(root/source['path']) for source in description.get('sources', [])
                              if 'compileGroupIndex' in source)
            makefile = read(directory/'build.make').replace('\r\n', '\n').replace('\\\n', '')

            def objects(label):
                # CMake rewrites punctuation in the Make variable name and can
                # number collisions. Its preceding target comment is explicit.
                comment = re.escape(f'# {label} for target {row["name"]}')
                assignments = re.findall(r'^'+comment+r'\n([^\n]*)', makefile, re.M)
                if not assignments:
                    return []
                assignment = re.fullmatch(r'[^\s=]+[ \t]*=((?:[ \t]*"[^"\n]+")*[ \t]*)', assignments[0])
                if len(assignments) != 1 or assignment is None:
                    raise ValueError(f'无法识别对象规则: {row["name"]} / {label}')
                return [api.build_path(value) for value in re.findall(r'"([^"\n]+)"', assignment[1])]

            own_objects = (api.artifacts(description)
                           if description['type'] == 'OBJECT_LIBRARY' else objects('Object files'))
            actual = Counter()
            for output in own_objects:
                if len(by_output[output]) != 1:
                    raise ValueError('对象缺少唯一编译命令: '+str(output))
                entry = by_output[output][0]
                if not output.is_relative_to(directory) or output in outputs:
                    raise ValueError('对象输出归属有歧义: '+str(output))
                actual[resolved_path(Path(entry['directory'])/entry['file'])] += 1
                outputs.add(output)
            if actual != sources:
                raise ValueError('目标源码与实际对象编译命令不一致: '+row['name'])
            if own_objects:
                read(directory/'flags.make')
            if filesystem_path(directory/'link.txt').is_file():
                read(directory/'link.txt')
            external.update(objects('External object files'))

        if dependencies - {targets[directory]['id'] for directory in visited}:
            raise ValueError('Makefile2 闭包缺少 CMake File API 声明的目标依赖')
        if external - outputs:
            raise ValueError('链接对象缺少所选目标的编译命令: '+str(min(external - outputs)))
        if not outputs:
            raise ValueError('目标没有可解析编译单元')
        if auto:
            # The selected link must already be part of ALL. Check the real
            # Makefile2 edges, including nested directory aggregates.
            defaults = defaultdict(set)
            for rule, prerequisite in re.findall(r'^([^\t#\n:]+):[ \t]+([^\n]+/all)$', rules, re.M):
                if rule == 'all' or rule.endswith('/all'):
                    key = make_path(rule.removesuffix('/all'))
                    defaults[key].add(make_path(prerequisite.removesuffix('/all')))

            def reachable(first, edges):
                result, pending = set(), [first]
                while pending:
                    node = pending.pop()
                    if node not in result:
                        result.add(node)
                        pending.extend(edges.get(node, ()))
                return result

            selected_dir = target_dir(selected)
            all_targets = reachable(build/'all', {**defaults, **graph}) & targets.keys()
            if selected_dir not in all_targets:
                raise AutoTargetUnavailable('候选不在 Makefiles 的默认构建中')
            for directory in sorted(all_targets - visited):
                if (api.target(targets[directory])['type'] != 'UTILITY'
                        or selected_dir not in reachable(directory, graph)):
                    raise AutoTargetUnavailable('默认构建还有不属于该固件闭包的独立目标')
        # Keep original command ordering, flags and output identities.
        entries = [row for row in rows if api.build_path(row['output']) in outputs]
        return entries, outputs | set(api.artifacts(api.target(selected)))
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f'{generator} 目标编译闭包无法校验，禁止回退混用全目标数据库: {target}\n{exc}') from exc
