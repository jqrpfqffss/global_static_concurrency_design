"""Independent verification and publication completeness, without weakening input gates."""
import hashlib

from .common import digest


def extraction_digest(path):
    """Stream one raw worker record at a time; exclude only input receipts/logs."""
    from .json_rows import rows
    result = hashlib.sha256()
    for key, value, array in rows(path):
        if key not in {'input_snapshot', 'preprocessor_signature', 'diagnostics'}:
            result.update(digest([key, array, value]).encode('ascii'))
    return result.hexdigest()


def completeness(scope):
    units = scope.get('units', [])
    if not scope.get('inventory_known') or not units:
        raise ValueError('缺少可信编译单元清单，不能发布有效局部比较')
    if any(u.get('parse_status') not in {'PARSED', 'PARTIAL', 'FAILED'} for u in units):
        raise ValueError('未知提取状态，不能作为可定位局部缺口')
    gaps = [dict(kind='EXTRACTION_GAP', **dict(u)) for u in units if u['parse_status'] != 'PARSED']
    if scope.get('missing_objects'):
        gaps.append(dict(kind='MISSING_LINKED_OBJECT', objects=scope['missing_objects']))
    if scope.get('build_complete') is not True:
        gaps.append(dict(kind='BUILD_COVERAGE_INCOMPLETE'))
    return dict(state='VALID_PARTIAL' if gaps else 'COMPLETE', complete_tus=all(
        u['parse_status'] == 'PARSED' for u in units), gaps=gaps,
        total_units=len(units), parsed_units=sum(u['parse_status'] == 'PARSED' for u in units))


def summary_cache_matches(manifest, coverage):
    """Check cheap cache metadata against the validated authority's coverage."""
    if not isinstance(manifest, dict) or not isinstance(manifest.get('completeness'), dict):
        return False
    total, parsed = coverage.get('translation_units_total'), coverage.get('translation_units_parsed')
    if type(total) is not int or type(parsed) is not int or not 0 <= parsed <= total or total == 0:
        return False
    complete_tus = parsed == total
    closure = coverage.get('build_closure', {})
    build_complete = coverage.get('build_complete', closure.get('complete'))
    missing = coverage.get('missing_object_count', len(closure.get('missing_objects', [])))
    expected = 'COMPLETE' if complete_tus and build_complete is True and missing == 0 else 'VALID_PARTIAL'
    recorded = manifest['completeness']
    return (manifest.get('complete_tus') is complete_tus and recorded.get('complete_tus') is complete_tus
            and type(recorded.get('total_units')) is int and type(recorded.get('parsed_units')) is int
            and recorded.get('state') == expected and recorded.get('total_units') == total
            and recorded.get('parsed_units') == parsed)


def verify_summaries(expected, actual, units):
    """Return INCOMPLETE only for explicit extraction/build-coverage gaps.

    Equal partial summaries still cannot certify a complete extraction. When
    extraction coverage differs, compare raw facts for every common parsed TU
    and derived objects whose gap isolation is proved on both runs. A missing
    digest, changed build, or any observed mismatch is a failure, not a gap.
    """
    scopes = [s.get('comparison_scope') for s in (expected, actual)]
    # Legacy verification fixtures retain their original exact equality gate.
    if any(scope is None for scope in scopes):
        if expected != actual:
            raise ValueError('增量与独立全量的语义事实不一致，已阻止发布')
        return dict(state='PASSED', variables=len(actual['variables']), reextracted_units=units,
                    classification_mismatches=0, semantic_mismatches=0)
    states = [completeness(scope) for scope in scopes]
    gaps = [dict(side=side, **gap) for side, state in zip(('current', 'reference'), states)
            for gap in state['gaps']]
    if expected != actual:
        def fail():
            raise ValueError('增量与独立全量的语义事实不一致或无法局部化，已阻止发布')
        if (not gaps or expected.keys() != actual.keys() or expected.get('schema') != actual.get('schema')
                or expected.get('build') != actual.get('build')):
            fail()
        inventories = [{(u['source_file'], u.get('tu_id')): u for u in scope['units']} for scope in scopes]
        if inventories[0].keys() != inventories[1].keys():
            fail()
        statuses = [[u['parse_status'] for _, u in sorted(inv.items())] for inv in inventories]
        # Same coverage must produce exactly the same complete normalized facts,
        # even when both runs share a known gap.
        if statuses[0] == statuses[1]:
            fail()
        common_files, common_regions = set(), set()
        for key, first in inventories[0].items():
            second = inventories[1][key]
            if first['parse_status'] == second['parse_status'] == 'PARSED':
                if not first.get('extraction_digest') or first != second:
                    fail()
                common_files.add(first['source_file'])
                common_regions.update(first.get('includes', []))
        if not common_files:
            fail()  # No reliably comparable region is not a verified local result.
        common_regions.update(common_files)
        for source in common_files:
            if expected.get('macros', {}).get(source) != actual.get('macros', {}).get(source):
                fail()
        for key in set(expected['functions']) | set(actual['functions']):
            left, right = expected['functions'].get(key), actual['functions'].get(key)
            if not any(v and v.get('file') in common_regions for v in (left, right)):
                continue
            if left is None or right is None:
                fail()
            # Binding to global storage may change with the missing TU. The
            # observed function itself must still be identical.
            if ({k: v for k, v in left.items() if k != 'dependencies'} !=
                    {k: v for k, v in right.items() if k != 'dependencies'}):
                fail()
        from .diff_risk import coverage_assessment
        def reliable_definition(value):
            owners = set(value.get('object_evidence', {}).get('translation_units') or [])
            return (value.get('file') in common_files or bool(owners) and owners <= common_files)
        for key in set(expected['variables']) | set(actual['variables']):
            left, right = expected['variables'].get(key), actual['variables'].get(key)
            if left is None or right is None:
                present = left or right
                if reliable_definition(present):
                    fail()
                continue
            # A global access/coverage gap may affect derived risk, but cannot
            # excuse a changed declaration already observed in a reliable TU.
            if (any(reliable_definition(v) for v in (left, right)) and
                    (left.get('file') != right.get('file') or
                     left['dimensions'].get('declaration') != right['dimensions'].get('declaration'))):
                fail()
            assessments = [coverage_assessment(v, s) for v, s in zip((left, right), scopes)]
            if all(not a['related_gaps'] and not a['unaccounted_gaps'] for a in assessments) and left != right:
                fail()
        # TU digests cover all extracted observations (including functions,
        # calls and aliases); global solver differences remain explicitly unverified.
    return dict(state='INCOMPLETE' if gaps else 'PASSED', variables=len(actual['variables']),
                reextracted_units=units, classification_mismatches=0, semantic_mismatches=0,
                mismatch_scope='RELIABLY_OBSERVED_ONLY' if gaps else 'COMPLETE_SUMMARY',
                gaps=gaps, scope='可靠观察已核对；局部缺口及其派生结论未完成验证' if gaps else '完整规范化事实一致')


def publication(diff):
    verification = diff.get('full_verification', {'state': 'NOT_RUN'})
    partial = (bool(diff.get('regional_gaps')) or verification['state'] == 'INCOMPLETE'
               or 'INCOMPLETE' in diff.get('comparison_analysis_status', {}).values())
    return dict(state='VALID_PARTIAL' if partial else 'COMPLETE',
                verification_state=verification['state'], regional_gap_count=len(diff.get('regional_gaps', [])))
