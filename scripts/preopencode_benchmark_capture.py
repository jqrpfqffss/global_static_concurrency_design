"""Record actual compiler invocations while executing the real compiler.

Used only for Make based benchmark builds. ECRA does not consume synthetic
commands: a command is admitted to compile_commands.json only after success.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    args = sys.argv[1:]
    # GCC 10's Windows -flto=auto can pass an invalid job count to make.
    # This optional build-profile setting changes LTO parallelism only; the
    # recorded command is the exact command actually executed.
    lto_jobs = os.environ.get("ECRA_LTO_JOBS")
    if lto_jobs:
        args = ["-flto=" + str(int(lto_jobs)) if arg == "-flto=auto" else arg for arg in args]
    # Upstream POSIX build scripts split --version at LF; normalize Windows
    # toolchain CRLF for that metadata query without changing compilation.
    if "--version" in args:
        result = subprocess.run(args, capture_output=True)
        sys.stdout.buffer.write(result.stdout.replace(b"\r\n", b"\n"))
        sys.stderr.buffer.write(result.stderr.replace(b"\r\n", b"\n"))
        return result.returncode
    result = subprocess.run(args)
    folder = os.environ.get("ECRA_COMPILER_CAPTURE")
    if folder:
        record = dict(directory=str(Path.cwd()), arguments=args,
                      returncode=result.returncode, timestamp_ns=time.time_ns())
        sources = [arg for arg in args[1:] if Path(arg).suffix.lower() in {".c", ".cc", ".cpp", ".s"}]
        if "-c" in args and sources:
            record["file"] = sources[-1]
            if "-o" in args:
                record["output"] = args[args.index("-o") + 1]
        elif "-o" in args:
            record["link_output"] = args[args.index("-o") + 1]
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(json.dumps(record).encode()).hexdigest()
        (path / (key + ".json")).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
