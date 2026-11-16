import argparse
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import webbrowser


def main(argv=None):
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='ECRA Studio 本地归档与人工确认工作台（开发预览）')
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--session-file', type=Path, help='自动验收使用；包含临时会话凭据')
    args = parser.parse_args(argv)
    from ..workspace import managed_path
    from ..studio_preferences import startup_selection
    from ..runtime_storage import initialize
    try:
        selection = startup_selection(args.data_root)
        target = (managed_path(args.session_file, label='--session-file') if args.session_file else None)
        if target is not None and not target.is_relative_to(selection['root']/'work'):
            raise ValueError(f'--session-file 必须位于当前数据目录的 work 下: {target}')
        initialize(selection['root'])
        return _serve(args, selection, target)
    except (ValueError, OSError, ImportError) as exc:
        print(f'ECRA Studio: {exc}', file=sys.stderr)
        return 3


def _serve(args, selection, target):
    import uvicorn
    from .server import _create_app
    from ..config import TOOL_ROOT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', args.port))
        sock.listen(128)
        authority = '127.0.0.1:' + str(sock.getsockname()[1])
        app = _create_app(selection['root'], token=None, authority=authority, startup=selection)
        return _run_server(uvicorn, sock, authority, app, TOOL_ROOT, target, args.no_browser)


def _run_server(uvicorn, sock, authority, app, tool, target, no_browser):
    url = 'http://' + authority + '/#session=' + app.state.session_token
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        from ..common import replace_file
        pending=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=target.parent,
                    prefix=target.name+'.',suffix='.pending',delete=False) as stream:
                pending=Path(stream.name)
                json.dump(dict(url=url,authority=authority,token=app.state.session_token),stream,ensure_ascii=False)
                stream.flush();os.fsync(stream.fileno())
            replace_file(pending,target)
        finally:
            if pending is not None:pending.unlink(missing_ok=True)
    print('ECRA Studio；完整发布门禁状态见 docs/rearchitecture。', flush=True)
    print('工具目录：' + str(tool), flush=True)
    print('数据目录：' + str(app.state.data_root), flush=True)
    if app.state.preference_warning:
        print('启动设置恢复提示：' + app.state.preference_warning, flush=True)
    print('浏览器入口：' + url, flush=True)
    print('关闭本启动窗口或按 Ctrl+C 结束本地服务。', flush=True)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=sock.getsockname()[1], log_level='warning'))
    if not no_browser:
        # Wait for actual server startup; no fixed fake startup delay.
        def open_when_ready():
            while not server.started and not server.should_exit:
                threading.Event().wait(0.05)
            if server.started:
                webbrowser.open(url)
        threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        server.run(sockets=[sock])
    finally:
        app.state.task_manager.close()
        if target is not None:
            target.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
