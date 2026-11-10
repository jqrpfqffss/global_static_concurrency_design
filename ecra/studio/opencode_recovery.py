"""Preserve legacy OpenCode startup files outside an owned Git snapshot."""
import os
from pathlib import Path
import re
import tempfile

from ..common import read_json
from ..workspace import canonical, no_links


_STARTUP_IGNORE = b'node_modules\npackage.json\npackage-lock.json\nbun.lock\n.gitignore'


def recover_review_tree(workspace, pinned, progress=print):
    """Move recognizable startup artifacts only. Normal Git checks still run."""
    if not isinstance(pinned, dict):
        return
    sha = pinned.get('head_sha')
    if (not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', sha)
            or pinned.get('include_uncommitted')):
        return
    work = no_links(workspace.project_workspace)
    tree = no_links(Path(workspace.worktree_root)/('current-' + sha[:16]))
    project = Path(workspace.project_root)
    repo = Path(workspace.repository_root)
    source = tree/project.relative_to(repo)
    if pinned.get('current_source_root') and Path(pinned['current_source_root']) != source:
        return
    config = source/'.opencode'
    # An ordinary worktree, an old snapshot without an ownership record, or an
    # unrecognized file is left to the existing strict validation.
    if not (config/'.gitignore').exists():
        return
    # Keep the marker and then the manifest until last so a partial move can
    # resume even if stopping OpenCode interrupted dependency installation.
    try:
        candidates = [no_links(config/name) for name in
                      ('node_modules', 'package-lock.json', 'bun.lock', 'package.json', '.gitignore')]
    except ValueError:
        return  # Leave linked paths to the normal Git boundary check.
    paths = [path for path in candidates if path.exists()]
    ignore = candidates[-1]
    if not ignore.is_file() or ignore.stat().st_size != len(_STARTUP_IGNORE) or ignore.read_bytes() != _STARTUP_IGNORE:
        return
    home = no_links(work/'git-snapshots'/tree.name)
    marker = no_links(home/'state.json')
    if not marker.is_file() or marker.with_name('state.json.pending').exists():
        return
    private = no_links(home/'repository.git')
    identity = dict(version=1, project_id=workspace.project_id, source=canonical(repo),
                    tree=canonical(tree), sha=sha, repository=canonical(private), status='READY')
    state = read_json(marker)
    if not isinstance(state, dict) or any(state.get(key) != value for key, value in identity.items()):
        return

    from ..git_diff import _content_changes, git
    from ..independent_git import _owned
    _owned(private, tree, sha)
    literal = ':(literal,icase)' if os.name == 'nt' else ':(literal)'
    if (git(tree, 'ls-files', '--cached', '-z', '--', *(literal+p.relative_to(tree).as_posix() for p in paths))
            or _content_changes(tree, 'HEAD')):
        return
    manifest = candidates[-2]
    if len(paths) > 1:
        if not manifest.is_file() or manifest.stat().st_size > 4096:
            return
        try:
            metadata = read_json(manifest)
        except (ValueError, OSError):
            return
        if not isinstance(metadata, dict) or set(metadata) != {'dependencies'}:
            return
        dependencies = metadata['dependencies']
        if (not isinstance(dependencies, dict) or set(dependencies) != {'@opencode-ai/plugin'}
                or not isinstance(dependencies['@opencode-ai/plugin'], str)):
            return
    if any(not (p.is_dir() if p.name == 'node_modules' else p.is_file()) for p in paths):
        return
    recovery = no_links(work/'opencode-recovery'/tree.name)
    recovery.mkdir(parents=True, exist_ok=True)
    saved = Path(tempfile.mkdtemp(prefix='startup-', dir=recovery))
    progress(f'将旧版 OpenCode 启动文件移出隔离源码，保留于：{saved}')
    for path in paths:
        path.rename(saved/path.name)
