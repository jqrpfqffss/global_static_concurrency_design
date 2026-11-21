"""Configure and link an ARM image whose executable compiles no sources."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from ecra.cmake_file_api import FileAPI
from ecra.common import read_json, write_json
from ecra.compilation import cmake_build_directory, prepare
from ecra.git_diff import build_arguments, check_isolated_tree


@pytest.fixture
def firmware(tmp_path):
    if not all(shutil.which(tool) for tool in ('cmake', 'git', 'arm-none-eabi-gcc')):
        pytest.skip('requires CMake, Git and ARM GCC')
    root = tmp_path / 'src'
    root.mkdir()
    (root / '.gitignore').write_text('/output/\n', encoding='utf-8')
    (root / 'main.c').write_text('int value(void); int main(void) {return value();}\n')
    (root / 'value.c').write_text('int value(void) {return 7;}\n')
    (root / 'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
set(CMAKE_C_COMPILER arm-none-eabi-gcc)
project(objects C)
add_library(objects OBJECT main.c value.c)
if(LINK_OBJECTS)
  add_executable(app_elf)
  target_link_libraries(app_elf PRIVATE objects)
else()
  add_executable(app_elf $<TARGET_OBJECTS:objects>)
endif()
target_link_options(app_elf PRIVATE -nostdlib -Wl,-e,main)
set_target_properties(app_elf PROPERTIES OUTPUT_NAME mfc_v2 SUFFIX .axf)
add_custom_target(app_M2 ALL
  COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_SOURCE_DIR}/output
  COMMAND ${CMAKE_COMMAND} -E touch ${CMAKE_SOURCE_DIR}/output/package-ran
  DEPENDS app_elf VERBATIM)
''', encoding='utf-8')
    for args in (['init', '-q'], ['add', '.'], ['-c', 'user.name=fixture', '-c',
                 'user.email=fixture@example.invalid', 'commit', '-qm', 'firmware']):
        subprocess.run(['git', *args], cwd=root, check=True)
    config = dict(version=1, project=dict(root=str(root)), review=dict(enabled=False),
                  analysis=dict(output=dict(location='custom', custom_dir=str(tmp_path/'data')),
                                cmake=dict(build=True, clean_before_configure=True)))
    return root, config


@pytest.mark.parametrize('generator', ['MinGW Makefiles', 'Ninja'])
@pytest.mark.parametrize('link_objects', ['ON', 'OFF'])
def test_object_only_target(firmware, generator, link_objects):
    if not shutil.which('mingw32-make' if generator == 'MinGW Makefiles' else 'ninja'):
        pytest.skip('requires CMake, generator and ARM GCC')
    if generator == 'MinGW Makefiles' and os.name != 'nt':
        pytest.skip('requires Windows MinGW Makefiles')
    root, config = firmware
    settings = config['analysis']['cmake']
    settings.update(generator=generator, args=['-DLINK_OBJECTS='+link_objects])
    units, compilation = prepare(root, config)
    build = Path(compilation['compile_database']).parent
    api = FileAPI(root, build, {}, generator)
    target, = [api.target(row) for row in api.configuration('Debug')['targets'] if row['name'] == 'app_elf']
    assert not target.get('compileGroups')
    assert compilation['cmake_target_selection']['effective_target'] == 'app_elf'
    assert compilation['cmake_steps'][-1]['command'][-2:] == ['--target', 'app_elf']
    assert (build/'mfc_v2.axf').read_bytes()[:4] == b'\x7fELF'
    assert not (root/'output').exists()
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    check_isolated_tree(root, sha)
    assert sorted(u['source_file'] for u in units) == ['main.c', 'value.c']
    rows = read_json(compilation['compile_database'])
    settings['target'] = 'app_elf'
    explicit, other = prepare(root, config)
    def records(entries, checks, folder):
        return sorted((Path(row['directory']).resolve().relative_to(folder).as_posix(),
                       row['output'], unit['source_file'], build_arguments(unit, root))
                      for row, unit in zip(entries, checks, strict=True))
    assert records(read_json(other['compile_database']), explicit, Path(other['compile_database']).parent) == records(rows, units, build)
    assert other['cmake_steps'][-2]['outputs'] == compilation['cmake_steps'][-2]['outputs'] == 3
    explicit_build = Path(other['compile_database']).parent
    explicit_api = FileAPI(root, explicit_build, {}, generator)
    explicit_target, = [explicit_api.target(row) for row in explicit_api.configuration('Debug')['targets']
                        if row['name'] == 'app_elf']
    assert [path.relative_to(explicit_build) for path in explicit_api.artifacts(explicit_target)] == [
        path.relative_to(build) for path in api.artifacts(target)]
    assert [u['arguments'] for u in explicit] == [u['arguments'] for u in units]


def append_cmake(root, text):
    with (root/'CMakeLists.txt').open('a', encoding='utf-8') as stream:
        stream.write(text)


@pytest.mark.skipif(not shutil.which('ninja') or not shutil.which('arm-none-eabi-g++'), reason='requires ARM C++')
def test_direct_cpp_executable(firmware):
    root, cfg = firmware
    path = root/'CMakeLists.txt'
    body = path.read_text('utf-8').replace('project(objects C)',
                'set(CMAKE_CXX_COMPILER arm-none-eabi-g++)\nproject(objects C CXX)')
    path.write_text(body[:body.index('if(LINK_OBJECTS)')] + 'add_executable(app_elf main.cpp)\n' +
                    body[body.index('target_link_options'):], 'utf-8')
    (root/'main.cpp').write_text('volatile int state; int main() {return ++state;}\n', encoding='utf-8')
    units, info = prepare(root, cfg)
    assert [u['source_file'] for u in units] == ['main.cpp']
    assert info['cmake_steps'][-1]['command'][-2:] == ['--target', 'app_elf']
    assert not (root/'output').exists()


@pytest.mark.skipif(not shutil.which('ninja'), reason='requires Ninja')
def test_exact_name_and_artifact_owners(firmware):
    root, cfg = firmware
    settings = cfg['analysis']['cmake']
    settings['target'] = 'mfc_v2.axf'
    with pytest.raises(ValueError, match='未找到 CMake 目标：mfc_v2.axf.*目标 app_elf 的构建产物'):
        prepare(root, cfg)
    append_cmake(root, '''
add_executable(second main.c value.c)
set_target_properties(second PROPERTIES RUNTIME_OUTPUT_DIRECTORY second OUTPUT_NAME mfc_v2 SUFFIX .axf)
''')
    with pytest.raises(ValueError, match='多个同名产物.*app_elf、second'):
        prepare(root, cfg)
    append_cmake(root, '''
set_target_properties(app_elf PROPERTIES RUNTIME_OUTPUT_DIRECTORY first)
add_executable(mfc_v2.axf main.c value.c)
set_target_properties(mfc_v2.axf PROPERTIES SUFFIX "")
target_link_options(mfc_v2.axf PRIVATE -nostdlib -Wl,-e,main)
''')
    units, info = prepare(root, cfg)
    assert sorted(u['source_file'] for u in units) == ['main.c', 'value.c']
    assert all('mfc_v2.axf.dir' in row['output'] for row in read_json(info['compile_database']))
    assert (Path(info['compile_database']).parent/'mfc_v2.axf').read_bytes()[:4] == b'\x7fELF'
    assert info['cmake_steps'][-1]['command'][-2:] == ['--target', 'mfc_v2.axf']
    assert not (root/'output').exists()


@pytest.mark.skipif(not shutil.which('ninja'), reason='requires Ninja')
def test_order_only_library_and_helper_cannot_supply_link_evidence(firmware):
    root, cfg = firmware
    subprocess.run(['arm-none-eabi-gcc', '-c', 'main.c', '-o', 'prebuilt.o'], cwd=root, check=True)
    path = root/'CMakeLists.txt'
    body = path.read_text('utf-8')
    path.write_text(body[:body.index('if(LINK_OBJECTS)')] + '''
add_executable(helper main.c value.c)
add_executable(app_elf prebuilt.o)
set_target_properties(app_elf PROPERTIES LINKER_LANGUAGE C)
add_dependencies(app_elf objects helper)
''' + body[body.index('target_link_options'):], 'utf-8')
    with pytest.raises(ValueError, match='没有合格.*app_elf.*实际链接对象.*helper.*链接脚本'):
        prepare(root, cfg)
    assert not (root/'output').exists()
    assert not (cmake_build_directory(root, cfg['analysis'])/'mfc_v2.axf').exists()


@pytest.mark.skipif(not shutil.which('ninja'), reason='requires Ninja')
def test_unique_qualified_executable_with_helper_and_shared_dependency(firmware):
    root, cfg = firmware
    append_cmake(root, '''
add_executable(helper main.c value.c)
target_link_options(helper PRIVATE -nostdlib)
add_custom_target(gen1 DEPENDS objects)
add_custom_target(gen2 DEPENDS objects)
add_dependencies(app_elf gen1 gen2)
''')
    _, info = prepare(root, cfg)
    selection = info['cmake_target_selection']
    assert selection['effective_target'] == 'app_elf'
    assert [(row['target'], row['eligible']) for row in selection['candidates']] == [
        ('app_elf', True), ('helper', False)]
    assert len(read_json(info['compile_database'])) == 2
    assert not (root/'output').exists()


@pytest.mark.skipif(not shutil.which('ninja') or not shutil.which('g++'), reason='requires Ninja and host g++')
def test_required_host_generator_is_built_but_does_not_prove_firmware(firmware):
    root, cfg = firmware
    path = root/'CMakeLists.txt'
    path.write_text(path.read_text('utf-8').replace('project(objects C)',
                    f'set(CMAKE_CXX_COMPILER "{Path(shutil.which("g++")).as_posix()}")\nproject(objects C CXX)'), 'utf-8')
    (root/'helper.cpp').write_text('int main() {return 0;}\n', encoding='utf-8')
    append_cmake(root, '''
add_executable(generator helper.cpp)
set_target_properties(generator PROPERTIES SUFFIX ".exe")
add_dependencies(app_elf generator)
''')
    _, info = prepare(root, cfg)
    selection = info['cmake_target_selection']
    assert selection['effective_target'] == 'app_elf'
    evidence, = [row['compile_evidence'] for row in selection['candidates'] if row['eligible']]
    assert [row['target'] for row in evidence] == ['objects']
    build = Path(info['compile_database']).parent
    api = FileAPI(root, build, {}, 'Ninja')
    helper, = [api.target(row) for row in api.configuration('Debug')['targets'] if row['name'] == 'generator']
    assert all(path.is_file() for path in api.artifacts(helper))
    assert not (root/'output').exists()


@pytest.mark.skipif(not shutil.which('ninja'), reason='requires Ninja')
def test_current_config_and_broken_dependency_before_build(firmware, monkeypatch):
    from ecra import compilation
    from ecra.build_target_checkpoint import task_selection
    from ecra.cmake_file_api import latest_index
    from ecra.common import digest
    from ecra.report_package import sha256
    root, cfg = firmware
    settings = cfg['analysis']['cmake']
    settings['clean_before_configure'] = False
    # A successful ALL record for the same source and build directory.
    _, old = prepare(root, dict(cfg, project=dict(cm4_enabled=True)))
    assert old['cmake_target_selection']['effective_target'] is None
    build = Path(old['compile_database']).parent
    assert (root/'output/package-ran').is_file()
    old_task, retry = (root.parent/'tasks'/name for name in ('old', 'retry'))
    for task in (old_task, retry):
        task.mkdir(parents=True)
        write_json(task/'semantics.yaml', cfg)
    records = dict(current=dict(source=str(root), build=str(build), selection=old['cmake_target_selection'],
                                inputs={}, signature='legacy-all'))
    write_json(old_task/'cmake-target-checkpoint.json', dict(version=1, records=records, digest=digest(records),
               config_sha256=sha256(old_task/'semantics.yaml')))
    write_json(retry/'retry-source.json', dict(source_task=old_task.name))
    with task_selection(retry), pytest.raises(ValueError, match='旧检查点没有已验证的 CMake 逻辑目标'):
        prepare(root, cfg)
    _, refreshed = prepare(root, cfg)
    assert refreshed['cmake_steps'][-1]['command'][-2:] == ['--target', 'app_elf']
    assert Path(refreshed['compile_database']).parent == build
    settings['build_type'] = 'Release'
    _, release = prepare(root, cfg)
    assert release['cmake_target_selection']['build_type'] == 'Release'
    assert release['cmake_steps'][-1]['command'][-4:] == ['--config', 'Release', '--target', 'app_elf']
    assert Path(release['compile_database']).parent != build

    original = compilation.execute
    commands = []
    def broken_edge(argv, **kwargs):
        commands.append(argv)
        proc = original(argv, **kwargs)
        if '-S' in argv:
            index = latest_index(cmake_build_directory(root, cfg['analysis']))
            target, = index.parent.glob('target-app_elf-*.json')
            desc = read_json(target)
            desc['dependencies'].append(dict(id='missing-target-id'))
            write_json(target, desc)
        return proc
    monkeypatch.setattr(compilation, 'execute', broken_edge)
    with pytest.raises(ValueError, match='依赖缺少目标记录：missing-target-id'):
        prepare(root, cfg)
    assert not any('--build' in argv for argv in commands)


@pytest.mark.parametrize('filename', ['output/post-build', 'untracked.marker'])
@pytest.mark.skipif(not shutil.which('ninja'), reason='requires Ninja')
def test_post_build_pollution_reported_in_isolated_preflight(firmware, filename):
    from ecra.studio.preflight import run_preflight
    root, cfg = firmware
    subprocess.run(['git', 'branch', 'fixture-base'], cwd=root, check=True)
    append_cmake(root, '''
add_custom_command(TARGET app_elf POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_SOURCE_DIR}/output
  COMMAND ${CMAKE_COMMAND} -E touch ${CMAKE_SOURCE_DIR}/'''+filename+''' VERBATIM)
''')
    subprocess.run(['git', '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '-qam', 'post build'], cwd=root, check=True)
    cfg['analysis']['git_diff'] = dict(enabled=True, base_ref='fixture-base')
    data = Path(cfg['analysis']['output']['custom_dir'])
    receipt = data/'work/post-build'
    profile = root.parent/'profile.json'
    write_json(profile, cfg)
    with pytest.raises(ValueError, match=r'构建目标 app_elf.*'+Path(filename).name):
        run_preflight(profile, data, receipt)
    check = read_json(receipt/'preflight.json')
    assert not check['passed'] and check['target'] == 'app_elf'
    assert check['cmake_steps'][-1]['command'][-2:] == ['--target', 'app_elf']
    assert not (root/filename).exists()
