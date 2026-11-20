"""Evidence-backed object and static-risk changes between two fixed builds.

This layer does not classify variables or decide impact propagation. It binds
the classifier's proofs to both versions and keeps missing observations apart
from proven absence. Audit references always refer to the owning side's facts.
"""
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path

from .common import digest
from .evidence import READS, WRITES, SAFE_REASONS, SHARED_REASONS


COMPARISON_SCHEMA = 1
SHARED_PROOF_HAZARDS = frozenset({'MULTI_WRITER', 'STALE_SNAPSHOT', 'CHECK_THEN_ACT', 'DMA',
    'BITFIELD', 'UNION_OR_OVERLAP', 'WHOLE_OBJECT_MEMBER_CONFLICT', 'ADDRESS_ESCAPE',
    'MULTI_FIELD_COHERENCE', 'UNKNOWN_WRITER'})
MATRIX = {
    ('SAFE_PROVEN', 'SAFE_PROVEN'): ('R01', 'SAFETY_RETAINED', '安全结论保持'),
    ('SAFE_PROVEN', 'SUSPECT'): ('R02', 'NEW_SUSPECT', '新增疑似风险'),
    ('SAFE_PROVEN', 'UNKNOWN'): ('R03', 'SAFETY_PROOF_LOST', '原安全结论不再有充分依据'),
    ('SUSPECT', 'SAFE_PROVEN'): ('R04', 'RISK_POSSIBLY_RESOLVED', '风险可能已消除'),
    ('SUSPECT', 'SUSPECT'): ('R05', 'SUSPECT_PERSISTS', '疑似风险持续'),
    ('SUSPECT', 'UNKNOWN'): ('R06', 'PRIOR_RISK_UNCLOSED', '原风险尚不能关闭，当前证据不足'),
    ('UNKNOWN', 'SAFE_PROVEN'): ('R07', 'SAFETY_PROOF_GAINED', '当前已取得安全证明'),
    ('UNKNOWN', 'SUSPECT'): ('R08', 'SUSPECT_DISCOVERED', '当前发现疑似风险，不能证明本次新引入'),
    ('UNKNOWN', 'UNKNOWN'): ('R09', 'STILL_UNKNOWN', '仍待核实'),
}


def _relocate(value, cid):
    # Unlike semantic normalization, proof references retain access IDs and
    # source coordinates. They are for audit, never positional change signals.
    if isinstance(value, Mapping):
        return {key: _relocate(item, cid) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_relocate(item, cid) for item in value]
    return cid(value)


def scope_evidence(facts, report, cid):
    coverage = report.get('coverage', {})
    root = coverage.get('project_root')
    def path(value):
        if root and value and Path(value).is_absolute():
            actual = Path(value).resolve()
            if actual.is_relative_to(Path(root).resolve()):
                value = actual.relative_to(Path(root).resolve()).as_posix()
        return cid(value)
    units = [dict(source_file=path(u.get('source_file')), tu_id=u.get('tu_id'),
                  parse_status=u.get('parse_status'), includes=sorted(path(p) for p in u.get('includes', [])),
                  **({'extraction_digest': u['extraction_digest']} if u.get('extraction_digest') else {}))
             for u in facts.get('translation_units', [])]
    closure = coverage.get('build_closure', {})
    clock_regions = [dict(file=path(u['file']), line=u['line'], macro=u['macro'],
                          translation_unit=path(u['translation_unit']), reason=u['reason'])
                     for u in facts.get('unknowns', ()) if u['kind'] == 'DYNAMIC_PREDEFINED_INPUT'
                     and u['scope'] == 'BUILD']
    return dict(schema=COMPARISON_SCHEMA, units=units,
        **({'clock_regions': clock_regions} if clock_regions else {}),
        inventory_known=bool(units) and all(u['source_file'] and u['parse_status'] for u in units),
        build_complete=closure.get('complete'), missing_objects=closure.get('missing_objects', []),
        excluded_from_build=sorted(path(p) for p in coverage.get('excluded_from_build', [])),
        excluded_sources=sorted(path(p) for p in coverage.get('excluded_sources', [])),
        failed_preprocessing=_relocate(list(facts.get('failed_tu_preprocessing', [])), cid))


def object_evidence(variable, cid):
    return _relocate({key: variable.get(key) for key in (
        'symbol_id', 'name', 'kind', 'linkage', 'owner_function_id', 'root_symbol_id',
        'array_root_symbol_id', 'field_path', 'array_index', 'definition_file',
        'definitions', 'declarations', 'translation_units', 'resource_kind', 'coverage_source')}, cid)


def risk_evidence(variable, contexts, cid):
    """Keep proof data and bounded selectors, without expanding conflict products."""
    accesses = []
    for index, row in enumerate(variable.get('accesses', [])):
        item = {key: row.get(key) for key in ('access_id', 'function_id', 'file', 'line',
                'access_kind', 'contexts', 'reachability', 'canonical_path')}
        item.update(index=index, physical_contexts=sorted({contexts.get(c, {}).get('physical_id')
            for c in row.get('contexts', [])} - {None}))
        accesses.append(item)
    conflicts = []
    for index, row in enumerate(variable.get('conflict_pairs', [])):
        participants = [row.get('participant_a', {}), row.get('participant_b', {})]
        if (row.get('may_concurrent') and row.get('has_write_conflict')
                and row.get('protection_status') != 'EFFECTIVE'
                and all(contexts.get(p.get('context_id'), {}).get('physical_kind')
                        not in (None, 'UNKNOWN_CONTEXT') for p in participants)):
            conflicts.append(dict(index=index, conflict_id=row.get('conflict_id'),
                representation=row.get('representation', 'ACCESS_PAIR'), sha256=digest(row),
                participants=[{key: p.get(key) for key in
                    ('context_id', 'access_id', 'function_id', 'access_kind', 'file', 'line')} for p in participants],
                evidence_field='conflict_pairs'))
    gaps = [{key: gap.get(key) for key in ('blocker_id', 'reason_code', 'kind', 'relevance', 'file', 'line')}
            | dict(index=index, sha256=digest(gap), evidence_field='blocking_evidence')
            for index, gap in enumerate(variable.get('blocking_evidence', []))]
    evidence = dict(schema=COMPARISON_SCHEMA, symbol_id=variable['symbol_id'],
        classification=variable.get('static_classification'),
        safe_reason_code=variable.get('safe_reason_code'), safe_proof=variable.get('safe_evidence'),
        shared_reason_code=variable.get('shared_reason_code'), shared_proof=variable.get('shared_evidence'),
        accesses=accesses, known_conflicts=conflicts, known_conflict_count=len(conflicts), related_gaps=gaps,
        coverage=variable.get('analysis_coverage'), coverage_reasons=variable.get('coverage_reasons', []),
        protection_status=variable.get('protection_status'),
        protection_details_count=len(variable.get('protection_details', [])),
        physical_contexts=variable.get('variable_evidence_slice', {}).get('physical_contexts', []),
        address_escapes=bool(variable.get('variable_evidence_slice', {}).get('address_escapes')),
        initialization=variable.get('initialization_proof'), linkage=variable.get('linkage'),
        size_bytes=variable.get('size_bytes'), alignment_bytes=variable.get('alignment_bytes'),
        is_volatile=variable.get('is_volatile'), is_atomic=variable.get('is_atomic'))
    return _relocate(evidence, cid)


def coverage_assessment(variable, scope):
    evidence = (variable or {}).get('risk_evidence', {})
    identity = (variable or {}).get('object_evidence', {})
    related = list(evidence.get('related_gaps', []))
    excluded, unaccounted = [], []
    if not any(g.get('kind') == 'DYNAMIC_PREDEFINED_INPUT' for g in related):
        unaccounted.extend(scope.get('clock_regions', ()))
    definition_units = set(identity.get('translation_units') or []) | {identity.get('definition_file')}
    failed = defaultdict(list)
    for unit in scope.get('units', []):
        if unit['parse_status'] != 'PARSED':
            failed[unit['source_file']].append(unit)
    for source, units in sorted(failed.items()):
        if any(gap.get('file') == source and gap.get('kind') in {'PARSE_FAILED', 'PARTIAL_PARSE_REGION'}
               for gap in related):
            continue
        if (identity.get('linkage') == 'INTERNAL' and source not in definition_units
                and not evidence.get('address_escapes')):
            excluded.append(dict(file=source, proof='INTERNAL_LINKAGE_SEPARATE_TU',
                reason='内部链接对象不在该编译单元中，且对象证据未发现地址逃逸。'))
            continue
        preprocessing = [row for row in scope.get('failed_preprocessing', []) if row.get('source_file') == source]
        variants = {unit.get('tu_id') for unit in units}
        if (source not in definition_units and identity.get('name')
                and len(preprocessing) == len(units)
                and {row.get('tu_id') for row in preprocessing} == variants
                and all(row.get('status') == 'COMPLETE' and identity['name'] not in row.get('identifiers', [])
                        for row in preprocessing)):
            excluded.append(dict(file=source, proof='ALL_FAILED_VARIANTS_EXCLUDE_IDENTIFIER',
                preprocessing=[{key: row.get(key) for key in ('tu_id', 'output_sha256', 'command_sha256')}
                               for row in preprocessing], reason='失败单元所有构建变体的完整预处理结果均排除此对象名称。'))
            continue
        unaccounted.append(dict(file=source, reason='缺少此解析缺口与目标对象隔离的证明。'))
    if scope.get('missing_objects') and identity.get('linkage') != 'INTERNAL':
        if not any(gap.get('kind') == 'MISSING_LINKED_OBJECT' for gap in related):
            unaccounted.append(dict(missing_objects=scope['missing_objects'], reason='缺失链接对象尚未排除对目标存储的访问。'))
    return dict(status=evidence.get('coverage', 'UNKNOWN'), related_gaps=related,
                excluded_gaps=excluded, unaccounted_gaps=unaccounted)


def validate_proof(variable, scope, shared=False):
    evidence = variable.get('risk_evidence', {})
    proof = evidence.get('shared_proof' if shared else 'safe_proof')
    code = evidence.get('shared_reason_code' if shared else 'safe_reason_code')
    assessment = coverage_assessment(variable, scope)
    issues = []
    if (evidence.get('schema') != COMPARISON_SCHEMA or not isinstance(proof, dict)
            or code not in (SHARED_REASONS if shared else SAFE_REASONS) or proof.get('proof') != code):
        issues.append('MISSING_VALID_PROOF')
        proof = proof if isinstance(proof, dict) else {}
    accesses = evidence.get('accesses', [])
    ids = {row.get('access_id') for row in accesses}
    runtime = [row for row in accesses if row.get('access_kind') in READS | WRITES
               and row.get('reachability') != 'PROVEN_UNREACHABLE']
    covered = (set(proof.get('writer_access_ids', [])) | set(proof.get('reader_access_ids', []))
               if shared else set(proof.get('access_ids', [])))
    required = {row.get('access_id') for row in runtime} if shared else ids
    if None in required or covered != required:
        issues.append('ACCESS_COVERAGE_MISMATCH')
    if not shared and proof.get('evidence_slice_symbol_id') != evidence.get('symbol_id'):
        issues.append('PROOF_OBJECT_MISMATCH')
    if not shared and (proof.get('coverage') != evidence.get('coverage') or
            set(proof.get('physical_contexts', [])) != set(evidence.get('physical_contexts', []))):
        issues.append('PROOF_SCOPE_MISMATCH')
    if assessment['related_gaps'] or assessment['unaccounted_gaps']:
        issues.append('RELEVANT_COVERAGE_GAP')
    # A protection diagnostic can be irrelevant to an independent proof, but
    # an unexplained PARTIAL flag is not permission to close the old risk.
    reasons = set(evidence.get('coverage_reasons', []))
    independent = code in {'SAFE_NO_RUNTIME_ACCESS', 'SAFE_READ_ONLY', 'SAFE_MULTI_CONTEXT_READ_ONLY',
                          'SAFE_SINGLE_FOREGROUND', 'SAFE_SINGLE_IRQ', 'SAFE_NON_INTERLEAVING', 'SAFE_UNOBSERVED_WRITES'}
    if reasons == {'PROTECTION_UNRESOLVED'} and independent:
        assessment['excluded_gaps'].append(dict(kind='PROTECTION_UNRESOLVED', proof=code,
            reason='此安全证明不依赖未解析的保护操作。'))
    elif reasons or evidence.get('coverage') != 'COMPLETE':
        issues.append('UNEXPLAINED_COVERAGE_LIMIT')
    physical = {p for row in runtime for p in row['physical_contexts']}
    if shared:
        writer = proof.get('writer_physical_context')
        writers = {p for row in runtime if row['access_kind'] in WRITES for p in row['physical_contexts']}
        readers = {p for row in runtime if row['access_kind'] in READS for p in row['physical_contexts']} - writers
        if (not writer or writers != {writer} or not readers
                or set(proof.get('reader_physical_contexts', [])) != readers
                or any(not row['physical_contexts'] for row in runtime)):
            issues.append('EXEMPTION_CONTEXTS_INCOMPLETE')
        writer_ids = {row['access_id'] for row in runtime if writer in row['physical_contexts']}
        reader_ids = {row['access_id'] for row in runtime if set(row['physical_contexts']) - {writer}}
        if (set(proof.get('writer_access_ids', [])) != writer_ids
                or set(proof.get('reader_access_ids', [])) != reader_ids
                or set(proof.get('writer_rmw_access_ids', [])) !=
                    {row['access_id'] for row in runtime if row['access_kind'] == 'RMW'}):
            issues.append('EXEMPTION_ACCESS_ROLES_MISMATCH')
        width, alignment = proof.get('atomic_width_bytes'), proof.get('alignment_bytes')
        if (type(width) is not int or type(alignment) is not int or width <= 0 or alignment < width
                or width != evidence.get('size_bytes') or alignment != evidence.get('alignment_bytes')):
            issues.append('EXEMPTION_ATOMIC_ACCESS_UNPROVEN')
        visibility = 'ATOMIC' if evidence.get('is_atomic') else 'VOLATILE' if evidence.get('is_volatile') else None
        if not visibility or proof.get('compiler_visibility') != visibility:
            issues.append('EXEMPTION_VISIBILITY_UNPROVEN')
        if (not SHARED_PROOF_HAZARDS <= set(proof.get('excluded_hazards', []))
                or evidence.get('address_escapes') or not evidence.get('known_conflicts')
                or len(evidence['known_conflicts']) != evidence.get('known_conflict_count')):
            issues.append('EXEMPTION_HAZARDS_UNPROVEN')
    else:
        if code == 'SAFE_EFFECTIVE_PROTECTION' and (evidence.get('protection_status') != 'EFFECTIVE'
                or not evidence.get('protection_details_count')):
            issues.append('PROTECTION_NOT_PROVEN')
        if code == 'SAFE_NO_RUNTIME_ACCESS' and runtime:
            issues.append('RUNTIME_ACCESS_REMAINS')
        if code in {'SAFE_READ_ONLY', 'SAFE_MULTI_CONTEXT_READ_ONLY'} and (not runtime
                or any(row['access_kind'] not in READS for row in runtime)):
            issues.append('WRITER_REMAINS')
        if code == 'SAFE_SINGLE_FOREGROUND' and physical != {'FOREGROUND'}:
            issues.append('EXECUTION_CONTEXT_MISMATCH')
        if code == 'SAFE_SINGLE_IRQ' and (len(physical) != 1 or not next(iter(physical), '').startswith('IRQ:')):
            issues.append('EXECUTION_CONTEXT_MISMATCH')
        if code == 'SAFE_INIT_ONLY_WRITE' and not evidence.get('initialization'):
            issues.append('INITIALIZATION_NOT_PROVEN')
        if evidence.get('known_conflicts') and code != 'SAFE_UNOBSERVED_WRITES':
            issues.append('UNEXCLUDED_CURRENT_CONFLICT')
        if code == 'SAFE_UNOBSERVED_WRITES' and (evidence.get('linkage') != 'INTERNAL'
                or evidence.get('is_volatile') or evidence.get('is_atomic') or not runtime
                or any(row['access_kind'] not in {'WRITE', 'WHOLE_OBJECT_WRITE'} for row in runtime)):
            issues.append('OBSERVABLE_ACCESS_REMAINS')
    return dict(valid=not issues, issues=sorted(set(issues)), proof=proof, coverage=assessment,
                covered_access_ids=sorted(covered), proof_code=code)


class ObjectComparison:
    def __init__(self, base, head, pinned):
        self.base, self.head, self.pin = base, head, pinned
        self.unmatched = []
        for side, other in ((base, head), (head, base)):
            groups = defaultdict(list)
            for sid in sorted(side['variables'].keys() - other['variables'].keys()):
                row = side['variables'][sid]
                identity = row.get('object_evidence', {})
                groups[(row.get('file'), identity.get('owner_function_id'))].append(row['symbol_id'])
            self.unmatched.append(groups)

    def absence(self, present, missing, missing_side):
        scope = missing.get('comparison_scope', {})
        identity = present.get('object_evidence', {})
        result = dict(state='NOT_OBSERVED', reason='缺少完整构建清单或对象存在性证据，不能从缺记录推断删除或新增。')
        root = identity.get('root_symbol_id') or identity.get('array_root_symbol_id')
        other_root = missing['variables'].get(root) if root else None
        if other_root and not other_root.get('container'):
            return dict(result, kind='STORAGE_SHAPE_CHANGED', root_symbol_id=root,
                reason='另一版本只有对应根存储，成员与标量或不同存储形态之间不能直接匹配。')
        candidates = self.unmatched[missing_side].get((present.get('file'), identity.get('owner_function_id')), [])
        if candidates and identity:
            return dict(result, candidates=candidates, reason='同一声明作用域存在未匹配对象，可能改名或改变存储形态。')
        if (scope.get('schema') != COMPARISON_SCHEMA or not scope.get('inventory_known')
                or scope.get('build_complete') is not True or not identity):
            return result
        # Only missing-side regional gaps apply here; the other version's
        # blocker rows cannot serve as evidence about this version.
        probe = dict(present, risk_evidence=dict(present.get('risk_evidence', {}), related_gaps=[]))
        coverage = coverage_assessment(probe, scope)
        if coverage['unaccounted_gaps'] or scope.get('missing_objects') or scope.get('build_complete') is False:
            return dict(result, coverage=coverage, reason='构建或解析缺口尚不能排除隐藏目标对象。')
        # The present side's old blockers cannot establish a missing-side gap;
        # inspect its definition units against the missing side directly.
        files = {identity.get('definition_file')} | set(identity.get('translation_units') or [])
        units = scope.get('units', [])
        if any(unit['parse_status'] != 'PARSED' and unit['source_file'] in files for unit in units):
            return dict(result, coverage=coverage, reason='目标相关单元未完整提取，存在性待核实。')
        excluded = set(scope.get('excluded_from_build', [])) | set(scope.get('excluded_sources', []))
        source = identity.get('definition_file')
        if source in excluded:
            return dict(state='CONFIRMED_ABSENT', kind='OUT_OF_BUILD', file=source,
                reason='定义所在文件被本次真实构建或配置排除；不表示源码删除。')
        deleted = set()
        for change in self.pin.get('files', []):
            status = change.get('status', '')
            path = change.get('old_path') if missing_side == 1 else change.get('new_path')
            if path and status.startswith('D' if missing_side == 1 else 'A'):
                prefix = self.pin.get('project_subdir', '.')
                deleted.add(Path(path).relative_to(prefix).as_posix() if prefix != '.' and Path(path).is_relative_to(prefix)
                            else Path(path).as_posix())
        if source in deleted:
            return dict(state='CONFIRMED_ABSENT', kind='DELETED', file=source,
                reason='固定 Git 差异确认定义文件不存在，完整构建清单未观察到同一对象。')
        if source and any(unit['parse_status'] == 'PARSED' and
                (unit['source_file'] == source or source in unit['includes']) for unit in units):
            return dict(state='CONFIRMED_ABSENT', kind='ABSENT_IN_BUILD', file=source,
                reason='定义文件已完整解析，该对象不在此构建的活动声明中；源码删除与条件编译变化不作无依据区分。')
        return dict(result, reason='原定义不在已解析或明确排除的文件清单中，不能证明其去向。')

    def describe(self, old, new):
        def observed(row):
            identity = row.get('object_evidence', {})
            if (identity.get('coverage_source') in {'supplemental', 'inactive_branch'}
                    or row['dimensions']['classification'] == 'OUT_OF_BUILD'):
                return dict(state='CONFIRMED_ABSENT', kind='OUT_OF_BUILD', symbol_id=row['symbol_id'],
                    definition_file=identity.get('definition_file'), reason='清单有声明记录，但该对象未进入本次活动构建。')
            return dict(state='OBSERVED' if identity.get('definition_file') else 'NOT_OBSERVED',
                symbol_id=row['symbol_id'], definition_file=identity.get('definition_file'),
                reason='已提取对象定义。' if identity.get('definition_file') else '仅有记录，缺少实际存储定义证据。')
        before = observed(old) if old else self.absence(new, self.base, 0)
        after = observed(new) if new else self.absence(old, self.head, 1)
        if old and new:
            shape = bool(old.get('container')) != bool(new.get('container'))
            event = 'STORAGE_SHAPE_CHANGED' if shape else 'MATCHED'
            if before['state'] == 'CONFIRMED_ABSENT' and after['state'] == 'OBSERVED':
                event = 'ENTERED_BUILD'
            elif after['state'] == 'CONFIRMED_ABSENT':
                event = 'OUT_OF_BUILD'
            elif before['state'] != 'OBSERVED' or after['state'] != 'OBSERVED':
                event = 'EXISTENCE_UNCERTAIN'
        elif (before if old is None else after)['state'] != 'CONFIRMED_ABSENT':
            absent = before if old is None else after
            event = ('STORAGE_SHAPE_CHANGED' if absent.get('kind') == 'STORAGE_SHAPE_CHANGED' else
                     'MATCH_UNCERTAIN' if absent.get('candidates') else 'EXISTENCE_UNCERTAIN')
        elif new is None:
            event = after['kind']
        else:
            event = 'ADDED' if before['kind'] in {'DELETED', 'ABSENT_IN_BUILD'} else 'ENTERED_BUILD'
        return dict(event=event, base=before, head=after)


def risk_transition(old, new, object_change, base_scope=None, head_scope=None):
    before = old['dimensions']['classification'] if old else None
    after = new['dimensions']['classification'] if new else None
    result = dict(code='NOT_COMPARABLE', label='无法判断变化结果', matrix_case=None,
        comparison_status='UNMATCHED', note=None, base_classification=before, head_classification=after,
        counts_as_new_risk=False, counts_as_risk_resolution=False,
        current_suspect=after == 'SUSPECT', prior_risk_unclosed=before == 'SUSPECT', closure=None,
        coverage=dict(base=coverage_assessment(old, base_scope or {}), head=coverage_assessment(new, head_scope or {})))
    if old is None or new is None:
        result['note'] = '缺少同一存储对象的双版本证据；对象新增、消失或移出构建不等于风险新增或修复。'
        if after == 'SUSPECT':
            result.update(code='CURRENT_SUSPECT_UNMATCHED', label='当前存在疑似风险，对象变化单独核对')
        elif before == 'SUSPECT':
            result.update(code='PRIOR_RISK_UNCLOSED', label='原风险尚不能关闭，对象存在性或去向需核对')
        return result
    if bool(old.get('container', before == 'CONTAINER')) != bool(new.get('container', after == 'CONTAINER')):
        result.update(comparison_status='STORAGE_SHAPE_CHANGED',
            note='存储对象在标量与容器间转换，根对象与成员的风险需要分别核对，不能据容器分类判断风险新增或消除。')
        return result
    if before not in {'SAFE_PROVEN', 'SUSPECT', 'UNKNOWN', 'SHARED_NO_REVIEW'} or after not in {'SAFE_PROVEN', 'SUSPECT', 'UNKNOWN', 'SHARED_NO_REVIEW'}:
        result.update(comparison_status='AGGREGATE_OR_UNASSESSED',
            note='容器、非存储对象或尚未分析的记录不是可直接比较的变量风险结论，需核对实际存储对象及其成员。')
        return result
    if any(v.get('risk_evidence', {}).get('schema') != COMPARISON_SCHEMA for v in (old, new)):
        result.update(comparison_status='LEGACY_EVIDENCE', note='旧摘要缺少对象存在性或风险证明字段，变化不可比；请重新扫描。')
        return result
    if object_change['event'] != 'MATCHED':
        result.update(comparison_status='EXISTENCE_UNCERTAIN', note='同一存储对象的双侧实际定义尚未确认。')
        return result
    checks = {}
    for side, variable, scope in (('base', old, base_scope or {}), ('head', new, head_scope or {})):
        state = variable['dimensions']['classification']
        if state != variable['risk_evidence'].get('classification'):
            result.update(comparison_status='PROOF_INCOMPLETE', note='静态分类与归档证明身份不一致。')
            return result
        if state == 'SUSPECT':
            witnesses = variable['risk_evidence'].get('known_conflicts', [])
            if (not witnesses or len(witnesses) != variable['risk_evidence'].get('known_conflict_count')
                    or len({row['index'] for row in witnesses}) != len(witnesses)):
                result.update(comparison_status='PROOF_INCOMPLETE', label='疑似风险证据不完整，变化待核实',
                              note='缺少完整且可定位的疑似冲突引用：' + side)
                return result
        if state in {'SAFE_PROVEN', 'SHARED_NO_REVIEW'}:
            checks[side] = validate_proof(variable, scope, state == 'SHARED_NO_REVIEW')
            result['coverage'][side] = checks[side]['coverage']
            if not checks[side]['valid']:
                result.update(code='EXEMPTION_UNVERIFIED' if state == 'SHARED_NO_REVIEW' else 'PROOF_INCOMPLETE',
                    comparison_status='PROOF_INCOMPLETE', note='该侧安全或免复核证明不完整，不能沿用：' + side,
                    proof_issues={side: checks[side]['issues']})
                if before == 'SUSPECT':
                    result['label'] = '原风险尚不能关闭，当前安全或免复核依据不完整'
                return result
    if 'SHARED_NO_REVIEW' in (before, after):
        if before == after:
            result.update(code='EXEMPTION_RETAINED', label='共享无需复核，免复核依据保持')
        elif after == 'SHARED_NO_REVIEW':
            result.update(code='EXEMPTION_GAINED', label='当前满足免复核规则')
        elif after == 'SUSPECT':
            result.update(code='EXEMPTION_LOST_SUSPECT', label='免复核条件失效，当前存在疑似风险')
        elif after == 'UNKNOWN':
            result.update(code='EXEMPTION_LOST_UNKNOWN', label='免复核依据不再充分，当前待核实')
        else:
            result.update(code='EXEMPTION_TO_SAFETY', label='当前取得独立安全证明')
        result.update(comparison_status='COMPARABLE', exemption={side: item['proof'] for side, item in checks.items()
            if (old if side == 'base' else new)['dimensions']['classification'] == 'SHARED_NO_REVIEW'})
        return result
    case, code, label = MATRIX[(before, after)]
    if case == 'R04':
        conflicts = old['risk_evidence'].get('known_conflicts', [])
        proof = checks['head']
        if not conflicts:
            result.update(comparison_status='PROOF_INCOMPLETE', label='旧风险关闭证据不足',
                          note='缺少可定位的基准冲突，不能仅凭分类变化关闭旧风险。')
            return result
        result['closure'] = dict(status='PROVEN', current_proof=proof['proof'], proof_code=proof['proof_code'],
            current_access_ids=proof['covered_access_ids'], related_gaps=[], excluded_gaps=proof['coverage']['excluded_gaps'],
            correspondences=[dict(base_conflict=conflict, head_proof_code=proof['proof_code'],
                head_symbol_id=new['symbol_id'], head_evidence_field='safe_evidence',
                explanation=SAFE_REASONS[proof['proof_code']] + '；该证明覆盖当前对象全部访问，排除原冲突在当前版本中的成立条件。')
                for conflict in conflicts])
    result.update(code=code, label=label, matrix_case=case, comparison_status='COMPARABLE',
        counts_as_new_risk=case == 'R02', counts_as_risk_resolution=case == 'R04',
        prior_risk_unclosed=before == 'SUSPECT' and case != 'R04')
    return result


def change_counts(impacts):
    rows = list(impacts)
    return dict(basis='SELECTED_DIFF_OBJECTS',
        transitions=dict(sorted(Counter(row['risk_transition']['code'] for row in rows).items())),
        objects=dict(sorted(Counter(row['object_change']['event'] for row in rows).items())),
        **{key: sum(bool(row['risk_transition'][key]) for row in rows) for key in
           ('counts_as_new_risk', 'counts_as_risk_resolution', 'current_suspect', 'prior_risk_unclosed')})
