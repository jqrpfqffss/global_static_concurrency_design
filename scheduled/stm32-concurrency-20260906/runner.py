"""One-shot Windows task controller. Never launches the actual job during --check."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PYTHON = Path(r"C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe")
NODE = Path(r"C:\Program Files\nodejs\node.exe")
CODEX = HERE / "runtime/node_modules/@openai/codex/bin/codex.js"
LOGS = HERE / "logs"
BENCH = ROOT / "validation/stm32_concurrency"


def write_json(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def progress(state, **values):
    write_json(HERE / "status.json", dict(state=state, updated=stamp(), **values))


def run_process(argv, stdin=None, stdout=None, stderr=None, timeout=None):
    return subprocess.run(argv, cwd=ROOT, input=stdin, text=True, encoding="utf-8", errors="replace",
                          stdout=stdout or subprocess.PIPE, stderr=stderr or subprocess.PIPE,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                          timeout=timeout)


def validate_completion(round_number):
    verifier = BENCH / "verify_acceptance.py"
    if not verifier.is_file():
        return "缺少独立 verify_acceptance.py"
    with (LOGS / f"round-{round_number:03d}-acceptance.log").open("w", encoding="utf-8") as log:
        result = run_process([str(PYTHON), str(verifier)], stdout=log, stderr=log)
    if result.returncode:
        return f"独立验收比较器失败，退出码 {result.returncode}"
    try:
        acceptance = json.loads((BENCH / "acceptance.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return f"验收结果无效: {exc}"
    if acceptance.get("status") != "PASS":
        return "acceptance.status 不是 PASS"
    for key in ("missing_variables", "missing_risk_cases"):
        if acceptance.get(key) != []:
            return f"{key} 未清零"
    if acceptance.get("unresolved_reviews") != 0:
        return "真实模型复核仍有未解决项"
    for expected, matched in (("expected_variables", "matched_variables"), ("expected_risk_cases", "matched_risk_cases")):
        if type(acceptance.get(expected)) is not int or acceptance[expected] <= 0 or acceptance.get(matched) != acceptance[expected]:
            return f"{expected}/{matched} 不符合全覆盖要求"
    if acceptance.get("build_passed") is not True or acceptance.get("regression_passed") is not True:
        return "构建或回归验证未通过"
    artifacts = acceptance.get("firmware_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return "缺少 ARM ELF 产物"
    for artifact in artifacts:
        path = (ROOT / artifact).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            return f"固件产物不存在: {artifact}"
        with path.open("rb") as f:
            header = f.read(20)
        if header[:4] != b"\x7fELF" or len(header) < 20:
            return f"不是 ELF: {artifact}"
        endian = "little" if header[5] == 1 else "big"
        if int.from_bytes(header[18:20], endian) != 40:
            return f"不是 ARM ELF: {artifact}"
    if not (BENCH / "final_report.md").is_file():
        return "缺少最终报告"
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path in (ROOT, PYTHON, NODE, CODEX, HERE / "task.md", HERE / "result.schema.json"):
        if not path.exists():
            raise RuntimeError(f"依赖不存在: {path}")
    if args.check:
        version = run_process([str(NODE), str(CODEX), "--version"], timeout=30)
        login = run_process([str(NODE), str(CODEX), "login", "status"], timeout=30)
        evidence = dict(checked=stamp(), project=str(ROOT), version=version.stdout.strip(),
                        logged_in=login.returncode == 0, dry_run=True,
                        prompt_sha256=hashlib.sha256((HERE / "task.md").read_bytes()).hexdigest())
        write_json(HERE / "preflight.json", evidence)
        if version.returncode or login.returncode:
            raise RuntimeError("Codex 版本/登录检查失败；未运行实际任务")
        print(json.dumps(evidence, ensure_ascii=False))
        return 0

    LOGS.mkdir(exist_ok=True)
    lock = HERE / "running.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return 4
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    previous = None
    failures = 0
    previous_blocker = None
    blocked_count = 0
    try:
        for round_number in __import__("itertools").count(1):
            progress("RUNNING", round=round_number, started=stamp(), log_dir=str(LOGS))
            prompt = (HERE / "task.md").read_text(encoding="utf-8")
            if previous:
                prompt += "\n\n上一轮结果/控制器反馈（继续已有进度，不从头重做）：\n" + json.dumps(previous, ensure_ascii=False)
            prompt += "\n\n现在已到计划执行时间。立即完成实施任务，最终输出符合给定 JSON schema。"
            final_path = LOGS / f"round-{round_number:03d}-result.json"
            if final_path.exists():
                final_path.unlink()
            argv = [str(NODE), str(CODEX), "exec", "--skip-git-repo-check", "--sandbox", "danger-full-access",
                    "-c", 'approval_policy="never"', "--cd", str(ROOT), "--json", "--color", "never",
                    "--output-schema", str(HERE / "result.schema.json"), "--output-last-message", str(final_path), "-"]
            with (LOGS / f"round-{round_number:03d}.jsonl").open("w", encoding="utf-8") as out, \
                 (LOGS / f"round-{round_number:03d}.stderr.log").open("w", encoding="utf-8") as err:
                process = run_process(argv, stdin=prompt, stdout=out, stderr=err)
            try:
                if process.returncode:
                    raise RuntimeError(f"codex exec 退出码 {process.returncode}")
                previous = json.loads(final_path.read_text(encoding="utf-8-sig"))
                if previous.get("status") not in {"COMPLETE", "CONTINUE", "BLOCKED"}:
                    raise ValueError("最终状态无效")
            except (OSError, ValueError, RuntimeError) as exc:
                failures += 1
                previous = dict(status="CONTINUE", controller_feedback=str(exc))
                if failures >= 3:
                    progress("BLOCKED", round=round_number, reason="Codex 连续三次启动/输出失败；检查日志、登录、网络或额度", details=str(exc))
                    return 3
                time.sleep(30)
                continue
            failures = 0
            if previous["status"] == "COMPLETE":
                problem = validate_completion(round_number)
                if not problem:
                    progress("COMPLETE", round=round_number, result=previous, final_report=str(BENCH / "final_report.md"))
                    return 0
                previous["status"] = "CONTINUE"
                previous["controller_feedback"] = "完成验收被拒绝，请修复并继续：" + problem
            if previous["status"] == "BLOCKED":
                blocker = previous.get("blocker", "未说明阻塞原因")
                blocked_count = blocked_count + 1 if blocker == previous_blocker else 1
                previous_blocker = blocker
                if blocked_count >= 3:
                    progress("BLOCKED", round=round_number, result=previous, reason=blocker)
                    return 2
                previous["controller_feedback"] = "先完成不依赖阻塞项的工作，确认该外部阻塞无法在已授权范围内解决。"
            else:
                blocked_count = 0
            progress("CONTINUING", round=round_number, result=previous)
    except Exception:
        (LOGS / "controller-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        progress("FAILED", reason="控制器异常，查看 controller-error.log")
        return 3
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
