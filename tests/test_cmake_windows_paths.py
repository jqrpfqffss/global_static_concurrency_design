"""Exercise real Windows CMake/ARM builds, including previously built objects."""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import uuid

import pytest

from ecra.common import read_json
from ecra.compilation import configure_cmake
from ecra.path_io import filesystem_path
from ecra.portable import default_alias_root, read_cache
from ecra.workspace import WorkspaceResolver


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows path semantics required")

HAL_DIRECTORY = Path("platform/thirdParty/opensource/stm32cubeh7/stm32h7xx_hal")
HAL_SOURCE = Path("code/stm32h7xx-hal-driver-1.11.5/Src/stm32h7xx_hal.c")
HAL_OBJECT = HAL_DIRECTORY / "CMakeFiles/stm32h745xxlib_obj.dir" / (HAL_SOURCE.as_posix() + ".obj")


@pytest.fixture
def aliases(monkeypatch):
    parent = default_alias_root() / uuid.uuid4().hex[:8]
    monkeypatch.setenv("ECRA_PATH_ALIAS_ROOT", str(parent))
    monkeypatch.setattr("ecra.portable._BUILD_ALIASES", {})
    try:
        yield parent
    finally:
        if parent.exists():
            for alias in parent.iterdir():
                assert alias.lstat().st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
                alias.rmdir()
            parent.rmdir()


def create_firmware(root, subdirectory):
    hal = root / subdirectory
    (hal / HAL_SOURCE).parent.mkdir(parents=True)
    (hal / HAL_SOURCE).write_text(
        "static volatile int ticks; int hal(void) { return ++ticks; }\n", encoding="utf-8")
    (hal / "CMakeLists.txt").write_text(
        f"add_library(stm32h745xxlib_obj OBJECT {HAL_SOURCE.as_posix()})\n", encoding="utf-8")
    (root / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\n"
        "project(stm32h745_fixture C)\n"
        "add_compile_options(-mcpu=cortex-m7 -mthumb)\n"
        f"add_subdirectory({subdirectory.as_posix()})\n"
        "add_executable(firmware.elf main.c)\n"
        "target_link_libraries(firmware.elf PRIVATE stm32h745xxlib_obj)\n"
        "target_link_options(firmware.elf PRIVATE -mcpu=cortex-m7 -mthumb -nostdlib -Wl,-e,main)\n",
        encoding="utf-8")
    (root / "main.c").write_text(
        "int hal(void); volatile int samples; int main(void) { return samples = hal(); }\n",
        encoding="utf-8")
    (root / "arm.cmake").write_text(
        "set(CMAKE_SYSTEM_NAME Generic)\n"
        "set(CMAKE_C_COMPILER arm-none-eabi-gcc)\n"
        "set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)\n", encoding="utf-8")


@pytest.mark.parametrize("generator,program", [("Ninja", "ninja"), ("MinGW Makefiles", "mingw32-make")])
@pytest.mark.parametrize("length,source_dir",
                         [(232, "fw"), (259, "fw"), (286, "fw"), (286, "固件 文件"), (286, "fw files")])
def test_managed_arm_build_and_clean(tmp_path_factory, monkeypatch, aliases, generator, program, length, source_dir):
    if not all(shutil.which(tool) for tool in ("cmake", program, "arm-none-eabi-gcc")):
        pytest.skip("CMake, selected generator and ARM GCC required")
    home = tmp_path_factory.mktemp("b")
    root = home / source_dir
    analysis = dict(output=dict(location="custom", custom_dir=str(home / "d")),
                    cmake=dict(location="workspace", generator=generator,
                               target="firmware.elf", toolchain_file="arm.cmake", build=True))
    build = Path(WorkspaceResolver.resolve(root, analysis).build_root) / "b"
    monkeypatch.setattr("ecra.compilation.workspace_build_path", lambda *_: build)
    object_suffix = HAL_OBJECT.relative_to(HAL_DIRECTORY)
    depth = length - len(str(build / "x" / object_suffix)) + 1
    assert depth > 0
    subdirectory = Path("p" * depth)
    object_path = build / subdirectory / object_suffix
    assert len(str(object_path)) == length
    create_firmware(root, subdirectory)

    def configure():
        return configure_cmake(root, analysis, lambda _: None, True)

    database, steps = configure()
    command = next(step["command"] for step in steps if step["stage"] == "configure")
    if " " in source_dir:
        source_alias = Path(command[command.index("-S") + 1])
        assert source_alias.parent.resolve() == aliases.resolve()
        assert source_alias.resolve() == root
    alias = Path(command[command.index("-B") + 1])
    assert alias.parent.resolve() == aliases.resolve()
    assert alias.resolve() == database.parent == build
    cache = read_cache(build)
    assert Path(cache["CMAKE_CACHEFILE_DIR"]).resolve() == build
    expected = {root / "main.c", root / subdirectory / HAL_SOURCE}
    rows = read_json(database)
    assert {(Path(row["directory"]) / row["file"]).resolve() for row in rows} == expected
    # CMake may shorten an object-component name at its Windows path limit.
    by_source = {(Path(row["directory"]) / row["file"]).resolve():
                 (alias if generator == "MinGW Makefiles" else Path(row["directory"])) / row["output"]
                 for row in rows}
    objects = set(by_source.values())
    assert all(path.is_file() for path in objects)
    header = by_source[root / subdirectory / HAL_SOURCE].read_bytes()[:20]
    assert header[:4] == b"\x7fELF" and int.from_bytes(header[18:20], "little") == 40
    assert (alias / "firmware.elf").read_bytes().startswith(b"\x7fELF")
    before = {path: path.stat().st_mtime_ns for path in objects}

    # Emulate a fresh process reusing the existing cache and junction.
    from ecra import portable
    portable._BUILD_ALIASES.clear()
    repeated_db, repeated = configure()
    assert repeated_db == database and read_json(repeated_db) == rows
    assert next(step["command"] for step in repeated if step["stage"] == "configure") == [
        arg for arg in command if not arg.startswith("-DCMAKE_TOOLCHAIN_FILE=")]
    assert {path: path.stat().st_mtime_ns for path in objects} == before

    sentinel = filesystem_path(alias / object_path.relative_to(build).with_suffix(".obj.d"))
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("stale dependency", encoding="utf-8")
    analysis["cmake"]["clean_before_configure"] = True
    clean_db, clean = configure()
    assert clean_db == database and read_json(clean_db) == rows
    assert [step["stage"] for step in clean] == ["clean", "configure", "target-closure", "build"]
    assert all(path.is_file() for path in objects)
    if sentinel.exists():  # Make retains its new depfile. Ninja consumes it.
        assert "stale dependency" not in sentinel.read_text(encoding="utf-8")


def test_clean_removes_existing_long_objects_on_the_real_tree(tmp_path, aliases):
    if not all(shutil.which(tool) for tool in ("cmake", "ninja", "arm-none-eabi-gcc")):
        pytest.skip("CMake, Ninja and ARM GCC required")
    root = tmp_path / "fw"
    create_firmware(root, HAL_DIRECTORY)
    analysis = dict(output=dict(location="custom", custom_dir=str(tmp_path / "data")),
                    cmake=dict(location="workspace", generator="Ninja",
                               target="firmware.elf", toolchain_file="arm.cmake", build=True,
                               clean_before_configure=True))
    from ecra.workspace import build_path
    build = build_path(root, analysis)
    build.mkdir(parents=True)
    (build / ".ecra-build-owner").write_text(str(root), encoding="utf-8")
    # Use the exact old object suffix from the Studio failure. The existing
    # tree can contain longer paths than the current configuration will build.
    stale = filesystem_path(build / ("old-" + "x" * 45) / HAL_OBJECT.with_suffix(".o"))
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old object")
    assert len(str(stale)) > 280
    database, steps = configure_cmake(root, analysis, lambda _: None, True)
    assert not stale.exists()
    assert (build / "firmware.elf").read_bytes().startswith(b"\x7fELF")
    assert len(read_json(database)) == 2
    assert [step["stage"] for step in steps] == ["clean", "configure", "target-closure", "build"]


def test_reconfigure_existing_unaliased_cache(tmp_path_factory, monkeypatch, aliases):
    if not all(shutil.which(tool) for tool in ("cmake", "ninja", "arm-none-eabi-gcc")):
        pytest.skip("CMake, Ninja and ARM GCC required")
    home = tmp_path_factory.mktemp("r")
    root = home / "f"
    create_firmware(root, Path("hal"))
    (root / ".git").mkdir()
    analysis = dict(output=dict(location="custom", custom_dir=str(home / "d")),
                    cmake=dict(location="workspace", generator="Ninja",
                               target="firmware.elf", toolchain_file="arm.cmake", build=True))
    build = Path(WorkspaceResolver.resolve(root, analysis).build_root) / "b"
    monkeypatch.setattr("ecra.compilation.workspace_build_path", lambda *_: build)
    subprocess.run(["cmake", "-S", str(root), "-B", str(build), "-G", "Ninja",
                    "-DCMAKE_TOOLCHAIN_FILE=" + str(root/"arm.cmake"),
                    "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"], check=True, capture_output=True)
    subprocess.run(["cmake", "--build", str(build), "--target", "firmware.elf"],
                   check=True, capture_output=True)
    (build / ".ecra-build-owner").write_text(str(root), encoding="utf-8")
    sentinel = build / "keep"
    sentinel.touch()
    database, steps = configure_cmake(root, analysis, lambda _: None, True)
    alias = Path(steps[0]["command"][4])
    assert alias.parent.resolve() == aliases.resolve()
    assert alias.resolve() == build == database.parent
    assert sentinel.is_file()
    assert len(read_json(database)) == 2
    assert [step["stage"] for step in steps] == ["configure", "target-closure", "build"]


def test_prepare_consumes_long_owned_link_outputs(tmp_path, aliases):
    if not all(shutil.which(tool) for tool in ("cmake", "ninja", "arm-none-eabi-gcc")):
        pytest.skip("CMake, Ninja and ARM GCC required")
    from ecra.compilation import cmake_build_directory, prepare
    from ecra.input_snapshot import InputSnapshot, SOURCE_READS
    from ecra.linker_symbols import linked_symbol_names

    root = tmp_path / "fw"
    create_firmware(root, HAL_DIRECTORY)
    analysis = dict(output=dict(location="custom", custom_dir=str(tmp_path / "data")),
                    cmake=dict(build_dir="build/ecra", generator="Ninja", target="firmware.elf",
                               toolchain_file="arm.cmake", build=True))
    build = cmake_build_directory(root, analysis)
    padding = max(0, 270 - len(str(build / "artifacts" / "x" / "firmware.elf")))
    output = Path("artifacts") / ("x" * (padding + 1))
    names = {"elf": output / "firmware.elf", "map": output / "firmware.map"}
    analysis["build_closure"] = {key: (Path("build/ecra") / path).as_posix() for key, path in names.items()}
    with (root / "CMakeLists.txt").open("a", encoding="utf-8") as script:
        script.write(f'set(link_dir "${{CMAKE_BINARY_DIR}}/{output.as_posix()}")\n'
                     'set_target_properties(firmware.elf PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${link_dir}")\n'
                     'target_link_options(firmware.elf PRIVATE "-Wl,-Map,${link_dir}/firmware.map")\n')

    units, compilation = prepare(root, dict(analysis=analysis))
    paths = {key: build / name for key, name in names.items()}
    assert len(units) == 2
    assert all(len(str(path)) >= 270 and filesystem_path(path).is_file() for path in paths.values())
    binding = compilation["build_closure_binding"]
    for key, path in paths.items():
        assert binding["artifacts"][key]["actual"] == str(path)
        assert binding["artifacts"][key]["sha256"] == compilation["consumed_inputs"][str(path)]["sha256"]
    snapshot = InputSnapshot(root, tmp_path / "diagnostics", paths.values(), compilation["consumed_inputs"])
    token = SOURCE_READS.set(snapshot)
    try:
        assert "samples" in linked_symbol_names(compilation["build_closure"])
        assert not snapshot.changes
    finally:
        SOURCE_READS.reset(token)


def test_default_alias_does_not_depend_on_worker_temp(tmp_path, monkeypatch):
    import tempfile
    from ecra import portable

    monkeypatch.delenv("ECRA_PATH_ALIAS_ROOT", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path.parent / "local"))
    monkeypatch.setattr(portable, "_BUILD_ALIASES", {})
    build = tmp_path / "构建"
    build.mkdir()
    aliases = []
    try:
        for task in ("job1", "job2"):
            temp = tmp_path.parent / task
            temp.mkdir()
            for key in ("TEMP", "TMP", "TMPDIR"):
                monkeypatch.setenv(key, str(temp))
            monkeypatch.setattr(tempfile, "tempdir", None)
            portable._BUILD_ALIASES.clear()
            aliases.append(Path(portable.build_path(build, prefer_junction=True)))
        assert aliases[0] == aliases[1]
        assert aliases[0].resolve() == build
    finally:
        for alias in set(aliases):
            alias.rmdir()


@pytest.mark.parametrize("profile_dir", ["用户 目录", "user profile"])
def test_alias_stays_with_tool_when_local_appdata_has_no_compatible_spelling(
        tmp_path, tmp_path_factory, monkeypatch, profile_dir):
    import tempfile
    from ecra import portable

    monkeypatch.delenv("ECRA_PATH_ALIAS_ROOT", raising=False)
    local = tmp_path / profile_dir
    temp = tmp_path_factory.mktemp("t")
    local.mkdir()
    monkeypatch.setattr(portable, "_short_path", str)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    for key in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.setenv(key, str(temp))
    monkeypatch.setattr(tempfile, "tempdir", None)
    monkeypatch.setattr(portable, "_BUILD_ALIASES", {})
    build = tmp_path / "构建"
    build.mkdir()
    alias = Path(portable.build_path(build, prefer_junction=True))
    try:
        assert alias.parent.resolve() == portable.default_alias_root()
        assert alias.resolve() == build
    finally:
        alias.rmdir()


def owned_paths(tmp_path):
    root = tmp_path / "source"
    build = tmp_path / "build"
    root.mkdir()
    build.mkdir()
    marker = build / ".ecra-build-owner"
    marker.write_text(str(root), encoding="utf-8")
    return root, build, marker


@pytest.mark.parametrize("dangling", [False, True])
def test_clean_rejects_nested_junction_before_deleting(tmp_path, dangling):
    from ecra.build_tree import clean_owned_directory
    from ecra.portable import _junction

    root, build, marker = owned_paths(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").touch()
    junction = build / "foreign"
    inside = build / "also-keep"
    inside.touch()
    _junction(junction, outside if not dangling else tmp_path / "missing")
    try:
        with pytest.raises(ValueError, match="拒绝清理含链接"):
            clean_owned_directory(build, root)
        assert inside.is_file() and marker.is_file() and (outside / "keep").is_file()
    finally:
        junction.rmdir()


@pytest.mark.parametrize("vanished", [False, True])
def test_clean_reports_missing_child_only_after_checking_its_state(tmp_path, monkeypatch, vanished):
    import ctypes
    from ecra.build_tree import clean_owned_directory

    root, build, marker = owned_paths(tmp_path)
    child = build / "candidate.obj"
    child.touch()
    unlink = os.unlink
    attempts = []

    def fail(path, *args, **kwargs):
        if Path(path).name != child.name:
            return unlink(path, *args, **kwargs)
        attempts.append(path)
        if vanished:
            unlink(path)
            return unlink(path)
        raise ctypes.WinError(3)

    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", fail)
        with pytest.raises(ValueError, match="路径在清理期间消失" if vanished else "路径仍存在") as exc:
            clean_owned_directory(build, root)
    assert isinstance(exc.value.__cause__, FileNotFoundError)
    assert marker.is_file() and child.exists() != vanished
    assert len(attempts) == 1


def test_clean_preserves_owner_when_a_file_is_in_use(tmp_path):
    from ecra.build_tree import clean_owned_directory

    root, build, marker = owned_paths(tmp_path)
    child = build / "open.obj"
    child.touch()
    with child.open("rb"), pytest.raises(ValueError, match="删除文件") as exc:
        clean_owned_directory(build, root)
    assert exc.value.__cause__.winerror in {5, 32, 33}
    assert marker.is_file() and child.is_file()
    clean_owned_directory(build, root)
    assert set(build.iterdir()) == {marker}


def test_configure_reports_build_directory_file_conflict(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    analysis = dict(output=dict(location="custom", custom_dir=str(tmp_path / "data")),
                    cmake=dict(location="workspace", build_dir="build"))
    from ecra.workspace import build_path
    conflict = build_path(root, analysis)
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"unrelated data")
    with pytest.raises(ValueError, match="构建路径被非目录占用"):
        configure_cmake(root, analysis, lambda _: None, True)
    assert conflict.read_bytes() == b"unrelated data"


def test_clean_rejects_a_foreign_owner_without_removing_files(tmp_path):
    from ecra.build_tree import clean_owned_directory

    root, build, marker = owned_paths(tmp_path)
    marker.write_text(str(tmp_path / "another-project"), encoding="utf-8")
    child = build / "existing.obj"
    child.write_bytes(b"keep")
    with pytest.raises(ValueError, match="拒绝清理非 ECRA 专用构建目录"):
        clean_owned_directory(build, root)
    assert marker.is_file() and child.read_bytes() == b"keep"


def test_windows_pins_prevent_directory_replacement_during_cleanup(tmp_path):
    from ecra.build_tree import _WindowsDirectoryPins

    folder = tmp_path / "build"
    folder.mkdir()
    renamed = tmp_path / "moved"
    with _WindowsDirectoryPins().hold(filesystem_path(folder)):
        with pytest.raises(PermissionError) as exc:
            folder.rename(renamed)
        assert exc.value.winerror in {5, 32}
        assert folder.is_dir() and not renamed.exists()
    assert folder.rename(renamed) == renamed
