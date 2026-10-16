"""Read-only visual evidence contracts, scoped count comparison and diagnostics.

This module recognizes no pixels and parses no GRE. Callers supply independent
pixel observations and counts from the existing projection as separate sources.
"""
import copy


SCHEMA = 'mtgaplayer.visual-count.v1'
QUALITY_REASONS = {'black_frame', 'white_frame', 'low_variance_frame'}


def _count(value):
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError('count_must_be_nonnegative_integer_or_unknown')


def _validate(observation):
    if not isinstance(observation, dict) or observation.get('schema_version') != SCHEMA:
        raise ValueError('invalid_visual_count_contract')
    if not isinstance(observation.get('field'), str) or not observation['field']:
        raise ValueError('count_field_required')
    if 'value' not in observation:
        raise ValueError('count_value_or_explicit_unknown_required')
    _count(observation['value'])
    source, visibility, coverage = (observation.get(key) for key in ('source', 'visibility', 'coverage'))
    if source == 'GRE':
        if visibility != 'GRE_presence_only' or coverage != 'engine_zone_total':
            raise ValueError('GRE_presence_must_not_be_visual')
    elif source == 'visual':
        if visibility not in {'visible', 'partial', 'uncertain'}:
            raise ValueError('invalid_visual_visibility')
        if coverage not in {'visible_subset', 'explicit_complete_coverage', 'unknown'}:
            raise ValueError('invalid_visual_coverage')
        if coverage == 'explicit_complete_coverage' and (
                visibility != 'visible' or not isinstance(observation.get('coverage_evidence'), str)
                or not observation['coverage_evidence'].strip()):
            raise ValueError('complete_coverage_requires_visible_evidence')
    else:
        raise ValueError('unsupported_observation_source')
    evidence = observation.get('evidence')
    if not isinstance(evidence, dict) or not isinstance(evidence.get('reference'), str) or not evidence['reference']:
        raise ValueError('evidence_reference_required')
    if source == 'visual':
        digest = evidence.get('frame_sha256')
        if not isinstance(digest, str) or len(digest) != 64 or any(ch not in '0123456789abcdef' for ch in digest):
            raise ValueError('visual_frame_sha256_required')
    reasons = observation.get('uncertainty_reasons')
    if not isinstance(reasons, list) or any(not isinstance(reason, str) or not reason for reason in reasons):
        raise ValueError('uncertainty_reasons_must_be_strings')
    return observation


def visual_count(field, value, *, frame_ref, frame_sha256, visibility='visible',
                 coverage='visible_subset', coverage_evidence=None, uncertainty_reasons=()):
    """Declare a pixel-only count; explicit coverage never defaults to complete.

    ``value`` is the observed subset or lower bound when coverage is incomplete.
    The caller must preserve how independently the pixels were interpreted.
    """
    if isinstance(uncertainty_reasons, str):
        raise ValueError('uncertainty_reasons_must_be_strings')
    return _validate({'schema_version': SCHEMA, 'field': field, 'source': 'visual',
        'visibility': visibility, 'coverage': coverage, 'value': value,
        'coverage_evidence': coverage_evidence,
        'evidence': {'reference': frame_ref, 'frame_sha256': frame_sha256},
        'uncertainty_reasons': list(uncertainty_reasons)})


def gre_presence_count(field, value, *, source_ref):
    """A separately sourced GRE zone total, never a value filled into pixels."""
    return _validate({'schema_version': SCHEMA, 'field': field, 'source': 'GRE',
        'visibility': 'GRE_presence_only', 'coverage': 'engine_zone_total', 'value': value,
        'coverage_evidence': None, 'evidence': {'reference': source_ref}, 'uncertainty_reasons': []})


def compare_counts(observation, before, after):
    """Compare one capture event; content hashes never deduplicate capture times.

    Stable collection endpoints do not prove synchronized rendering or causality.
    Even a complete-coverage numeric conflict does not identify a parser defect.
    """
    _validate(observation)
    for side in (before, after):
        if side is not None:
            _validate(side)
            if side['source'] != 'GRE' or side['field'] != observation['field']:
                raise ValueError('comparison_requires_matching_GRE_field')
    result = {'schema_version': 'mtgaplayer.visual-comparison.v1',
        'field': observation['field'], 'observation': copy.deepcopy(observation),
        'GRE_before': copy.deepcopy(before), 'GRE_after': copy.deepcopy(after),
        'visual_value': observation['value'] if observation['source'] == 'visual' else None,
        'GRE_before_value': before['value'] if before else None,
        'GRE_after_value': after['value'] if after else None,
        'scope_comparable': False, 'renderer_synchronization': 'unknown',
        'causal_proof': False, 'parser_error_proven': False}
    if observation['source'] == 'GRE':
        status, reason = 'GRE_presence_only', 'log_presence_is_not_visual_verification'
    elif observation['value'] is None or observation['visibility'] == 'uncertain':
        status, reason = 'insufficient_evidence', 'visual_value_unknown_or_uncertain'
    elif before is None or after is None or before['value'] is None or after['value'] is None:
        status, reason = 'insufficient_evidence', 'GRE_bracket_missing_or_unknown'
    elif before['value'] != after['value']:
        status, reason = 'time_association_uncertain', 'GRE_count_changed_across_capture_bracket'
    elif observation['coverage'] != 'explicit_complete_coverage' or observation['visibility'] != 'visible':
        status, reason = 'scope_mismatch', 'visible_subset_is_not_complete_GRE_zone_total'
    elif observation['uncertainty_reasons']:
        status, reason = 'insufficient_evidence', 'visual_animation_render_or_quality_uncertainty'
    else:
        result['scope_comparable'] = True
        status = 'verified_consistent' if observation['value'] == before['value'] else 'conflict_in_observed_bracket'
        reason = 'complete_observed_count_compared_with_stable_collected_GRE_count'
    result.update(status=status, reason=reason)
    return result


def capture_diagnostics(record, previous=None, *, gre_advanced=None):
    """Report acquisition, heuristic and time facts without recognizing content.

    Legacy records lacking an explicit acquisition status stay unknown, even if
    they contain a saved file or a black-background heuristic result. No failed
    heuristic is upgraded to a usable state, and no repeated hash proves stale
    rendering. GRE progress cannot establish a network-delay measurement.
    """
    capture = record.get('capture_result') or {}
    quality = capture.get('quality') or {}
    reason = quality.get('failure_reason') or capture.get('reason')
    quality_status = ('failed' if reason in QUALITY_REASONS else
                      'passed' if quality and quality.get('failure_reason') is None else 'unknown')
    acquisition = capture.get('pixel_acquisition_status', 'unknown')
    if acquisition not in {'not_attempted', 'attempted', 'succeeded', 'failed', 'unknown'}:
        acquisition = 'unknown'
    start = (record.get('capture_started') or {}).get('monotonic_ns')
    end = (record.get('capture_completed') or {}).get('monotonic_ns')
    duration = ((end - start) / 1_000_000_000
                if type(start) is int and type(end) is int and end >= start else None)
    digest, old_digest = record.get('sha256'), previous.get('sha256') if previous else None
    relation = ('first_capture' if previous is None else 'not_comparable' if not digest or not old_digest else
                'unchanged' if digest == old_digest else 'changed')
    return {'schema_version': 'mtgaplayer.capture-diagnostics.v1',
        'capture_id': record.get('capture_id'), 'frame_ref': record.get('file'), 'frame_sha256': digest,
        'overall_capture_status': capture.get('status', 'unknown'),
        'pixel_acquisition_status': acquisition, 'capture_stage': capture.get('capture_stage', 'unknown'),
        'file_saved': bool(record.get('file_completed')), 'quality_status': quality_status,
        'quality_reason': reason if reason in QUALITY_REASONS else None,
        'quality_heuristic_only': quality.get('heuristic_only'),
        'visual_state_usable': 'unknown', 'blank_content_proven': False,
        'freshness': {'capture_started_ns': start, 'capture_completed_ns': end,
            'capture_duration_seconds': duration, 'content_relation': relation,
            'previous_capture_id': previous.get('capture_id') if previous else None,
            'gre_advanced': gre_advanced, 'render_timestamp': None, 'renderer_freshness': 'unknown',
            'assessment': 'uncertain' if relation == 'unchanged' and gre_advanced is True else 'unknown',
            'stale_capture_proven': False, 'network_delay_seconds': None}}
