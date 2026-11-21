"""Read CMake's replies for the actual source and build trees."""
import json
from collections import Counter
from pathlib import Path

from .input_snapshot import read_consumed_text
from .path_io import filesystem_path, resolved_path
from .workspace import no_links


class AutoTargetUnavailable(Exception):
    """A valid configuration for which automatic selection is not proven."""


def request(build, *objects):
    query = no_links(build/'.cmake/api/v1/query/client-ecra')
    filesystem_path(query).mkdir(parents=True, exist_ok=True)
    for name in objects:
        filesystem_path(no_links(query/name)).touch()


def latest_index(build):
    reply = no_links(build/'.cmake/api/v1/reply')
    path = max(filesystem_path(reply).glob('index-*.json'), default=None)
    return no_links(path) if path is not None else None


class FileAPI:
    def __init__(self, root, build, consumed, generator=None):
        self.root, self.build = resolved_path(root), build
        self.consumed = consumed
        try:
            self.index = latest_index(build)
            if self.index is None:
                raise ValueError('缺少本轮 CMake File API 索引')
            self.reply = self.index.parent
            data = self.read(self.index)
            actual = data['cmake']['generator']
            if generator and (actual['name'] != generator or actual['multiConfig'] is not False):
                raise ValueError('CMake File API 生成器身份不一致')
            self.references = data['reply']['client-ecra']
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f'CMake File API 索引无法校验: {exc}') from exc

    def read(self, path):
        result = json.loads(read_consumed_text(path, self.consumed))
        if not isinstance(result, dict):
            raise ValueError(f'CMake File API 对象无效: {path}')
        return result

    def reference(self, ref):
        name = ref['jsonFile']
        if not isinstance(name, str) or not name.endswith('.json'):
            raise ValueError('CMake File API 引用无效')
        path = no_links(self.reply/name)
        if path.parent != self.reply:
            raise ValueError(f'CMake File API 引用越界: {name}')
        return self.read(path)

    def object(self, kind, major, *, optional=False):
        query = f'{kind}-v{major}'
        ref = self.references[query]
        if optional and ref == {'error': 'unknown query file'}:
            return None
        data = self.reference(ref)
        if any(row['kind'] != kind or row['version']['major'] != major for row in (ref, data)):
            raise ValueError(f'CMake File API 对象版本不符: {query}')
        return data

    def check_paths(self, data):
        if (resolved_path(data['paths']['source']) != self.root
                or resolved_path(data['paths']['build']) != self.build):
            raise ValueError('CMake File API 源码/构建目录身份不一致')

    def inputs(self):
        data = self.object('cmakeFiles', 1)
        self.check_paths(data)
        paths = []
        for row in data['inputs']:
            path = resolved_path(self.root/row['path'])
            if row.get('isGenerated') and not path.is_relative_to(self.build):
                raise ValueError(f'CMake 生成输入越界: {path}')
            paths.append(path)
            read_consumed_text(path, self.consumed, errors='replace')
        if not paths:
            raise ValueError('缺少 CMake 配置输入')
        return paths

    def configuration(self, expected=None):
        data = self.object('codemodel', 2)
        self.check_paths(data)
        config, = data['configurations']
        if expected is not None and config['name'] != expected:
            raise ValueError('CMake codemodel 构建变体身份不一致')
        return config

    def target(self, row):
        target = self.reference(row)
        if target['id'] != row['id'] or target['name'] != row['name']:
            raise ValueError('CMake File API 的目标身份不一致')
        self.build_path(target['paths']['build'])
        self.artifacts(target)
        return target

    def build_path(self, value):
        # CMake can spell the physical build via a Windows tool-side alias.
        path = resolved_path(self.build/value)
        if not path.is_relative_to(self.build):
            raise ValueError(f'CMake 目标构建证据越界: {value}')
        return path

    def artifacts(self, target):
        return [self.build_path(row['path']) for row in target.get('artifacts', [])]


class TargetGraph:
    """One configure generation and configuration, keyed by codemodel IDs."""

    def __init__(self, api, variant):
        self.api = api
        self.config = api.configuration(variant)
        rows = self.config['targets']
        self.refs = {row['id']: row for row in rows}
        if len(self.refs) != len(rows):
            raise ValueError('CMake codemodel 目标身份重复')
        self.descriptions = {}

    def description(self, key):
        if key not in self.refs:
            raise ValueError(f'CMake codemodel 依赖缺少目标记录：{key}')
        if key not in self.descriptions:
            try:
                self.descriptions[key] = self.api.target(self.refs[key])
            except (KeyError, TypeError, IndexError, OSError, ValueError) as exc:
                raise ValueError(f'CMake File API 目标 {key} 无法解析：{exc}') from exc
        return self.descriptions[key]

    def named(self, name):
        matches = [key for key, ref in self.refs.items() if ref['name'] == name]
        if len(matches) == 1:
            return self.description(matches[0])
        if matches:
            raise ValueError(f'CMake 逻辑目标名不唯一：{name}')
        owners = []
        for key in self.refs:
            desc = self.description(key)
            if (name == desc.get('nameOnDisk') or any(
                    name in {item['path'], Path(item['path']).name} for item in desc.get('artifacts', []))):
                owners.append(desc['name'])
        message = f'未找到 CMake 目标：{name}。'
        if len(owners) == 1:
            message += f'当前配置中，该文件是目标 {owners[0]} 的构建产物。请将 target 设置为 {owners[0]}，或清空 target 使用自动识别。'
        elif owners:
            message += '当前配置中有多个同名产物，所属目标：' + '、'.join(sorted(owners)) + '。'
        raise ValueError(message + '本次未执行构建。')

    def closure(self, target):
        visited, pending = {}, [target['id']]
        while pending:
            key = pending.pop()
            if key not in visited:
                desc = visited[key] = self.description(key)
                pending.extend(dep['id'] for dep in desc.get('dependencies', []))
        return visited

    def object_directory(self, target):
        return self.api.build_path(Path(target['paths']['build'])/'CMakeFiles'/(target['name']+'.dir'))

    def compiled_sources(self, target):
        sources = target.get('sources', [])
        listed = Counter()
        for group_index, group in enumerate(target.get('compileGroups', [])):
            for i in group['sourceIndexes']:
                if (type(i) is not int or not 0 <= i < len(sources)
                        or sources[i].get('compileGroupIndex') != group_index):
                    raise ValueError(f'CMake 编译组与源码索引不一致：{target["name"]}')
                listed[i] += 1
        if listed != Counter(i for i, row in enumerate(sources) if 'compileGroupIndex' in row):
            raise ValueError(f'CMake 编译组缺少源码记录：{target["name"]}')
        return Counter(resolved_path(self.api.root/sources[i]['path']) for i in listed)
