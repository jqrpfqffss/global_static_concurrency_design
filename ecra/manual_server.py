"""Loopback-only report viewer and human audit API (standard library only)."""
import json
import os
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlsplit

from .common import read_json
from .config import load_config
from .manual_review import Conflict, Ledger, catalog, progress
from .workflow import checked_scan, checked_reviews, output_path, read_queue

MAX_BODY = 8 * 1024 * 1024


class ReviewApplication:
    def __init__(self, root, config_path):
        self.root = root.resolve()
        self.config_path = config_path
        self.cfg, self.config_file = load_config(root, config_path)
        self.out = output_path(root, self.cfg)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.ledger = None
        self.items = {}
        self.valid = False
        self.error = ''
        self.fingerprint = ''
        self.refresh()
        if not self.valid:
            raise ValueError('人工确认服务需要有效扫描结果：' + self.error)
        if not (self.out / 'index.html').is_file():
            raise ValueError('缺少 index.html，请先执行 report')

    def refresh(self, owns_scan_lock=False):
        # Never invoke extraction, generate(), or review_all from this service.
        self.valid, self.error = False, ''
        try:
            self.cfg, self.config_file = load_config(self.root, self.config_path)
            if output_path(self.root, self.cfg) != self.out:
                raise ValueError('输出目录已改变，请重新启动服务')
            if not owns_scan_lock and (self.out / 'scan.lock').exists():
                self.error = '扫描或复核正在运行，请结束后重新加载'
                # A temporary writer lock suspends validity; it must not
                # permanently invalidate an otherwise identical later scan.
                return self.ledger.paused(self.items) if self.ledger else []
            facts, clean, state = checked_scan(self.root, self.out, self.cfg, self.config_file)
            if any(u.get('parse_status') in {'FAILED', 'PARTIAL'} for u in facts.get('translation_units', [])):
                raise ValueError('源码解析不完整，不能沿用人工结论；请修复后重新扫描')
            if any(u.get('kind') in {'SOURCE_CHANGED_DURING_SCAN', 'HEADER_CHANGED_DURING_SCAN'} for u in facts.get('unknowns', [])):
                raise ValueError('扫描过程中源码发生变化，请重新扫描')
            report = read_json(self.out / 'reports/global_static_concurrency.json')
            if report.get('stale_reason'):
                raise ValueError(report['stale_reason'])
            queue = read_queue(self.out)
            verified = checked_reviews(self.root, self.out, queue, state['fingerprint'])
            from .html_report import review_records
            report['review_records'] = review_records(report, verified)
            pid, items = catalog(self.root, self.out, self.cfg, facts, report)
            checked_scan(self.root, self.out, self.cfg, self.config_file)
            self.ledger = self.ledger or Ledger(self.out, pid)
            self.items = items
            self.fingerprint = report['fingerprint']
            self.valid = True
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.error = str(exc)
        if self.ledger:
            return self.ledger.sync(self.items, self.valid, self.error)
        return []

    def state(self, rows):
        return dict(valid=self.valid, error=self.error, report_fingerprint=self.fingerprint,
                    project_id=self.ledger.project_id, token=self.token, rows=rows, progress=progress(rows),
                    revisions=self.ledger.revisions())


def make_server(root, config_path=None, port=0):
    app = ReviewApplication(root, config_path)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass

        def reply(self, code, data, content_type='application/json; charset=utf-8'):
            body = json.dumps(data, ensure_ascii=False).encode('utf-8') if not isinstance(data, bytes) else data
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'same-origin')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def trusted(self, write=False):
            origin = 'http://' + self.server.authority
            if self.headers.get('Host') != self.server.authority:
                raise PermissionError('Host 校验失败')
            if self.headers.get('Sec-Fetch-Site', 'same-origin') not in {'same-origin', 'none'}:
                raise PermissionError('禁止跨域访问')
            if self.headers.get('Origin') not in (None, origin):
                raise PermissionError('Origin 校验失败')
            if write and (self.headers.get('Origin') != origin or
                          not secrets.compare_digest(self.headers.get('X-ECRA-Token', ''), app.token)):
                raise PermissionError('请求来源或安全令牌无效')

        def do_GET(self):
            try:
                self.trusted()
                url = urlsplit(self.path)
                if url.path.startswith('/api/'):
                    with app.lock:
                        rows = app.refresh()
                        if url.path == '/api/state':
                            self.reply(200, app.state(rows))
                        elif url.path == '/api/history':
                            vid = parse_qs(url.query).get('variable_id', [None])[0]
                            self.reply(200, dict(history=app.ledger.history(vid)))
                        elif url.path == '/api/export':
                            self.reply(200, app.ledger.export())
                        else:
                            self.reply(404, dict(error='接口不存在'))
                    return
                from .html_report import REVIEW_PAGE, QUALITY_PAGE
                names = {'/': 'index.html', '/index.html': 'index.html',
                         '/' + REVIEW_PAGE: REVIEW_PAGE, '/' + QUALITY_PAGE: QUALITY_PAGE,
                         '/reports/global_static_concurrency.json': 'reports/global_static_concurrency.json',
                         '/review/queue.json': 'review/queue.json'}
                # Preserve existing prompt/receipt/log links, without opening a
                # generic disk-file endpoint or exposing the human database.
                parts = PurePosixPath(url.path).parts
                if len(parts) == 3 and parts[1] == 'review' and '\\' not in url.path:
                    report = read_json(app.out / 'reports/global_static_concurrency.json')
                    ids = [f['finding_id'] for f in report.get('findings', []) + report.get('review_safe_samples', [])]
                    if any(parts[2].startswith(fid + '.') for fid in ids) and PurePosixPath(parts[2]).suffix in {'.json', '.jsonl', '.txt'}:
                        names[url.path] = 'review/' + parts[2]
                if url.path not in names:
                    self.reply(404, dict(error='文件不在报告允许列表中'))
                    return
                report_file = (app.out / names[url.path]).resolve()
                if not report_file.is_relative_to(app.out):
                    raise PermissionError('报告路径超出输出目录')
                content_type = ('text/html' if report_file.suffix == '.html' else
                                'application/json' if report_file.suffix == '.json' else 'text/plain')
                self.reply(200, report_file.read_bytes(), content_type + '; charset=utf-8')
            except PermissionError as exc:
                self.reply(403, dict(error=str(exc)))
            except Exception as exc:
                self.reply(503, dict(error='读取失败：' + str(exc)))

        def do_POST(self):
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_BODY:
                    self.reply(413, dict(error='请求体为空或超过 8 MiB'))
                    return
                raw = self.rfile.read(length)
                self.trusted(write=True)
                if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('仅支持 application/json 请求')
                request = json.loads(raw)
                if not isinstance(request, dict):
                    raise ValueError('请求必须是 JSON 对象')
                with app.lock:
                    lock = app.out / 'scan.lock'
                    try:
                        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    except FileExistsError as exc:
                        raise Conflict('扫描或复核正在运行，请稍后重新加载') from exc
                    try:
                        os.write(fd, str(os.getpid()).encode())
                        os.close(fd)
                        app.refresh(owns_scan_lock=True)
                        if not app.valid:
                            raise Conflict('当前扫描证据无效：' + app.error)
                        if request.get('report_fingerprint') != app.fingerprint:
                            raise Conflict('报告版本已变化，请重新打开报告')
                        path = urlsplit(self.path).path
                        if path == '/api/decision':
                            app.ledger.submit(app.items, request)
                        elif path == '/api/import':
                            app.ledger.import_data(app.items, request.get('document'), request.get('revisions'))
                        else:
                            self.reply(404, dict(error='接口不存在'))
                            return
                        self.reply(200, app.state(app.ledger.sync(app.items)))
                    finally:
                        lock.unlink(missing_ok=True)
            except PermissionError as exc:
                self.reply(403, dict(error=str(exc)))
            except Conflict as exc:
                self.reply(409, dict(error=str(exc)))
            except (ValueError, TypeError, KeyError) as exc:
                self.reply(400, dict(error=str(exc)))
            except Exception as exc:
                self.reply(503, dict(error='保存失败，未确认成功：' + str(exc)))

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.authority = '127.0.0.1:' + str(server.server_address[1])
    server.app = app
    return server


def serve(root, config_path=None, port=0, open_browser=True):
    with make_server(root, config_path, port) as server:
        url = 'http://' + server.authority + '/index.html'
        print('人工确认页面：' + url + '\n确认记录保存于：' + str(server.app.ledger.path) + '\n按 Ctrl+C 停止服务。', flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever(poll_interval=0.3)
        except KeyboardInterrupt:
            pass
    return 0
