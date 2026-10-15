"""MP19 Phase 2: bounded, read-only coverage of already-projected DecisionState.

No GRE/Player.log reader, legality oracle, policy, executor, or network client.
Raw request identities are retained ONLY in bounded process memory for dedup.
CLI input is projected DecisionState v1 JSONL, not original game logs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from itertools import combinations
import hashlib
import json
from pathlib import Path
import subprocess
import sys

SCHEMA_VERSION = 'mtgaplayer.advisor-coverage.v1'
MAX_RECORDS = 4096
MAX_LINE_BYTES = 2 * 1024 * 1024
MAX_INPUT_BYTES = 64 * 1024 * 1024
BINDING_FIELDS = ('source_generation', 'match', 'game', 'self_seat',
                  'game_state_id', 'request_id', 'request_type')
REQUEST_TYPES = {
    'GREMessageType_ActionsAvailableReq': 'actions_available',
    'GREMessageType_SelectNReq': 'select_n',
    'GREMessageType_DeclareAttackersReq': 'declare_attackers',
    'GREMessageType_DeclareBlockersReq': 'declare_blockers',
}
ACTION_TYPES = {
    'ActionType_Pass': 'Pass', 'ActionType_Play': 'Play',
    'ActionType_Cast': 'Cast', 'ActionType_Activate': 'Activate',
    'ActionType_Activate_Mana': 'Activate_Mana',
    'ActionType_FloatMana': 'FloatMana',
    '_unrecognized_action_type': 'Unknown',
}
# Existing Advisor reason names are mapped to fixed output labels. Any novel
# free-form value becomes OTHER_UNKNOWN; it never enters an output artifact.
REASONS = {
    'historical_research_only': 'HISTORICAL_RESEARCH_ONLY',
    'evidence_only_policy': 'POLICY_ABSTENTION',
    'current_request_not_provided': 'CURRENT_REQUEST_UNAVAILABLE',
    'new_request_not_observed': 'CURRENT_REQUEST_UNAVAILABLE',
    'candidate_inventory_invalid': 'CANDIDATE_INVENTORY_INVALID',
    'invalid_decision_state': 'SOURCE_OR_CONSUMER_INVALID',
    'current_view_unavailable': 'SOURCE_OR_CONSUMER_INVALID',
    'current_snapshot_binding_invalid': 'SOURCE_OR_CONSUMER_INVALID',
    'current_snapshot_not_provided': 'SOURCE_OR_CONSUMER_INVALID',
    'requires_current_consumer': 'SOURCE_OR_CONSUMER_INVALID',
    'simple_candidate_structure_incomplete': 'STRUCTURE_UNSUPPORTED',
    'choice_graph_candidate_conflict': 'CANDIDATE_INVENTORY_INVALID',
    'unique_play_not_observed': 'MULTIPLE_OR_NO_UNIQUE_PLAY',
    'complex_or_unsupported_candidates': 'COMPLEX_PARAMETERS_UNKNOWN',
    'select_n_candidates_not_provided': 'CANDIDATE_INVENTORY_INVALID',
    'select_n_strategy_unsupported': 'SELECT_N_COMBINATIONS_UNKNOWN',
    'combat_strategy_unsupported': 'COMBAT_COMBINATIONS_UNKNOWN',
    'combat_candidate_inventory_incomplete': 'CANDIDATE_INVENTORY_INVALID',
    'unsupported_request_type': 'OTHER_UNKNOWN',
    'no_engine_offered_candidates': 'CURRENT_REQUEST_UNAVAILABLE',
    'unsupported_policy_version': 'POLICY_ABSTENTION',
}
CANDIDATE_GAPS = {
    'UNSUPPORTED_STRUCTURE': 'STRUCTURE_UNSUPPORTED',
    'PARAMETERS_PARTIAL': 'COMPLEX_PARAMETERS_UNKNOWN',
    'COMBINATION_UNKNOWN': 'COMBINATIONS_UNKNOWN',
    'RESPONSE_UNVERIFIED': 'RESPONSE_ENCODING_UNKNOWN',
}
# Existing action_gaps labels are used as taxonomy only: this tool does NOT
# re-interpret effects, cost, targets, response bytes, or raw action details.
TYPE_GAPS = {
    'ActionType_Pass': ('pass_response_contract_unverified',),
    'ActionType_Play': ('play_conditions_unverified',),
    'ActionType_Cast': ('cast_payment_unverified', 'cast_effect_and_targets_unverified'),
    'ActionType_Activate': ('activation_cost_unverified', 'ability_effect_and_targets_unverified'),
    'ActionType_Activate_Mana': ('mana_effect_and_payment_unverified',),
}
AUTHORITY_KEYS = ('legal_choice_verified', 'complete_legality_verified',
                  'response_encoding_verified', 'server_acceptance_verified',
                  'execution_ready', 'input_sent', 'actionable', 'executor_connected')


def _advice_shape_valid(advice):
    if not isinstance(advice, dict) or advice.get('schema_version') != 'mtgaplayer.decision-advice.v1':
        return False
    execution = advice.get('execution')
    return (advice.get('read_only') is True and type(execution) is dict
            and all(execution.get(key) is False for key in AUTHORITY_KEYS)
            and isinstance(advice.get('candidate_coverage'), dict)
            and isinstance(advice.get('candidate_assessments'), list)
            and advice.get('assessment_status') in ('abstain', 'research_preference'))


def _safe_kind(binding):
    return REQUEST_TYPES.get(binding.get('request_type'), 'unsupported')


def _fixed_reason(reason):
    if type(reason) is str and reason.startswith('consumer_'):
        return 'SOURCE_OR_CONSUMER_INVALID'
    return REASONS.get(reason, 'OTHER_UNKNOWN')


def _safe_id_tuple(advice):
    binding = advice.get('request_identity')
    if type(binding) is not dict:
        return None
    try:
        identity = tuple(binding[key] for key in BINDING_FIELDS)
        # Prevent unhashable/unbounded arbitrary keys from breaking attribution.
        if any(type(v) not in (str, int, type(None)) for v in identity):
            return None
        if any(type(v) is str and len(v) > 4096 for v in identity):
            return None
        return identity
    except KeyError:
        return None


def _signature(advice):
    # Ignore snapshot_ref, view timestamps and raw request identity values;
    # normalized Advisor assessment is stable for one unchanged request.
    return json.dumps({k: advice.get(k) for k in (
        'assessment_status', 'policy_version', 'candidate_coverage',
        'candidate_assessments', 'request_summary', 'abstention_reason',
        'unresolved')}, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _ratio(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'value': numerator / denominator if denominator else None}


class CoverageAccumulator:
    """Bounded per-dataset analytical groups; not a request lifecycle ledger.

    add_projected() accepts only projected DecisionState, never raw GRE.
    add_current_consumer() calls the actual Advisor on a real Consumer instance
    and stores no long-lived authority. No imported/detached JSON can claim a
    newly observed current decision. Duplicate-conflicting identities are
    quarantined in the summary rather than counted as valid opportunities.
    """

    def __init__(self, *, assessor=None, dataset_kind='synthetic_projected_offline'):
        if dataset_kind not in ('synthetic_projected_offline',
                                'scrubbed_projected_offline',
                                'projected_offline_provenance_unverified'):
            raise ValueError('unsupported_dataset_kind')
        self._assessor = assessor
        self.dataset_kind = dataset_kind
        self._groups = {}
        self._raw_records = 0
        self._malformed_records = 0
        self._missing_states = 0
        self._invalid_states = 0
        self._valid_states = 0
        self._valid_no_request = 0
        self._repeated = 0
        self._invalid_current = 0
        self._current_assessments = 0

    def add_malformed(self):
        self._raw_records += 1
        self._malformed_records += 1

    def add_projected(self, record):
        self._raw_records += 1
        if type(record) is dict and 'decision_state' in record:
            state = record['decision_state']
        elif type(record) is dict and record.get('schema_version') == 'mtgaplayer.decision-state.v1':
            state = record
        else:
            self._malformed_records += 1
            return
        if state is None:
            self._missing_states += 1
            return
        assessor = self._assessor
        if assessor is None:
            from mtgaplayer.decision_advisor import assess_decision_state
            assessor = assess_decision_state
        try:
            advice = assessor(state)
        except (ValueError, KeyError, TypeError, RecursionError, UnicodeError):
            self._invalid_states += 1
            return
        if not _advice_shape_valid(advice) or advice.get('historical_research_only') is not True:
            self._invalid_states += 1
            return
        if advice.get('abstention_reason') == 'invalid_decision_state':
            self._invalid_states += 1
            return
        self._valid_states += 1
        identity = _safe_id_tuple(advice)
        if identity is None:
            self._invalid_states += 1
            self._valid_states -= 1
            return
        if identity[-2] is None:
            self._valid_no_request += 1
            return
        self._save('historical', identity, advice)

    def add_current_consumer(self, consumer, *, policy_version='evidence_only.v1'):
        """Ephemeral opt-in sample. Does NOT certify real server freshness."""
        from mtgaplayer.decision_advisor import assess_current_decision
        advice = assess_current_decision(consumer, policy_version=policy_version)
        self._current_assessments += 1
        if not _advice_shape_valid(advice):
            self._invalid_current += 1
            return
        identity = _safe_id_tuple(advice)
        if (identity is None or identity[-2] is None or
                advice.get('assessment_scope') != 'current_snapshot_research_only'):
            self._invalid_current += 1
            return
        self._save('consumer_current', identity, advice)

    def _save(self, scope, identity, advice):
        # The tuple never leaves memory. Separate historical/current datasets.
        key = (scope, identity)
        try:
            signature = _signature(advice)
        except (TypeError, ValueError, RecursionError):
            self._invalid_states += 1
            return
        if key in self._groups:
            self._repeated += 1
            self._groups[key][0].add(signature)
        else:
            self._groups[key] = ({signature}, advice)

    def summary(self, *, code=None):
        included = [(k[0], record[1]) for k, record in self._groups.items()
                    if len(record[0]) == 1]
        conflicts = sum(len(record[0]) > 1 for record in self._groups.values())
        reqs, actions, abstention, gaps, candidate_gaps, pairs = (Counter() for _ in range(6))
        total_offered = total_interpreted = valid_action_inventories = action_requests = 0
        unknown_inventories = total_combat = verified_combat = unknown_combat_links = 0
        select_n_refs = 0
        current_requests = current_preference = historical_requests = 0
        for scope, advice in included:
            if scope == 'historical':
                historical_requests += 1
            else:
                current_requests += 1
                current_preference += advice.get('assessment_status') == 'research_preference'
            binding = advice['request_identity']
            kind = _safe_kind(binding)
            reqs[kind] += 1
            abstention[_fixed_reason(advice.get('abstention_reason'))] += 1 if advice.get('assessment_status') == 'abstain' else 0
            request_gaps = set()
            if any(assessment.get('strategic_utility') is None
                   for assessment in advice.get('candidate_assessments', ())):
                request_gaps.add('STRATEGIC_UTILITY_UNKNOWN')
            coverage = advice['candidate_coverage']
            if kind == 'actions_available':
                action_requests += 1
                if coverage.get('inventory_integrity_verified') is not True:
                    unknown_inventories += 1
                    request_gaps.add('CANDIDATE_INVENTORY_INVALID')
                else:
                    valid_action_inventories += 1
                    candidates = advice['candidate_assessments']
                    # Use only inventories fully verified by the actual Advisor.
                    count = coverage.get('offered_count')
                    if type(count) is not int or count != len(candidates):
                        unknown_inventories += 1
                        valid_action_inventories -= 1
                    else:
                        total_offered += count
                        for cand in candidates:
                            name = cand.get('engine_action_type')
                            label = ACTION_TYPES.get(name, 'Unknown')
                            actions[label] += 1
                            total_interpreted += cand.get('structurally_interpreted') is True
                            flags = cand.get('evidence_quality')
                            labels = set(flags) if type(flags) is list else set()
                            for label_gap in labels:
                                if label_gap in CANDIDATE_GAPS:
                                    cat = CANDIDATE_GAPS[label_gap]
                                    candidate_gaps[cat] += 1
                                    request_gaps.add(cat)
                            for type_gap in TYPE_GAPS.get(name, ()):
                                candidate_gaps[type_gap] += 1
                                request_gaps.add(type_gap)
                            if cand.get('strategic_utility') is None:
                                candidate_gaps['STRATEGIC_UTILITY_UNKNOWN'] += 1
            elif kind == 'select_n':
                count = coverage.get('offered_count')
                if type(count) is int and count >= 0 and coverage.get('inventory_integrity_verified') is True:
                    select_n_refs += count
                else:
                    request_gaps.add('CANDIDATE_INVENTORY_INVALID')
                request_gaps.update(('SELECT_N_COMBINATIONS_UNKNOWN', 'SELECT_N_MINIMUM_UNKNOWN'))
            elif kind in ('declare_attackers', 'declare_blockers'):
                request_gaps.add('COMBAT_COMBINATIONS_UNKNOWN')
                if coverage.get('inventory_integrity_verified') is not True:
                    request_gaps.add('CANDIDATE_INVENTORY_INVALID')
                else:
                    total_combat += len(advice.get('candidate_assessments', ()))
                    for item in advice['candidate_assessments']:
                        verified_combat += item.get('reference_verified') is True
                        edges = item.get('engine_listed_attacker_references')
                        if edges is None:
                            unknown_combat_links += 1
                        elif type(edges) is list:
                            unknown_combat_links += sum(x.get('public_reference_verified') is not True
                                                        for x in edges if type(x) is dict)
            else:
                request_gaps.add('UNSUPPORTED_REQUEST_TYPE')
            request_gaps.add('RESPONSE_ENCODING_UNKNOWN')
            for tag in request_gaps:
                gaps[tag] += 1
            for left, right in combinations(sorted(request_gaps), 2):
                pairs[(left, right)] += 1
        report = {
            'schema_version': SCHEMA_VERSION,
            'code': code if code is not None else {'head': None, 'tree': None},
            'input_kind': self.dataset_kind,
            'qualification': {
                'synthetic_projected_offline': 'SYNTHETIC_COVERAGE_ONLY',
                'scrubbed_projected_offline': 'SCRUBBED_OFFLINE_SAMPLE_ONLY',
                'projected_offline_provenance_unverified': 'UNVERIFIED_PROJECTED_COVERAGE_ONLY',
            }[self.dataset_kind],
            'priority_verdict': 'PRIORITY_EVIDENCE_INSUFFICIENT',
            'live_or_server_coverage_qualified': False,
            'limits': ['sample_distribution_not_necessarily_representative',
                       'historical_policy_abstention_is_not_strategy_failure',
                       'engine_offered_not_complete_legality',
                       'effect_payment_target_response_encoding_unknown',
                       'real_mtga_three_second_loop_unverified'],
            'counts': {
                'input_records': self._raw_records,
                'malformed_record_count': self._malformed_records,
                'missing_state_count': self._missing_states,
                'invalid_state_count': self._invalid_states,
                'valid_state_record_count': self._valid_states,
                'valid_state_without_request_records': self._valid_no_request,
                'duplicate_record_count': self._repeated,
                'conflicting_request_identity_groups': conflicts,
                'excluded_conflicting_request_groups': conflicts,
                'unique_historical_requests': historical_requests,
                'unique_ephemeral_current_consumer_requests': current_requests,
                'invalid_ephemeral_current_checks': self._invalid_current,
                'total_ephemeral_current_checks': self._current_assessments,
                'request_groups_analyzed': len(included),
                'action_request_groups': action_requests,
                'valid_action_inventory_groups': valid_action_inventories,
                'unknown_action_inventory_groups': unknown_inventories,
                'active_actions_with_verified_inventory': total_offered,
                'structurally_interpreted_active_actions': total_interpreted,
                'other_request_select_n_offered_references': select_n_refs,
                'other_request_combat_offered_references': total_combat,
                'other_request_combat_verified_public_references': verified_combat,
                'other_request_combat_unresolved_links': unknown_combat_links,
            },
            'request_type_counts': {k: reqs[k] for k in (*REQUEST_TYPES.values(), 'unsupported')},
            'action_type_counts': {k: actions[k] for k in ACTION_TYPES.values()},
            'abstention_category_counts': dict(sorted((k, v) for k, v in abstention.items() if v)),
            'request_gap_counts': dict(sorted(gaps.items())),
            'candidate_gap_counts': dict(sorted(candidate_gaps.items())),
            'request_gap_cooccurrence': [
                {'a': a, 'b': b, 'request_groups': count}
                for (a, b), count in sorted(pairs.items())],
            'rates': {
                'inventory_valid_rate': _ratio(valid_action_inventories, action_requests),
                'structurally_interpreted_rate': _ratio(total_interpreted, total_offered),
                'unsupported_candidate_rate': _ratio(total_offered - total_interpreted, total_offered),
                'experimental_preference_rate': _ratio(current_preference, current_requests),
            },
            'next_candidates': [
                {'target': 'simple_pass_play_semantics', 'status': 'conditional_requires_real_semantic_evidence'},
                {'target': 'cast_activate_parameters', 'status': 'conditional_requires_payment_target_evidence'},
                {'target': 'combat_combinations', 'status': 'conditional_requires_rules_and_recipient_evidence'},
            ],
            'read_only': True,
            'execution': {k: False for k in AUTHORITY_KEYS},
        }
        # Explain each denominator and its exclusions. A percentage of active
        # rows is NOT a percentage of legal moves or of real-game decisions.
        rate_population = {
            'inventory_valid_rate': 'distinct_actions_available_request_groups',
            'structurally_interpreted_rate': 'active_engine_action_rows_with_verified_inventory',
            'unsupported_candidate_rate': 'active_engine_action_rows_with_verified_inventory',
            'experimental_preference_rate': 'distinct_ephemeral_current_consumer_request_groups',
        }
        for name, rate in report['rates'].items():
            rate['population'] = rate_population[name]
            rate['sample_kind'] = ('in_process_consumer_current_not_server_verified'
                                   if name == 'experimental_preference_rate' else self.dataset_kind)
            rate['excluded_conflicting_request_groups'] = conflicts
            rate['excluded_unknown_action_inventory_groups'] = (
                unknown_inventories if name in ('structurally_interpreted_rate',
                                                'unsupported_candidate_rate') else 0)
            rate['excluded_invalid_ephemeral_checks'] = (
                self._invalid_current if name == 'experimental_preference_rate' else 0)
        return report


def _strict_json(line):
    def unique_pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('duplicate_json_key')
            result[k] = v
        return result
    return json.loads(line, object_pairs_hook=unique_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))


def inspect_stream(stream, *, assessor=None, dataset_kind='synthetic_projected_offline'):
    aggregate = CoverageAccumulator(assessor=assessor, dataset_kind=dataset_kind)
    total_bytes = 0
    for index, line in enumerate(stream, start=1):
        if index > MAX_RECORDS:
            raise ValueError('input_record_limit_exceeded')
        total_bytes += len(line)
        if len(line) > MAX_LINE_BYTES or total_bytes > MAX_INPUT_BYTES:
            raise ValueError('input_bytes_limit_exceeded')
        try:
            record = _strict_json(line)
        except (ValueError, UnicodeError, TypeError):
            aggregate.add_malformed()
            continue
        aggregate.add_projected(record)
    return aggregate


def _code():
    root = Path(__file__).resolve().parents[1]
    def git(*args):
        try:
            return subprocess.check_output(['git', *args], cwd=root, text=True,
                                           stderr=subprocess.DEVNULL, timeout=3).strip()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
    tracked = git('status', '--porcelain', '--untracked-files=no')
    source_paths = ('scripts/inspect_advisor_coverage.py', 'src/mtgaplayer/decision_advisor.py')
    hashes = {}
    for rel in source_paths:
        candidate = root / rel
        hashes[rel] = hashlib.sha256(candidate.read_bytes()).hexdigest() if candidate.is_file() else None
    return {'head': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
            'tracked_dirty': None if tracked is None else bool(tracked),
            'source_sha256': hashes}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path,
                        help='already-projected DecisionState v1 JSONL; NEVER raw Player.log')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dataset-kind', choices=('synthetic_projected_offline', 'scrubbed_projected_offline',
                        'projected_offline_provenance_unverified'),
                        default='synthetic_projected_offline')
    args = parser.parse_args(argv)
    if args.input.resolve() == args.output.resolve():
        parser.error('input/output must differ')
    if args.input.resolve().name.casefold() == 'player.log':
        parser.error('raw Player.log is outside this projected-input analysis')
    try:
        with args.input.open('rb') as source:
            aggregate = inspect_stream(source, dataset_kind=args.dataset_kind)
        result = aggregate.summary(code=_code())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    except (OSError, ValueError, RuntimeError, ImportError):
        # Print only a fixed reason, never a source path or private source value.
        print(json.dumps({'qualified': False, 'error': 'coverage_input_or_processing_error'}))
        return 1
    print(json.dumps({'qualified': True, 'analysis_scope': result['qualification'],
                      'input_records': result['counts']['input_records']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
