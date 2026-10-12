"""Recover the cli_simple compile database from its actual Make build logs/map.

This is a validation helper for ViniBR01/stm32-bare-metal, not a replacement
for a firmware build. Run the standalone build first and retain build_full.log
and build_cli.log in the checkout.
"""

import json
import re
import shlex
import sys
from pathlib import Path


def main(root: Path) -> None:
    root = root.resolve()
    map_path = root / "build/apps/cli/cli_simple_standalone/cli_simple_standalone.map"
    selected = set()
    for line in map_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^(.+?/build/.+?/[^/\s]+\.a)\(([^()]+\.o)\)$", line)
        if match:
            selected.add(str(Path(match[1]).parent / match[2]).casefold())
    selected.update(str(p).casefold() for p in (
        root / "build/startup/stm32f411_startup.o",
        root / "build/apps/cli/cli_simple_standalone/cli_simple.o",
        root / "build/apps/cli/cli_simple_standalone/cli_commands.o",
    ))

    rows = {}
    for name in ("build_full.log", "build_cli.log"):
        directory = root
        for line in (root / name).read_text(encoding="utf-8", errors="replace").splitlines():
            entered = re.search(r"Entering directory '([^']+)'", line)
            if entered:
                directory = Path(entered[1])
                continue
            if not line.startswith("arm-none-eabi-gcc "):
                continue
            args = shlex.split(line)
            if "-c" not in args or "-o" not in args:
                continue
            output = Path(args[args.index("-o") + 1]).resolve()
            source = (directory / args[-1]).resolve()
            rows[str(output).casefold()] = dict(directory=str(directory), file=str(source),
                                                output=str(output), arguments=args)
    missing = selected - rows.keys()
    if missing:
        raise ValueError("Linked objects missing from build logs: " + ", ".join(sorted(missing)))
    database = [rows[key] for key in sorted(selected)]
    target = root / "build/compile_commands.json"
    target.write_text(json.dumps(database, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(database)} linked translation units -> {target}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
