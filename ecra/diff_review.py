"""Resolve deleted-variable evidence and reviews within their owning diff archive."""
from contextlib import closing
from functools import lru_cache
from pathlib import Path
import re

from .scan_store import EvidenceProvider, connect_readonly, schema_for_version
from .workspace import no_links


DELETED_REVIEW_PREFIX = '@deleted:'
DELETED_IDS = """SELECT CAST(n.value AS TEXT) AS symbol_id FROM main.edges d
 JOIN main.edges f ON f.parent=d.child AND f.key='symbol_id'
 JOIN main.nodes n ON n.id=f.child AND n.kind='str' WHERE d.parent=?"""

def _stamp(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino


@lru_cache(maxsize=24)
def _verified(path, expected, stamp, progress=None):
    from .report_package import sha256, validate_schema
    if sha256(path, progress=progress) != expected:
        raise ValueError('Git 基准证据的内容校验失败')
    with closing(connect_readonly(path)) as conn:
        version = conn.execute('PRAGMA user_version').fetchone()[0]
    validate_schema(path, schema_for_version(version), version, check_integrity=False)
    binding = EvidenceProvider(path).validate(deep=True, progress=progress)
    if _stamp(path) != stamp:
        raise ValueError('Git 基准证据在校验期间发生变化')
    return binding


class DiffReviewEvidence:
    def __init__(self, directory, current=None, *, progress=None):
        self.directory = Path(directory)
        self.current = current or EvidenceProvider(self.directory/'scan.db')
        self.progress = progress

    def deleted_node(self):
        return self.current.resolve('report', ['git_diff', 'deleted_variables'])

    def baseline(self):
        try:
            deleted = self.current.node(self.deleted_node(), limit=1)
            if deleted['kind'] != 'list' or not deleted['total']:
                return None
            pin = ['git_diff', 'pin']
            expected = self.current.node(self.current.resolve('report', [*pin, 'base_facts_sha256'])).get('value')
            base_sha = self.current.node(self.current.resolve('report', [*pin, 'base_sha'])).get('value')
        except KeyError:
            return None
        if expected is None or base_sha is None:
            return None
        if not isinstance(expected, str) or not re.fullmatch(r'[a-f0-9]{64}', expected):
            raise ValueError('Git 基准证据摘要无效')
        # Report paths refer to the machine that created the archive. Read only
        # the content-addressed object owned by this scan, also after import.
        for candidate in (self.directory/'evidence'/expected,
                          self.directory/'git_diff'/'evidence'/expected/'scan.db'):
            path = no_links(candidate)
            if not path.is_file():
                continue
            with path.open('rb') as stream:
                if stream.read(16) != b'SQLite format 3\0':
                    continue  # Legacy JSON-only baseline
            binding = _verified(path, expected, _stamp(path), self.progress)
            if binding['scan_id'] != 'base-'+str(base_sha) or binding['project_id'] != self.current.metadata()['project_id']:
                raise ValueError('Git 基准证据与此扫描的固定版本或工程不匹配')
            return EvidenceProvider(path)
        return None

    def require_baseline(self):
        provider = self.baseline()
        if provider is None:
            raise ValueError('此归档缺少可复核的基准数据库，请用当前版本重新运行差异扫描')
        return provider

    def require_deleted(self, symbol):
        with closing(connect_readonly(self.current.path)) as conn:
            row = conn.execute('SELECT 1 FROM ('+DELETED_IDS+') WHERE symbol_id=? LIMIT 1',
                               (self.deleted_node(), symbol)).fetchone()
        if not row:
            raise KeyError(symbol)

    def fingerprint(self, symbol):
        if not symbol.startswith(DELETED_REVIEW_PREFIX):
            return self.current.fingerprint(symbol)
        raw = symbol.removeprefix(DELETED_REVIEW_PREFIX)
        self.require_deleted(raw)
        return self.require_baseline().fingerprint(raw)
