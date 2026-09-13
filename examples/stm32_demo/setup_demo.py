"""Create relocatable compile commands; no hardware compiler/build required."""
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ecra.config import default_managed_config_path, register_managed_project

root = Path(__file__).resolve().parent
(root / ".ecra").mkdir(exist_ok=True)
config = default_managed_config_path(root)
if not config.exists():
    config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "semantics.yaml", config)
register_managed_project(root, config)
entries = [dict(directory=str(root), file=name,
                arguments=["arm-none-eabi-gcc", "-mcpu=cortex-m7", "-mthumb", "-std=c11", "-c", name, "-o", name + ".o"])
           for name in ("main.c", "other.c")]
(root / "compile_commands.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
print(root)
print('Tool-side configuration:', config)
