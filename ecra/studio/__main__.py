import argparse
import json
from pathlib import Path
import socket
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
    import uvicorn
    from .server import create_app
    from ..workspace import no_links
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', args.port)); sock.listen(128)
    authority = '127.0.0.1:' + str(sock.getsockname()[1])
    app = create_app(args.data_root, authority=authority)
    url = 'http://' + authority + '/#session=' + app.state.session_token
    if args.session_file:
        target = no_links(args.session_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(dict(url=url, authority=authority, token=app.state.session_token)), encoding='utf-8')
    print('ECRA Studio；完整发布门禁状态见 docs/rearchitecture。', flush=True)
    print('数据目录：' + str(app.state.data_root), flush=True)
    print('浏览器入口：' + url, flush=True)
    print('关闭本启动窗口或按 Ctrl+C 结束本地服务。', flush=True)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=sock.getsockname()[1], log_level='warning'))
    if not args.no_browser:
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
        sock.close()
        if args.session_file:
            target.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
