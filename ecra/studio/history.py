"""Paged archive catalog. Display metadata never establishes source validity."""
from contextlib import closing
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from ..report_package import IDENTITY
from ..scan_identity import query as identity_query
from ..scan_store import EvidenceProvider
from ..storage_activity import DataActivity
from ..workspace import no_links


def _date(value):
    if not value:
        return None
    try:
        result = date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError()
        return result
    except ValueError as exc:
        raise ValueError('历史日期须为 YYYY-MM-DD（UTC）') from exc


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            return None  # no invented timezone for legacy records
        return result.astimezone(timezone.utc).isoformat(timespec='microseconds')
    except (ValueError, OverflowError):
        return None


def _rows(data):
    root = no_links(data/'scans')
    if not root.exists():
        return
    # scandir streams names; Path.iterdir on Python3.10 uses a full os.listdir.
    with os.scandir(root) as entries:
        yield from _entries(root, entries)


def _entries(root, entries):
    for entry in entries:
        folder = root/entry.name
        item = dict(scan_id=folder.name, state='FAILED', mode='OFFLINE_ARCHIVE', identity={},
                    scan_mode='UNKNOWN', recorded_at=None, date_source=None,
                    can_open=False, can_confirm=False, error=None)
        try:
            no_links(folder)
            if not folder.is_dir():
                continue
            db = no_links(folder/'scan.db')
            manifest_path = no_links(folder/'manifest.json')
            if not db.is_file():
                continue
            if no_links(folder/'storage.json').is_file() and not manifest_path.is_file():
                continue
            if not IDENTITY.fullmatch(folder.name):
                raise ValueError('扫描目录身份无效')
            provider = EvidenceProvider(db)
            binding = provider.metadata()
            if binding['scan_id'] != folder.name:
                raise ValueError('扫描目录与静态身份不一致')
            item.update(binding)
            if not isinstance(binding['state'], str):
                raise ValueError('扫描状态不是文本')
            item['identity'] = identity_query(provider)
            item['recorded_at'] = item['identity']['generated_at']
            item['date_source'] = '归档生成时间'
            try:
                node = provider.node(provider.resolve('report', ['git_diff']), limit=1)
                item['scan_mode'] = 'DIFF' if node['kind'] == 'object' else 'FULL' if node['kind'] == 'null' else 'UNKNOWN'
            except KeyError:
                item['scan_mode'] = 'FULL'
            try:
                degraded = provider.node(provider.resolve('provenance', ['legacy_degraded']), limit=1).get('value') is True
            except KeyError:
                degraded = False
            if manifest_path.is_file():
                # Display manifest is small; no arbitrary-size read on corrupt input.
                if manifest_path.stat().st_size > 1024*1024:
                    raise ValueError('归档显示清单过大；请核对原件')
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                if not isinstance(manifest, dict):
                    raise ValueError('归档清单格式无效')
                if manifest.get('format') == 'ECRA_LOCAL_SCAN':
                    if any(manifest.get(key) != binding[key] for key in ['scan_id', 'project_id', 'facts_hash', 'report_hash']):
                        raise ValueError('本机发布清单与静态库身份不一致')
                    if not isinstance(manifest.get('state'), str):
                        raise ValueError('本机发布状态无效')
                    item.update(mode='LOCAL_SNAPSHOT', state=manifest['state'],
                                recorded_at=manifest.get('completed_at'), date_source='本机发布完成时间')
            item.update(can_open=True, can_confirm=not degraded)
        except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as exc:
            item.update(state='FAILED', can_open=False, can_confirm=False, error=str(exc))
        item['recorded_at_utc'] = _timestamp(item['recorded_at'])
        yield item


def history(data, *, project='', profile='', core='', git='', scan_mode='', state='',
            date_from='', date_to='', offset=0, limit=20):
    EvidenceProvider._bounds(offset, limit)
    if limit > 100 or offset > 2**63-1:
        raise ValueError('历史分页要求 limit=1–100，offset为有效非负整数')
    filters = dict(project=project, profile=profile, core=core, git=git, scan_mode=scan_mode, state=state)
    if any(not isinstance(value, str) or len(value) > 256 for value in filters.values()):
        raise ValueError('历史检索字段须为不超过256字的文本')
    if scan_mode not in {'', 'FULL', 'DIFF', 'UNKNOWN'}:
        raise ValueError('扫描模式须为 FULL / DIFF / UNKNOWN')
    start, end = _date(date_from), _date(date_to)
    if start and end and start > end:
        raise ValueError('开始日期不能晚于结束日期')
    data = no_links(Path(data))
    with DataActivity(data), tempfile.TemporaryDirectory(prefix='history-', dir=_scratch(data)) as temporary:
        # One row at a time, file-backed metadata only. The primary-key order
        # serves pagination without an unbounded Python list or SQL temp sort.
        with closing(sqlite3.connect(str(no_links(Path(temporary)/'catalog.db')))) as conn:
            conn.execute('PRAGMA cache_size=-2048')
            conn.execute('CREATE TABLE catalog (missing INTEGER, stamp TEXT, scan_id TEXT, project TEXT, profile TEXT, core TEXT, git TEXT, scan_mode TEXT, state TEXT, day TEXT, payload TEXT, PRIMARY KEY(missing,stamp DESC,scan_id)) WITHOUT ROWID')
            with conn:
                for item in _rows(data):
                    ident = item['identity']; pin = ident.get('diff') or {}
                    # BLOB literal search preserves escaped legacy surrogates
                    # without forcing them through SQLite's strict UTF8 text.
                    joined = lambda values: '\n'.join(v for v in values if isinstance(v, str)).encode('utf-8', errors='surrogatepass')
                    stamp = item['recorded_at_utc'] or ''
                    conn.execute('INSERT INTO catalog VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (int(not stamp), stamp, item['scan_id'],
                         joined([item.get('project_id'), ident.get('project_name')]),
                         joined([item.get('profile_id'), ident.get('configured_target'), ident.get('build_variant')]),
                         joined([ident.get('project_core')]),
                         joined([ident.get('recorded_git_commit'), *[pin.get(key) for key in ['base_ref', 'current_ref', 'base_sha', 'head_sha']]]),
                         item['scan_mode'], item['state'], stamp[:10] if stamp else None,
                         json.dumps(item, ensure_ascii=True)))
            terms, args = [], []
            for key in ['project', 'profile', 'core', 'git']:
                if filters[key]:
                    terms.append('instr('+key+',?)>0'); args.append(filters[key].encode('utf-8', errors='surrogatepass'))
            for key in ['scan_mode', 'state']:
                if filters[key]:
                    terms.append(key+'=?'); args.append(filters[key])
            if start:
                terms.append('day>=?'); args.append(start.isoformat())
            if end:
                terms.append('day<=?'); args.append(end.isoformat())
            where = ' WHERE '+' AND '.join(terms) if terms else ''
            total = conn.execute('SELECT count(*) FROM catalog'+where, args).fetchone()[0]
            # A removed/imported record can make a saved page invalid.
            actual = min(offset, ((total-1)//limit)*limit) if total else 0
            rows = [json.loads(row[0]) for row in conn.execute('SELECT payload FROM catalog'+where+
                    ' ORDER BY missing,stamp DESC,scan_id LIMIT ? OFFSET ?', [*args, limit, actual])]
            return dict(items=rows, total=total, offset=actual, limit=limit,
                        next_offset=actual+len(rows) if actual+len(rows)<total else None,
                        date_basis='UTC；未记录时区或日期的归档不匹配日期筛选，不使用文件修改时间。',
                        note='归档身份用于检索；发布状态与静态覆盖分别显示，不表示当前源码有效或全工程安全。')


def _scratch(data):
    folder = no_links(data/'work/history')
    folder.mkdir(parents=True, exist_ok=True)
    return folder
