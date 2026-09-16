import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time

from . import __version__
from .analysis import analyze, merge
from .common import digest, execute, read_json, relative, write_json
from .compilation import excluded, prepare
from .config import (TEMPLATE, CMAKE_TEMPLATE, TOOL_ROOT, default_managed_config_path,
                     load_config, register_managed_project, resolve_config_path,
                     project_profiles, profile_target, discover_arm_toolchains)
from .report import generate
from .html_report import REVIEW_PAGE, write_failure, write_html, review_records, category
from .review import review_all, resolve_command


def file_hashes(root, out, extra=(), audit_roots=()):
    paths = set(Path(p).resolve() for p in extra)
    roots = [root]
    for folder in sorted(audit_roots, key=lambda p: len(p.parts)):
        if not any(folder.is_relative_to(r) for r in roots):
            roots.append(folder)
    for base, dirs, files in (row for tree in roots for row in os.walk(tree)):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__"}
                   and (Path(base) / d).resolve() != out]
        for name in files:
            # Build products, model logs and reports are outputs, not analysis
            # inputs. Hashing them made every review stale and read gigabytes of
            # unrelated vendor assets. Explicit config/database/include inputs
            # above remain included regardless of extension.
            if (Path(name).suffix.lower() in {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".s", ".inc", ".ld", '.cmake'}
                    or name in {'CMakeLists.txt', 'CMakePresets.json', 'CMakeUserPresets.json'}):
                paths.add((Path(base) / name).resolve())
    result = {}
    for p in sorted(paths):
        if p.is_file():
            import hashlib
            h = hashlib.sha256()
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            result[relative(p, root)] = h.hexdigest()
    return result


def run(root, config_path=None, no_review=False, doctor_only=False):
    started = datetime.now(timezone.utc).isoformat()
    started_ns = time.time_ns()
    cfg, config_file = load_config(root, config_path)
    if no_review:
        cfg["review"]["enabled"] = False
    out = (root / cfg["analysis"].get("output_dir", ".ecra")).resolve()
    if out == root or not out.is_relative_to(root):
        raise ValueError("analysis.output_dir 必须是工程根目录下的独立子目录")
    out.mkdir(parents=True, exist_ok=True)
    lock = out / "scan.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError(f"已有扫描锁 {lock}；确认没有扫描进程后移除过期锁") from exc
    os.write(fd, json.dumps(dict(pid=os.getpid(), started=started)).encode())
    os.close(fd)
    run_info = dict(version=__version__, started=started, project_root=str(root), state="RUNNING")
    doctor = dict(project_root=str(root), python=sys.executable, python_version=sys.version,
                  semantics_found=True, config=str(config_file), ready_for_scan=False)
    log_lines = []

    def progress(message):
        print(message, flush=True)
        log_lines.append(datetime.now(timezone.utc).isoformat() + " " + message)
        (out / ("doctor.log" if doctor_only else "run.log")).write_text("\n".join(log_lines), encoding="utf-8")

    try:
        previous = {}
        old_report = out / "reports/global_static_concurrency.json"
        if old_report.is_file():
            previous = read_json(old_report)
        if (out / "run.json").is_file() and not doctor_only:
            snapshot = out / "snapshots" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            snapshot.mkdir(parents=True)
            for name in ("facts.json", "facts.db", "run.json", "scan_state.json", "input_manifest.json", "doctor.json", "run.log", "index.html", REVIEW_PAGE, "inventory", "reports", "review"):
                p = out / name
                if p.is_dir():
                    if name == 'review':
                        reviewed = {x.name.split('.attempt')[0] for x in p.glob('*.attempt*')}
                        def derived_packets(directory, names):
                            return [n for n in names if any(n.endswith(suffix) and n[:-len(suffix)] not in reviewed
                                    for suffix in ('.input.json','.prompt.txt'))]
                        shutil.copytree(p, snapshot / name, ignore=derived_packets)
                    else:
                        shutil.copytree(p, snapshot / name)
                elif p.is_file():
                    shutil.copy2(p, snapshot / name)
        if not doctor_only:
            (out/'scan_state.json').unlink(missing_ok=True)
            write_json(out / "run.json", run_info)
        progress("检查配置、libclang 和真实编译数据库…")
        from clang import cindex
        if cfg["analysis"].get("libclang_file"):
            cindex.Config.set_library_file(cfg["analysis"]["libclang_file"])
        cindex.Index.create()
        doctor["libclang_found"] = True
        from .scope import AuditScope
        scope = AuditScope(root, cfg['analysis'])
        if scope.active:
            progress('排查目录：' + (', '.join(scope.include_dirs) or '全部') + '；排除目录：' + (', '.join(scope.exclude_dirs) or '无'))
            progress('范围外编译依赖只用于恢复调用链和目标变量的访问，不生成第三方变量候选。')
        units, compilation = prepare(root, cfg, progress=progress, build_firmware=not doctor_only)
        doctor.update(compilation, compile_database_found=True, translation_units_total=len(units), ready_for_scan=True)
        doctor['review_enabled'] = cfg['review'].get('enabled', True)
        if doctor['review_enabled']:
            try:
                command=resolve_command(cfg['review'].get('command',['opencode']))
                doctor.update(opencode_command_found=True, opencode_executable=command[0])
            except ValueError as exc:
                doctor.update(opencode_command_found=False, opencode_error=str(exc))
                progress('源码仍会正常盘点；OpenCode 尚不可用：'+str(exc))
        write_json(out / "doctor.json", doctor)
        if doctor_only:
            run_info["state"] = "DOCTOR_READY"
            if doctor.get('opencode_command_found') is False:
                progress('源码分析环境可用；请安装 OpenCode 或修正 review.command。')
                return 2
            progress("环境检查通过。尚未进行源码覆盖、模型提供商连接和并发分析。")
            return 0
        # CMake may regenerate headers legitimately before extraction begins.
        started_ns = time.time_ns()
        response_files = {p for u in units for p in u.get('response_files', [])}
        sources = [u['source'] for u in units]
        sources.extend(str((root / p).resolve()) for p in compilation.get('assembly_sources', []))
        before = file_hashes(root, out, [config_file, compilation["compile_database"], *sources, *response_files], scope.includes)
        worker_dir = out / "workers"
        worker_dir.mkdir(exist_ok=True)
        parts, all_includes = [], set()
        tool_root = Path(__file__).resolve().parent.parent
        env = os.environ.copy()
        env["PYTHONPATH"] = str(tool_root) + os.pathsep + env.get("PYTHONPATH", "")
        for i, unit in enumerate(units):
            role = ' [依赖]' if scope.active and unit.get('audit_role') == 'dependency' else ''
            progress(f"Clang {i + 1}/{len(units)}{role}: {unit['source_file']}")
            request = worker_dir / (unit["tu_id"] + ".request.json")
            response = worker_dir / (unit["tu_id"] + ".response.json")
            write_json(request, dict(root=str(root), unit=unit, config=cfg))
            if response.exists():
                response.unlink()
            try:
                proc = execute([sys.executable, "-m", "ecra.extract", str(request), str(response)],
                               cwd=tool_root, env=env, timeout=float(cfg["analysis"].get("parse_timeout_seconds", 180)))
                if proc.returncode or not response.is_file():
                    raise ValueError(f"提取器退出 {proc.returncode}: {proc.stderr[-4000:]}")
                part = read_json(response)
            except Exception as exc:
                part = dict(parse_status="FAILED", diagnostics=[dict(severity=4, message=str(exc))])
            if unit["missing_defines"]:
                part["parse_status"] = "FAILED"
                part.setdefault("diagnostics", []).append(dict(severity=4, message="缺少预期宏: " + ", ".join(unit["missing_defines"])))
            unit["parse_status"] = part["parse_status"]
            unit["diagnostics"] = part.get("diagnostics", [])
            unit["includes"] = part.get("includes", [])
            for variable in part.get("variables", []):
                variable["parse_status"] = part["parse_status"]
            all_includes.update(part.get("includes", []))
            parts.append(part)
        facts = merge(parts)
        facts['translation_units'] = units
        from .supplemental import supplement, selected_files, build_file_coverage
        all_supplemental_tus, supplemental_includes = supplement(
            root, out, facts, units, cfg, scope, worker_dir, env, tool_root, progress)
        all_includes.update(supplemental_includes)
        facts['translation_units'] = units + all_supplemental_tus
        included_paths = {relative(p, root) for u in units for p in u.get('includes', [])}
        unlisted_headers = [p for p in selected_files(root, scope, out)
                            if Path(p).suffix.lower() in {'.h', '.hh', '.hpp', '.hxx', '.inc'} and p not in included_paths]
        compilation['unlisted_headers'] = unlisted_headers
        if unlisted_headers:
            facts['unknowns'].append(dict(kind='HEADERS_NOT_INCLUDED', files=unlisted_headers,
                hint='已尝试补充声明盘点；这些头文件不属于当前构建的访问证据。'))
        after = file_hashes(root, out, [config_file, compilation['compile_database'],
            *sources, *all_includes, *response_files], scope.includes)
        if any(after.get(p) != h for p, h in before.items()):
            facts["unknowns"].append(dict(kind="SOURCE_CHANGED_DURING_SCAN"))
        for include in all_includes:
            p = Path(include)
            if p.is_file() and p.stat().st_mtime_ns >= started_ns:
                facts["unknowns"].append(dict(kind="HEADER_CHANGED_DURING_SCAN", file=relative(p, root)))
        # Compiling the same source under multiple flag sets requires separate run variants.
        if len({u["source_file"] for u in units}) != len(units):
            facts["unknowns"].append(dict(kind="MULTIPLE_BUILD_VARIANTS", hint="为每个固件配置分别导出数据库并扫描"))
        known_functions = {f["function_id"] for f in facts["functions"]}
        summarized = {"memcpy", "memmove", "memset", "memcmp", "xTaskCreate", "xTaskCreateStatic", "osThreadNew", "xTaskCreatePinnedToCore"}
        for call in facts["calls"]:
            if call["call_kind"] == "DIRECT" and call["callee_function_id"] not in known_functions and call["callee_name"] not in summarized:
                facts["unknowns"].append(dict(kind="EXTERNAL_CALLEE", function_id=call["caller_function_id"],
                                              callee=call["callee_name"], file=call["file"], line=call["line"]))
        for path in compilation["unlisted_sources"]:
            facts["unknowns"].append(dict(kind="SOURCE_NOT_IN_DATABASE", file=path))
        for unit in units:
            if unit["parse_status"] != "PARSED":
                facts["unknowns"].append(dict(kind="PARSE_FAILED", file=unit["source_file"], diagnostics=unit["diagnostics"]))
        parsed = sum(u["parse_status"] == "PARSED" for u in units)
        cov = dict(translation_units_total=len(units), translation_units_parsed=parsed,
                   translation_units_failed=len(units) - parsed, parse_coverage_percent=round(100 * parsed / len(units), 2),
                   **compilation)
        # Build per-file coverage table for source-level accountability
        from .supplemental import build_file_coverage
        report = analyze(facts, cfg, cov, root=root)
        cov['file_coverage'] = build_file_coverage(facts, units, all_supplemental_tus, scope, root, output_dir=out)
        # Local fixes to extraction/review code must invalidate prior conclusions
        # even before a packaged release changes the version number.
        from .workflow import engine_digest, analysis_config
        analysis_inputs = {p:h for p,h in after.items() if p != relative(config_file,root)}
        fingerprint = digest([__version__, engine_digest(), analysis_config(cfg), analysis_inputs, [u["arguments"] for u in units]])
        report.update(fingerprint=fingerprint, generated_at=started, tool_version=__version__)
        try:
            git = execute(["git", "rev-parse", "HEAD"], cwd=root, timeout=10)
            report["git_commit"] = git.stdout.strip() if git.returncode == 0 else "unknown"
        except OSError:
            report["git_commit"] = "unknown"
        old_ids = {f["finding_id"] for f in previous.get("findings", [])}
        new_ids = {f["finding_id"] for f in report["findings"]}
        report["baseline"] = dict(new=sorted(new_ids - old_ids), unchanged=sorted(new_ids & old_ids),
                                  no_longer_observed=sorted(old_ids - new_ids),
                                  note="不再观察到不等于已修复；覆盖变化和证据变化必须复核")
        write_json(out / "input_manifest.json", after)
        generate(out, facts, report, [])
        from .workflow import save_scan
        save_scan(root, out, cfg, config_file, report)
        progress(f"已盘点 {len(facts['variables'])} 个变量，生成 {len(report['findings'])} 个候选/盲区复核项。")
        last_checkpoint = time.monotonic()

        def checkpoint(current):
            nonlocal last_checkpoint
            if time.monotonic() - last_checkpoint < 30:
                return
            records = review_records(report, current)
            report['review_summary'] = dict(total=len(records), unresolved=sum(category(r) == 'unresolved' for r in records))
            report['run_status'] = 'REVIEW_RUNNING'
            write_html(out, facts, report, current)
            last_checkpoint = time.monotonic()

        reviews = review_all(root, out, cfg, facts, report, fingerprint, progress, on_result=checkpoint)
        end_hashes = file_hashes(root, out, [config_file, compilation["compile_database"], *sources, *all_includes, *response_files], scope.includes)
        if end_hashes != after:
            report["analysis_status"] = "INCOMPLETE"
            report["limitations"].append("复核期间源码或输入发生变化；本轮证据需重新生成。")
            for r in reviews:
                r["state"] = "STALE"
        pending = sum(r["state"] != "DONE" or r["status"] in {"NEED_MORE_CONTEXT", "LIKELY"} for r in reviews)
        report["review_summary"] = dict(total=len(reviews), unresolved=pending)
        review_by_id = {r["finding_id"]: r for r in reviews}
        for finding in report["findings"]:
            r = review_by_id.get(finding["finding_id"], {})
            finding["review_state"] = r.get("state", "PENDING")
            if r.get("state") == "DONE":
                finding["status"] = r["status"]
                finding["review"] = r["answer"]
        report["run_status"] = "INCOMPLETE" if report["analysis_status"] == "INCOMPLETE" or pending else "REVIEW_COMPLETE"
        generate(out, facts, report, reviews)
        code = 2 if report["run_status"] == "INCOMPLETE" else (1 if report["findings"] else 0)
        run_info.update(state=report["run_status"], exit_code=code, fingerprint=fingerprint,
                        report=str(out / "index.html"), review_report=str(out / REVIEW_PAGE), review_summary=report["review_summary"])
        progress(f"完成：{report['run_status']}；变量与风险 {out / 'index.html'}；OpenCode 结果 {out / REVIEW_PAGE}")
        if cfg['analysis'].get('open_report', False):
            try:
                import webbrowser
                if not webbrowser.open((out / 'index.html').as_uri()):
                    progress('浏览器未自动打开，请打开上述 index.html。')
            except Exception as exc:
                progress(f'报告已生成，浏览器未打开：{exc}')
        return code
    except KeyboardInterrupt:
        run_info.update(state='INTERRUPTED', exit_code=130)
        if not doctor_only and (out/'scan_state.json').exists():
            queue=read_json(out/'review/queue.json')
            report['run_status']='INTERRUPTED'
            generate(out, facts, report, queue)
        progress('已中断；完成静态扫描后可用 review 继续复核，否则重新运行 run。')
        return 130
    except Exception as exc:
        run_info.update(state="FAILED", exit_code=3, error=f"{type(exc).__name__}: {exc}")
        doctor.update(ready_for_scan=False, error=run_info["error"])
        write_json(out / "doctor.json", doctor)
        if not doctor_only:
            write_failure(out)
        progress("失败：" + run_info["error"])
        return 3
    finally:
        run_info["finished"] = datetime.now(timezone.utc).isoformat()
        if not doctor_only:
            write_json(out / "run.json", run_info)
        lock.unlink(missing_ok=True)


def main(argv=None):
    # Match UTF-8 report files and Windows IDE terminals, regardless of ACP.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="STM32 全局/static 清单、读写调用链与 OpenCode 并发复核")
    parser.add_argument("command", nargs="?", choices=["run", "init", "doctor", "review", "report", "status", "projects"], default="run",
                        help='run 全流程；review 继续复核；report 刷新报告；status 查看进度；doctor 环境检查')
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--project", type=Path, help="固件工程根目录，默认当前目录")
    target.add_argument('--profile', help='工具侧项目 id；例如 serial-continue，无需再次填写固件路径')
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--compile-database", help="init 时写入真实编译数据库路径（相对工程根目录）")
    parser.add_argument("--model", help="init 时写入已配置的 OpenCode provider/model")
    parser.add_argument('--toolchain-file', help='init 时指定 CMake Arm 工具链文件（相对固件根目录）')
    parser.add_argument("--no-review", action="store_true", help="只生成静态报告与待复核清单，不调用 OpenCode")
    parser.add_argument("--json", action="store_true", help="status 输出可供脚本读取的 JSON")
    args = parser.parse_args(argv)
    root = (args.project or Path.cwd()).resolve()
    try:
        if args.command == 'projects':
            if args.project or args.profile or args.config or args.compile_database or args.model or args.no_review or args.toolchain_file:
                raise ValueError('projects 只接受 --json')
            entries = project_profiles()
            if args.json:
                print(json.dumps(entries, ensure_ascii=False, indent=2))
            else:
                for entry in entries:
                    print(f"{entry['id']}\n  固件：{entry['root']}\n  配置：{entry['semantics']}")
                if not entries:
                    print('尚未登记项目；运行 init --project <固件目录>')
            return 0
        if args.profile:
            if args.config or args.command == 'init':
                raise ValueError('--profile 用于已登记项目，不可与 init / --config 同用')
            root, selected_config = profile_target(args.profile)
            args.config = str(selected_config)
        if not root.is_dir():
            raise ValueError(f"工程目录不存在: {root}")
        if args.json and args.command != 'status':
            raise ValueError('--json 仅用于 status')
        if args.command != 'init' and (args.compile_database is not None or args.model is not None or args.toolchain_file is not None):
            raise ValueError('--compile-database / --model / --toolchain-file 仅用于 init；已有工程请编辑 semantics.yaml')
        if args.command in {'review', 'report', 'status'}:
            from .workflow import saved_run, status
            if args.no_review:
                raise ValueError('--no-review 仅用于 run；仅刷新报告请使用 report')
            if args.command == 'status':
                info=status(root,args.config)
                if args.json:
                    print(json.dumps(info, ensure_ascii=False, indent=2))
                else:
                    print(f"工程：{root}\n已保存状态：{info['state']}")
                    if 'variables' in info:
                        print(f"变量 {info['variables']} · 复核项 {info['findings']} · 未完成 {info['unresolved']}")
                    print('下一步：'+info['next_action'])
                    if 'inventory_html' in info:
                        print('变量报告：'+info['inventory_html']+'\n复核报告：'+info['review_html'])
                return 0
            return saved_run(root, args.config, render_only=args.command=='report')
        if args.command == "init":
            import yaml
            # Configurations belong to the analyzer, not the firmware project.
            # An explicit --config remains project-relative for backwards-compatible
            # one-off use; the normal init path is centrally managed and indexed.
            path = resolve_config_path(root, args.config) if args.config else default_managed_config_path(root)
            if path.exists():
                raise ValueError(f"配置已存在，不覆盖: {path}")
            managed_cmake = (root/'CMakeLists.txt').is_file() and args.compile_database is None
            content = CMAKE_TEMPLATE if managed_cmake else TEMPLATE
            # Keep custom BSP/User/Services directories. A shortlist of familiar
            # Cube folders silently excluded application code on other boards.
            if not managed_cmake:
                content = content.replace('include_dirs: []', 'include_dirs: [.]', 1)
                content = content.replace('exclude_dirs: []',
                    'exclude_dirs: [Drivers, Middlewares, ThirdParty, build, .ecra]', 1)
            legacy = root / '.ecra/semantics.yaml'
            migrating = args.config is None and legacy.is_file()
            if migrating:
                if args.compile_database or args.model or args.toolchain_file:
                    raise ValueError('迁移旧配置时保留全部原值；请先 init，再编辑工具侧配置')
                load_config(root, legacy)  # Reject malformed input before copying.
                content = legacy.read_text(encoding='utf-8-sig')
            if args.toolchain_file and not managed_cmake:
                raise ValueError('--toolchain-file 需要 CMake 工程，且不可与 --compile-database 同用')
            if managed_cmake and not migrating:
                choices = [(root/args.toolchain_file).resolve()] if args.toolchain_file else discover_arm_toolchains(root)
                if len(choices) == 1:
                    if not choices[0].is_file():
                        raise ValueError(f'工具链文件不存在: {choices[0]}')
                    content = content.replace('# toolchain_file: cmake/arm-none-eabi.cmake',
                        'toolchain_file: ' + json.dumps(relative(choices[0], root), ensure_ascii=False), 1)
                elif choices:
                    print('发现多个 Arm 工具链；请在配置中选择 toolchain_file：' + ', '.join(map(str, choices)))
            # Serialize user values as quoted YAML scalars; Windows paths and
            # characters such as '#' must survive without becoming YAML syntax.
            if args.compile_database is not None:
                content = content.replace('compile_database: auto', 'compile_database: ' +
                                          json.dumps(args.compile_database, ensure_ascii=False), 1)
            if args.model is not None:
                if not args.model.strip() or '/' not in args.model:
                    raise ValueError('--model 必须是已配置的 provider/model')
                content = content.replace('# model: provider/model', 'model: ' +
                                          json.dumps(args.model, ensure_ascii=False), 1)
                content = content.replace('enabled: false', 'enabled: true', 1)
            yaml.safe_load(content)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', encoding='utf-8') as stream:
                stream.write(content)
            from .config import PROJECT_INDEX
            if args.config is None or path.is_relative_to(PROJECT_INDEX.parent):
                try:
                    register_managed_project(root, path)
                except Exception:
                    path.unlink()  # Only the file created exclusively above; retry remains possible.
                    raise
            print(f"已生成 {path}\n确认排查/排除目录、CMake 配置和复核设置后即可执行一键排查。")
            if migrating:
                print(f'已迁移旧配置，原文件保留为备份：{legacy}；后续默认使用工具侧配置。')
            launcher = f'"{sys.executable}" "{Path(__file__).resolve().parent.parent / "run_ecra.py"}"'
            if not (Path(__file__).resolve().parent.parent / 'run_ecra.py').is_file():
                launcher = 'ecra'
            elif os.name == 'nt':
                launcher = '& ' + launcher  # PowerShell quoted executable
            common = f' --project "{root}" --config "{path}"'
            print('环境检查：' + launcher + ' doctor' + common)
            print('一键排查：' + launcher + common)
            return 0
        return run(root, args.config, args.no_review, args.command == "doctor")
    except (ValueError, OSError, ImportError) as exc:
        print(f"ECRA: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
