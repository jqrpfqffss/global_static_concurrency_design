"""Materialize benchmark databases from successful builds and link inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

WORKSPACE = Path(__file__).resolve().parent.parent
BASE = WORKSPACE / "output/preopencode-benchmark"
sys.path.insert(0, str(WORKSPACE))
from ecra.compilation import split_command
import yaml


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def normal(path):
    return str(Path(path).resolve()).lower()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project", choices=["betaflight", "klipper", "blackmagic"])
    args = parser.parse_args()
    name = args.project
    folder = BASE / name
    folder.mkdir(parents=True, exist_ok=True)
    if name == "blackmagic":
        root = WORKSPACE / "validation/github-blackmagic"
        build = root / "build/preopencode-native"
        elf = build / "blackmagic_native_firmware.elf"
        mapfile = folder / "firmware.map"
        ninja = (build / "build.ninja").read_text(encoding="utf-8")
        block = ninja[ninja.index("build blackmagic_native_firmware.elf:"):].split("\n\n", 1)[0]
        direct_objects = re.findall(r"\S+\.o(?= |$)", block.splitlines()[0])
        link_args = split_command("gcc " + re.search(r" LINK_ARGS = (.*)", block).group(1))[1:]
        command = ["arm-none-eabi-gcc", *direct_objects, "-o", str(elf), *link_args, "-Wl,-Map=" + str(mapfile)]
        result = subprocess.run(command, cwd=build, capture_output=True)
        (folder / "map-link.log").write_bytes(result.stdout + result.stderr)
        dump(folder / "map-link-command.json", dict(arguments=command,directory=str(build),returncode=result.returncode))
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace"))
        maptext = mapfile.read_text(errors="replace")
        members = set(re.findall(r"libopencm3_stm32f1\.a\(([^)]+)\)",maptext))
        # Meson creates a thin archive, whose map names the original member
        # object path instead of archive(member.o).
        thin_objects = set(re.findall(r"\bdeps/libopencm3/\S+\.a\.p/\S+\.o",maptext))
        originals = json.loads((build/"compile_commands.json").read_text())
        database = [entry for entry in originals if entry["output"] in direct_objects or entry["output"] in thin_objects or
            ("libopencm3_stm32f1.a.p/" in entry["output"] and Path(entry["output"]).name in members)]
        target = "native / STM32F1 / Cortex-M3 / BMD bootloader"
    else:
        root = BASE / "sources" / name
        records = [json.loads(path.read_text()) for path in (folder / "commands").glob("*.json")]
        links = [r for r in records if r.get("link_output", "").endswith(".elf") and r["returncode"] == 0]
        link = max(links, key=lambda r:r["timestamp_ns"])
        elf = (root / link["link_output"]).resolve()
        linked = {normal(root/arg) for arg in link["arguments"] if arg.endswith(".o")}
        choices = {}
        for record in sorted(records,key=lambda r:r["timestamp_ns"]):
            if record.get("file") and record["returncode"] == 0 and normal(root/record["output"]) in linked:
                choices[normal(root/record["output"])] = {key:record[key] for key in ("directory","file","output","arguments")}
        database = list(choices.values())
        if len(choices) != len(linked):
            raise RuntimeError("Missing compiler capture for actual link objects: " + repr(linked-set(choices)))
        mapfile = folder / "firmware.map"
        if name == "betaflight":
            mapfile.write_bytes((root / "obj/main/betaflight_STM32F405.map").read_bytes())
            target = "STM32F405 / Cortex-M4F / default firmware features"
        else:
            command = [*link["arguments"], "-Wl,-Map="+str(mapfile)]
            result = subprocess.run(command,cwd=root,capture_output=True)
            (folder/"map-link.log").write_bytes(result.stdout+result.stderr)
            dump(folder/"map-link-command.json",dict(arguments=command,directory=str(root),returncode=result.returncode))
            if result.returncode:
                raise RuntimeError(result.stderr.decode(errors="replace"))
            target = "STM32F103xE / Cortex-M3 / 8 KiB bootloader / 8 MHz / USB PA11 PA12"
    raw_elf = elf.read_bytes()
    if raw_elf[:4] != b"\x7fELF" or int.from_bytes(raw_elf[18:20],"little") != 40:
        raise RuntimeError("Actual ARM ELF required")
    commit = (root/".git/HEAD").read_text().strip()
    if commit.startswith("ref:"):
        commit=(root/".git"/commit[5:]).read_text().strip()
    db = folder / "compile_commands.json"
    dump(db, database)
    metadata = dict(project=name,commit=commit,target=target,root=str(root),compile_database=str(db),
        compile_commands=len(database),elf=str(elf),elf_sha256=hashlib.sha256(raw_elf).hexdigest(),map=str(mapfile),
        linked_sources=sorted({str((Path(d["directory"])/d["file"]).resolve()) for d in database}),
        linked_objects=sorted({str((Path(d["directory"])/d["output"]).resolve()) for d in database}))
    dump(folder/"build-closure.json",metadata)
    cfg = dict(version=1,project=dict(root=str(root),chip="STM32",core="Cortex-M",concurrency_model="single_core_preemptive",native_word_bits=32),
        analysis=dict(compile_database=str(db),auto_contexts=True,auto_system_includes=True,build_closure_only=True,
            build_closure={k:metadata[k] for k in ("target","commit","elf","map","linked_sources","linked_objects")},
            remove_args=["-fno-fat-lto-objects","-fsingle-precision-constant","-fno-tree-loop-distribute-patterns","-fno-use-linker-plugin","-fuse-linker-plugin","-fwhole-program"],
            # Compiler warnings do not imply a missing AST. Clang/GCC differ
            # in warnings; retain warning diagnostics without inheriting GCC's
            # -Werror policy. Actual Clang errors still fail parse coverage.
            extra_args=["-Wno-error","-Wno-unknown-warning-option","-Wno-error=deprecated-non-prototype","-Wno-error=invalid-utf8"],output_dir=".ecra-preopencode"),
        contexts=[dict(id="main",kind="MAIN",functions=["main"])],review=dict(enabled=False))
    if name == "betaflight":
        # Upstream atomic.h deliberately provides a Clang Blocks spelling of
        # the GCC nested-function cleanup barrier. Do not suppress __clang__
        # or replace source; enable that published parser compatibility path.
        cfg["analysis"]["extra_args"].append("-fblocks")
    (folder/"semantics.yaml").write_text(yaml.safe_dump(cfg,sort_keys=False),encoding="utf-8")
    print(json.dumps({k:v for k,v in metadata.items() if k not in {"linked_sources","linked_objects"}},indent=2))


if __name__ == "__main__":
    main()
