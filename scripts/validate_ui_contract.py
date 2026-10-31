"""Static UI contract checks complementing, never replacing, browser UAT."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    app=(root/'studio/src/App.vue').read_text(encoding='utf-8')
    source='\n'.join(path.read_text(encoding='utf-8') for path in (root/'studio/src').glob('*') if path.is_file())
    api=(root/'ecra/studio/server.py').read_text(encoding='utf-8')
    index=(root/'ecra/studio/web/index.html').read_text(encoding='utf-8')
    store=(root/'ecra/scan_store.py').read_text(encoding='utf-8')
    # Polling the real job endpoint is a timer, not simulated completion.
    # Permit only this named poll callback; still reject delayed success mocks.
    timers=re.findall(r'setTimeout\s*\(\s*([^,]+),',source)
    expected=['项目概览','工程配置','扫描任务','变量与风险','覆盖与诊断','OpenCode 复核','人工确认','历史与对比','数据与共享']
    nav=app[app.index('const navigation'):app.index('const route')]
    checks={
        'frozen_navigation_order':all(nav.index(first)<nav.index(second) for first,second in zip(expected,expected[1:])),
        'no_fake_timeout_or_raw_html':not re.search(r'v-html|innerHTML',source) and all(callback.strip()=='poll' for callback in timers),
        'no_remote_frontend_assets':not re.search(r'(?:src|href)=[\"\']https?://',index+source),
        'server_side_page_limit':bool(re.search(r'''limit=50|limit\s*:\s*['"]50['"]''',source)) and 'QueryService' in api and 'not 1 <= limit <= 200' in store,
        'three_independent_dimensions':all(value in app for value in ['static_classification','human','OpenCode']),
        'real_write_receipts':"result.saved" in app and "dict(saved=True, event=event)" in api,
        'real_scan_task_component':"SQLITE_NATIVE_SCAN" in api and '<TaskCenter' in app,
        'real_scan_task_endpoints':all(route in api for route in ["'/api/tasks'", "'/api/tasks/{task_id}/stop'", "'/api/tasks/{task_id}/retry'"]),
        'real_cleanup_endpoints_and_confirmation':all(text in api for text in ["'/api/storage/cleanup'", "payload.get('confirmed') is not True"]),
        'bounded_source_and_call_navigation':all(text in api for text in ["'/api/scans/{scan_id}/source-window'","'/api/scans/{scan_id}/call-neighbors'"]),
        'session_origin_host_checks':all(text in api for text in ['compare_digest','origin !=','headers.get(\'host\')']),
    }
    result=dict(passed=all(checks.values()),checks=checks,
        api_routes=re.findall(r"@app\.(get|post|put)\('([^']+)'\)",api),
        source_hashes={str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for path in (root/'studio/src').glob('*') if path.is_file()},
        scope='Static contracts only; no claim of U01–U24 completion, visual quality or native Windows DPI')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'],checks=checks)))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
