"""Read the selected Makefiles target's configure-time compilation records."""
from collections import Counter, defaultdict
import json
from pathlib import Path

from .cmake_file_api import FileAPI, TargetGraph
from .input_snapshot import read_consumed_text, record_consumed_file
from .path_io import filesystem_path, resolved_path
from .workspace import no_links


def target_entries(root, build, database, generator, target, consumed, *, graph=None, rows=None):
    """Cross-check object ownership, source multiplicity and actual compile commands."""
    try:
        if graph is None:
            graph = TargetGraph(FileAPI(root, build, consumed, generator), None)
        api = graph.api
        selected = graph.named(target)
        if rows is None:
            rows = json.loads(read_consumed_text(no_links(database), consumed))
        by_target = defaultdict(list)
        closure = graph.closure(selected)
        directories = {}
        for key, desc in closure.items():
            directory = graph.object_directory(desc)
            if directory in directories:
                raise ValueError(f'目标对象目录有歧义：{directory}')
            directories[directory] = key

        entries, outputs = [], set()
        for row in rows:
            if not row.get('output'):
                raise ValueError('compile_commands.json 缺少对象输出字段')
            output = api.build_path(row['output'])
            owners = [directories[parent] for parent in output.parents if parent in directories]
            if owners:
                if len(owners) != 1 or output in outputs:
                    raise ValueError(f'对象输出归属有歧义：{output}')
                by_target[owners[0]].append((row, output))
                outputs.add(output)
                entries.append(row)

        for directory, key in directories.items():
            desc = closure[key]
            compiled = by_target[key]
            sources = Counter(resolved_path(Path(row['directory'])/row['file']) for row, _ in compiled)
            if sources != graph.compiled_sources(desc):
                raise ValueError('目标源码与实际对象编译命令不一致：'+desc['name'])
            if desc['type'] == 'OBJECT_LIBRARY' and {obj for _, obj in compiled} != set(api.artifacts(desc)):
                raise ValueError('对象库产物与编译记录不一致：'+desc['name'])
            for source in desc.get('sources', []):
                path = resolved_path(root/source['path'])
                if ('compileGroupIndex' not in source and path.suffix.lower() in {'.o', '.obj'}
                        and path not in outputs):
                    raise ValueError(f'链接对象缺少所选目标的编译命令：{path}')
            # Bind the generated rules used by the actual build to the snapshot.
            # Target relationships come exclusively from the selected codemodel.
            for name in ('build.make', 'flags.make', 'link.txt'):
                path = no_links(directory/name)
                if filesystem_path(path).is_file():
                    record_consumed_file(path, consumed)
        for path in (build/'Makefile', build/'CMakeFiles/Makefile2'):
            record_consumed_file(no_links(path), consumed)
        if not entries:
            raise ValueError('目标没有可解析编译单元')
        return entries, outputs | set(api.artifacts(selected))
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f'{generator} 目标编译闭包无法校验：{target}\n{exc}') from exc
