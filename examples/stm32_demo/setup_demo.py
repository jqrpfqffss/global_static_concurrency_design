"""Create relocatable compile commands; no hardware compiler/build required."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ecra.config import SEMANTICS_FILE

root = Path(__file__).resolve().parent
(root / ".ecra").mkdir(exist_ok=True)
# Selecting the demo is explicit, so it intentionally replaces the one active
# tool-side configuration instead of registering another project profile.
config = SEMANTICS_FILE
content = (root / "semantics.yaml").read_text(encoding="utf-8")
content = content.replace('project:\n', 'project:\n  root: ' + json.dumps(str(root), ensure_ascii=False) + '\n', 1)
config.parent.mkdir(parents=True, exist_ok=True)
config.write_text(content, encoding="utf-8")
entries = [dict(directory=str(root), file=name,
                arguments=["arm-none-eabi-gcc", "-mcpu=cortex-m7", "-mthumb", "-std=c11", "-c", name, "-o", name + ".o"])
           for name in ("main.c", "other.c")]
(root / "compile_commands.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
print(root)
print('Active tool-side configuration:', config)
