"""One bounded, read-only count scan of an owner-selected Player.log.

Only fixed aggregate counts and source fingerprints leave this process.
No path, request identity, action identity, card value or raw record is output.
"""
import argparse
import hashlib
import json
from pathlib import Path

from mtgaplayer.response_evidence import inspect_response_envelopes


def _fingerprint(path):
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return {'size_bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
            'sha256': digest.hexdigest()}


def validate(path, max_history_bytes, expected=None):
    before = _fingerprint(path)
    if before['size_bytes'] > max_history_bytes:
        raise ValueError('history_limit_exceeded')
    report = inspect_response_envelopes(path, max_history_bytes,
                                        choice_graph_history=True)
    after = _fingerprint(path)
    classification = report['complex_action_choice_correlation'][
        'selected_action_identity']['results_by_action_type']
    actual = {
        'framed_records': report['source']['framed_records'],
        'matched_actions': report['matched_actions_available_responses'],
        'unique': sum(row['unique_count'] for row in classification),
        'incomplete_or_unsupported': sum(
            row['incomplete_or_unsupported_count'] for row in classification),
    }
    stable = before == after
    expected_matches = expected is None or all(actual[key] == value
                                               for key, value in expected.items())
    return {
        'probe': 'mtga-choice-graph-bounded-validation-v1',
        'source_before': before, 'source_after': after,
        'source_stable': stable,
        'source_complete': report['source']['complete'],
        'framing_errors': report['source']['framing_errors'],
        'partial_record': report['source']['partial_record'],
        'baseline_counts': actual,
        'expected_baseline_matches': expected_matches,
        'historical_choice_relations': report['historical_choice_relations'],
        'identity_counts_account_for_all_matched': report[
            'complex_action_choice_correlation']['selected_action_identity'][
                'counts_account_for_all_matched_action_responses'],
        'raw_values_or_identifiers_exported': False,
        'input_sent': False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--max-history-bytes', type=int, default=64 * 1024 * 1024)
    parser.add_argument('--expect-framed-records', type=int)
    parser.add_argument('--expect-matched-actions', type=int)
    parser.add_argument('--expect-unique', type=int)
    parser.add_argument('--expect-incomplete', type=int)
    args = parser.parse_args(argv)
    if not 1 <= args.max_history_bytes <= 1024 * 1024 * 1024:
        parser.error('max-history-bytes out of range')
    expected = {key: value for key, value in (
        ('framed_records', args.expect_framed_records),
        ('matched_actions', args.expect_matched_actions),
        ('unique', args.expect_unique),
        ('incomplete_or_unsupported', args.expect_incomplete)) if value is not None}
    try:
        report = validate(args.input, args.max_history_bytes, expected)
    except (OSError, ValueError):
        print(json.dumps({'probe': 'mtga-choice-graph-bounded-validation-v1',
                          'error': 'file_unavailable_or_history_limit',
                          'input_sent': False}))
        return 1
    print(json.dumps(report, sort_keys=True, ensure_ascii=True))
    return 0 if (report['source_stable'] and report['source_complete'] and
                 report['expected_baseline_matches'] and
                 report['identity_counts_account_for_all_matched']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
