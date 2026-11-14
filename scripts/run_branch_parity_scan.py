"""Record phase boundaries during a fresh A/B/C parity scan through the public CLI."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import runpy
import subprocess
import sys


VARIABLE_FIELDS = (
    'symbol_id', 'name', 'qualified_name', 'kind', 'type', 'linkage', 'coverage_source',
    'definition_file', 'definition_line', 'definition_column', 'definition_extent', 'resource_kind',
    'root_symbol_id', 'array_root_symbol_id', 'field_path', 'array_index', 'parent_symbol_id',
    'translation_units', 'parse_status', 'static_classification', 'screening_reason', 'safe_reason_code',
    'shared_reason_code', 'unknown_reason_codes', 'storage_class', 'is_const', 'is_volatile',
    'definition_missing', 'declarations', 'definitions', 'member_symbol_ids',
)


def inventory(variables):
    return [{key: row[key] for key in VARIABLE_FIELDS if key in row} for row in variables]


def observe(engine, config, evidence, legacy_cli):
    # Choose the target engine before importing any ECRA modules or Clang state.
    sys.path.insert(0, str(engine))
    from clang import cindex
    from ecra import cli, scope
    from ecra.common import digest
    from ecra.config import configured_project_root, load_config
    from ecra.workflow import analysis_config, engine_digest

    def save(filename, value):
        (evidence / (filename + '.json')).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    root = configured_project_root(config)
    cfg, _ = load_config(root, config)
    if not legacy_cli:
        cfg['analysis']['git_diff']['enabled'] = False
    before = engine_digest()
    save('engine', dict(engine=str(engine), engine_sha256=before, revision=subprocess.check_output(
        ['git', '--no-optional-locks', 'rev-parse', 'HEAD'], cwd=engine, text=True).strip(),
        python=sys.version, python_executable=sys.executable, libclang_package=importlib.metadata.version('libclang'),
        libclang_library=str(cindex.conf.get_filename()), config=str(config),
        config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
        analysis_config_digest=digest(analysis_config(cfg))))
    save('effective_config', cfg)
    save('effective_static_config', analysis_config(cfg))

    prepare_original, merge_original, select_original, analyze_original = cli.prepare, cli.merge, scope.select_facts, cli.analyze

    def prepare(*args, **kwargs):
        units, compilation = prepare_original(*args, **kwargs)
        save('L1-input', units)
        return units, compilation

    def merge(*args, **kwargs):
        facts = merge_original(*args, **kwargs)
        save('L3-linked', inventory(facts['variables']))
        return facts

    def select(facts, policy, coverage):
        save('L5-projection-before-scope', inventory(facts['variables']))
        result = select_original(facts, policy, coverage)
        save('L4-selected', inventory(facts['variables']))
        return result

    def analyze(facts, *args, **kwargs):
        save('L1-parsed', facts['translation_units'])
        report = analyze_original(facts, *args, **kwargs)
        save('L6-L7-analyzed', inventory(facts['variables']))
        save('L7-findings', [{key: row.get(key) for key in ('symbol_id', 'finding_id', 'static_classification',
                                                           'rules', 'readers', 'writers')}
                              for row in report['findings']])
        prefixes = ('translation_units', 'parse_', 'static_', 'audit_scope', 'struct_', 'variables_',
                    'build_closure', 'result_', 'array_', 'non_storage')
        save('L7-metrics', {key: val for key, val in report.get('coverage', {}).items() if key.startswith(prefixes)})
        return report

    cli.prepare, cli.merge, scope.select_facts, cli.analyze = prepare, merge, select, analyze
    script = engine / 'run_ecra.py'
    sys.argv = [str(script), 'run', '--config', str(config), '--no-review']
    if not legacy_cli:
        sys.argv += ['--scan-mode', 'full']
    try:
        runpy.run_path(str(script), run_name='__main__')
    finally:
        after = engine_digest()
        save('engine-finish', dict(engine_sha256=after, unchanged=after == before))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--legacy-cli', action='store_true', help='A has no --scan-mode argument')
    args = parser.parse_args()
    engine, config, evidence = args.engine.resolve(), args.config.resolve(), args.evidence.resolve()
    if not (engine/'run_ecra.py').is_file() or not config.is_file():
        parser.error('Provide an ECRA worktree and a real scan configuration')
    evidence.mkdir(parents=True, exist_ok=False)
    observe(engine, config, evidence, args.legacy_cli)


if __name__ == '__main__':
    main()
