"""Prove a CMake Makefiles target closure from the generated build graph."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

from .input_snapshot import read_consumed_text


def target_entries(root, build, database, generator, target, consumed):
    def read(path):
        return read_consumed_text(path, consumed)

    reply = build/'.cmake/api/v1/reply'

    def reply_object(ref):
        path = (reply/ref['jsonFile']).resolve()
        if not path.is_relative_to(reply.resolve()):
            raise ValueError('CMake File API 引用越界')
        return json.loads(read(path))

    def make_path(value):
        # CMake emits one Makefile2 prerequisite per line, including escaped spaces.
        return (build/value.replace(r'\ ', ' ').replace(r'\#', '#')).resolve()

    try:
        index = max(reply.glob('index-*.json'), key=lambda path: path.name)
        index = json.loads(index.read_text(encoding='utf-8'))
        model = reply_object(index['reply']['client-ecra']['codemodel-v2'])
        actual_generator = index['cmake']['generator']
        if (actual_generator['name'] != generator or actual_generator['multiConfig']
                or model['kind'] != 'codemodel' or model['version']['major'] != 2
                or Path(model['paths']['source']).resolve() != root.resolve()
                or Path(model['paths']['build']).resolve() != build):
            raise ValueError('CMake File API 的生成器或工程身份不一致')
        config, = model['configurations']
        matches = [row for row in config['targets'] if row['name'] == target]
        if len(matches) != 1:
            raise ValueError('当前 CMake 配置中没有唯一同名目标')
        selected = matches[0]
        directories = config['directories']

        def target_dir(row):
            return (build/directories[row['directoryIndex']]['build']/'CMakeFiles'/
                    (row['name']+'.dir')).resolve()

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
        by_output = defaultdict(list)
        # Makefile generators export output relative to the top-level binary
        # tree even when the compile command runs from a subdirectory.
        for row in rows:
            if not row.get('output'):
                raise ValueError('compile_commands.json 缺少对象输出字段')
            by_output[(build/row['output']).resolve()].append(row)

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
            description = reply_object(row)
            if description['id'] != row['id']:
                raise ValueError('CMake File API 的目标身份不一致')
            dependencies.update(dep['id'] for dep in description.get('dependencies', []))
            sources = Counter((root/source['path']).resolve() for source in description.get('sources', [])
                              if 'compileGroupIndex' in source)
            makefile = read(directory/'build.make').replace('\r\n', '\n').replace('\\\n', '')

            def objects(suffix):
                variable = re.escape(row['name']+suffix)
                values = re.findall(r'^'+variable+r' =([^\n]*)$', makefile, re.M)
                if len(values) > 1 or (values and not re.fullmatch(r'(?:[ \t]*"[^"\n]+")*[ \t]*', values[0])):
                    raise ValueError('无法识别对象规则: '+row['name']+suffix)
                return [(build/value).resolve() for value in re.findall(r'"([^"\n]+)"', values[0])] if values else []

            own_objects = ([(build/item['path']).resolve() for item in description.get('artifacts', [])]
                           if description['type'] == 'OBJECT_LIBRARY' else objects('_OBJECTS'))
            actual = Counter()
            for output in own_objects:
                if len(by_output[output]) != 1:
                    raise ValueError('对象缺少唯一编译命令: '+str(output))
                entry = by_output[output][0]
                if not output.is_relative_to(directory) or output in outputs:
                    raise ValueError('对象输出归属有歧义: '+str(output))
                actual[(Path(entry['directory'])/entry['file']).resolve()] += 1
                outputs.add(output)
            if actual != sources:
                raise ValueError('目标源码与实际对象编译命令不一致: '+row['name'])
            if own_objects:
                read(directory/'flags.make')
            if (directory/'link.txt').is_file():
                read(directory/'link.txt')
            external.update(objects('_EXTERNAL_OBJECTS'))

        if dependencies - {targets[directory]['id'] for directory in visited}:
            raise ValueError('Makefile2 闭包缺少 CMake File API 声明的目标依赖')
        if external - outputs:
            raise ValueError('链接对象缺少所选目标的编译命令: '+str(min(external - outputs)))
        if not outputs:
            raise ValueError('目标没有可解析编译单元')
        # Keep original command ordering, flags and output identities.
        entries = [row for row in rows if (build/row['output']).resolve() in outputs]
        selected_artifacts = reply_object(selected).get('artifacts', [])
        return entries, outputs | {(build/item['path']).resolve() for item in selected_artifacts}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f'{generator} 目标编译闭包无法校验，禁止回退混用全目标数据库: {target}\n{exc}') from exc
