"""One current-request research view over existing inventories and validators.

No parsing, solver, response or input authority. Source domains stay separate:
an offered action, parent member probe and a child proposal are different items.
"""
import copy

from .decision_consumer import DecisionConsumer, EXECUTION, _bounded_json
from .decision_advisor import assess_decision_state, _validate_state
from .choice_candidates import enumerate_known_candidates, _assess_current_report

VERSION = 'mtgaplayer.current-decision-options.v1'
MAX_OPTIONS = 64
UNKNOWN = ('complete_legality_unknown', 'complete_payment_unknown',
           'response_encoding_unknown', 'server_acceptance_unknown',
           'full_action_domain_unknown')


def _unknown(reason, ref=None):
    expired = 'expired' in reason or reason == 'consumer_stale'
    return {'schema_version': VERSION,
        'status': 'expired' if expired else 'insufficient_evidence',
        'reason': reason, 'request_binding': None, 'source_snapshot_ref': copy.deepcopy(ref),
        'visible_state': None, 'request_observation': None, 'continuation_context': None,
        'coverage': {'engine_offered_count': None, 'engine_offered_unit': None,
            'reviewed_candidate_count': None, 'unknown_count': None,
            'returned_options': 0, 'omitted_constructed_options': 0, 'truncated': False,
            'count_basis': 'separate_source_domains; reviewed_count_is_returned_options_only', 'sources': []},
        'options': [], 'unresolved': [{'evidence_level': 'expired' if expired else 'insufficient_evidence', 'reason': reason}],
        'complete_legality_verified': False, 'read_only': True, **EXECUTION}


def _option(binding, ref, kind, source, position, observation=None, proposal=None, scope=None):
    return {'option_key': {'kind': kind, 'source': source, 'source_position': position},
        'kind': kind, 'sources': [source], 'list_position': proposal.get('list_position') if proposal else None,
        'request_binding': copy.deepcopy(binding), 'source_snapshot_ref': copy.deepcopy(ref),
        'evidence_level': 'known_constraints_verified' if proposal else 'engine_offered',
        'validation_scope': scope, 'proposal': copy.deepcopy(proposal),
        'observation': copy.deepcopy(observation), 'unresolved': list(UNKNOWN),
        'research_eligible': True, 'read_only': True, **EXECUTION}


def _version(evidence):
    if evidence is None: return None
    from .cast_activate_associations import PROFILE as FAMILIES
    from .activate_target_payment import PROFILE as RELATION
    from .cast_target_members import PROFILE as CAST
    from .semantic_hand import CURRENT_PROFILE as DISCARD
    from .action_target_menus import CURRENT_PROFILE as MEMBER
    from .semantic_targets import PROFILE as TARGET, SELECT
    profile = evidence['profile']
    if profile in (FAMILIES, RELATION): return 6
    if profile == CAST: return 5
    if profile == DISCARD: return 4
    if profile == MEMBER: return 3
    if profile == TARGET:
        entries = evidence['targets']['entries']
        return 2 if entries is not None and all(e['legal_action'] == SELECT for e in entries) else 3
    return 2


def _context(state):
    version = int(state['schema_version'].rsplit('v', 1)[1])
    value = None; field = None
    if version == 14 and state['revised_choice_continuation'] is not None:
        field = 'revised_choice_continuation'; value = state[field]
        parent = value['first_child']['parent']
    elif version in (13, 14, 15) and state['choice_continuation'] is not None:
        field = 'choice_continuation'; value = state[field]; parent = value['parent']
    elif version == 15 and state['cast_choice_continuation'] is not None:
        field = 'cast_choice_continuation'; value = state[field]; parent = value['parent']
    if value is None: return None
    return {'field': field, 'provenance': value['schema_version'],
        'current_request_binding': copy.deepcopy(value['binding']),
        'historical_parent_binding': copy.deepcopy(parent['binding']),
        'historical_parent_current': False, 'raw_source_reauthenticated': False}


def _build(state, ref, limit):
    _validate_state(state)
    binding = state['binding']
    if binding['request_id'] is None: return _unknown('current_request_not_observed')
    result = _unknown('additional_rules_and_parameters_unverified', ref)
    result.update(status='partial', request_binding=copy.deepcopy(binding),
        visible_state={k: copy.deepcopy(state[k]) for k in ('game', 'visible_objects', 'card_knowledge')},
        continuation_context=_context(state))
    coverage = result['coverage']; options = []; sources = coverage['sources']
    advice = assess_decision_state(state)
    result['unresolved'].extend({'evidence_level': 'insufficient_evidence', 'reason': reason}
        for reason in sorted(set((*state['unresolved'], *advice['unresolved']))))
    ac = advice['candidate_coverage']; rows = advice['candidate_assessments']
    frontier = state['legal_action_space']['immediate_frontier']
    params = state['legal_action_space'].get('request_parameters')
    # _validate_state already checked this versioned Graph extension. Reuse
    # its facts rather than decode the action/slots a second time here.
    from .multi_slot_cast import FIELD as MULTI_SLOT
    graph = state['legal_action_space']['choice_graph']
    multi = {node['action_key']['list_position']: constraint[MULTI_SLOT]
        for node in graph['action_nodes'] for constraint in node['constraints']
        if MULTI_SLOT in constraint} if graph else {}
    result['request_observation'] = {'request_type': binding['request_type'],
        'parameter_profile': params['profile'] if params else None,
        'target_literals': copy.deepcopy(params.get('targets')) if params else None,
        'select_n_literals': copy.deepcopy(frontier['projection']) if frontier['kind'] == 'select_n' else None,
        'discard_literals': copy.deepcopy(params.get('discard_request')) if params else None}
    unit = {'actions_available': 'active_action_row', 'select_n': 'offered_member',
        'declare_attackers': 'attacker_candidate', 'declare_blockers': 'blocker_candidate'}.get(frontier['kind'])
    if ac['inventory_integrity_verified']:
        coverage.update(engine_offered_count=ac['offered_count'], engine_offered_unit=unit)
        for position, row in enumerate(rows):
            kind = 'engine_action' if frontier['kind'] == 'actions_available' else 'engine_member'
            observation = copy.deepcopy(row)
            if kind == 'engine_action':
                template = frontier['projection']['templates'][position]
                observation.update({k: copy.deepcopy(template[k]) for k in
                    ('visible_object_id', 'observed_parameter_shapes', 'unknown_parameter_fields_present')})
                if position in multi:
                    observation[MULTI_SLOT] = multi[position]
            option = _option(binding, ref, kind, 'decision_advisor', position, observation)
            option['list_position'] = position
            if row.get('structurally_interpreted'):
                option['evidence_level'] = 'structurally_decoded'
            if row.get('engine_action_type') == '_unrecognized_action_type':
                option.update(evidence_level='unsupported', research_eligible=False)
            option['unresolved'] = sorted(set((*UNKNOWN, *row.get('unresolved_parameters', ()))))
            options.append(option)
        sources.append({'source': 'decision_advisor', 'scope': 'engine_offered_inventory_only',
            'unit': unit, 'observed': ac['offered_count'], 'constructed_options': len(rows), 'truncated': False})
    else:
        result['unresolved'].append({'evidence_level': 'unsupported',
            'source': 'decision_advisor', 'reason': advice['abstention_reason']})
    if params and 'targets' in params:
        entries = params['targets']['entries']
        coverage.update(engine_offered_count=len(entries) if entries is not None else None,
            engine_offered_unit='current_target_entry')
    if params and 'discard_request' in params:
        offered = params['discard_request']['payload']['offered_object_refs']
        coverage.update(engine_offered_count=len(offered), engine_offered_unit='discard_offered_member')
    if params and 'cost_selection' in params:
        coverage.update(engine_offered_count=len(params['cost_selection']['offered_object_refs']),
            engine_offered_unit='cost_offered_member')

    def include(report, label, relation=False):
        # Keep each generator's denominator, including null totals and budgets.
        scope = report.get('validation_scope') or report['scope']
        stats = {k: copy.deepcopy(report[k]) for k in ('candidate_total_for_reviewed_constraints',
            'returned_candidates', 'truncated', 'probe_coverage', 'member_probes', 'target_quantities',
            'offered_member_count', 'minimum', 'maximum', 'selected_count', 'action_row_coverage',
            'returned_relations') if k in report}
        if isinstance(stats.get('action_row_coverage'), dict):
            stats['action_row_coverage'].pop('row_statuses', None)
        source = {'source': label, 'scope': scope, 'coverage': stats, 'reason': report['reason'],
            'constructed_options': 0, 'truncated': report.get('truncated', False)}
        sources.append(source)
        result['unresolved'].append({'source': label, 'evidence_level': 'insufficient_evidence',
            'reason': report['reason'], 'scope': scope})
        for name in ('probe_coverage', 'member_probes'):
            counts = report.get(name) or {}
            if counts.get('contradicted'):
                result['unresolved'].append({'source': label, 'evidence_level': 'violated_known_constraints',
                    'scope': scope, 'count': counts['contradicted'], 'unit': 'source_probes'})
        row_coverage = report.get('action_row_coverage') or {}
        contradicted = (report.get('contradicted_probes') or row_coverage.get('contradicted_known_constraint_rows')
            or row_coverage.get('contradicted_known_relation_rows'))
        if contradicted:
            result['unresolved'].append({'source': label, 'evidence_level': 'violated_known_constraints',
                'scope': scope, 'count': contradicted, 'unit': 'source_probes_or_action_rows'})
        for position, item in enumerate(report.get('relations' if relation else 'candidates', [])):
            if relation:
                option = _option(binding, ref, 'activate_target_payment_association', label, position,
                    observation=item, scope=scope)
                option.update(evidence_level='known_constraints_verified', list_position=item['list_position'])
            else:
                proposal = item.get('proposal', item)
                from .choice_validation import check_proposal
                check_proposal(proposal)
                if proposal['request_identity'] != binding or proposal.get('source_snapshot_ref') != ref:
                    raise ValueError('candidate_binding_mismatch')
                kinds = {'proposed_action': 'offered_action', 'proposed_final_target_set': 'final_target_set',
                    'proposed_current_selected_target_set': 'current_selected_literal_probe',
                    'proposed_cast_target_member': 'parent_cast_member_probe',
                    'proposed_activate_target_member': 'parent_activate_member_probe',
                    'proposed_discard_selection': 'discard_selection_probe', 'proposed_cost_selection': 'cost_selection'}
                kind = next(v for k, v in kinds.items() if k in proposal)
                proposal_scope = scope
                if label == 'known_candidates_v2':
                    from .semantic_targets import SCOPE as TARGET_SCOPE
                    from .semantic_activate import PROFILE as ACTIVATE, SCOPE as ACTIVATE_SCOPE
                    from .choice_validation import SCOPE as PAYMENT_SCOPE
                    proposal_scope = (TARGET_SCOPE if kind == 'final_target_set' else
                        'offered_visible_single_nonmana_selection_consistency' if kind == 'cost_selection' else
                        ACTIVATE_SCOPE if params['profile'] == ACTIVATE else PAYMENT_SCOPE)
                option = _option(binding, ref, kind, label, position, proposal=proposal, scope=proposal_scope)
                if kind == 'offered_action':
                    pos = proposal['list_position']
                    if pos >= len(options) or options[pos]['kind'] != 'engine_action':
                        raise ValueError('action_inventory_not_observed')
                    options[pos].update(proposal=copy.deepcopy(proposal), validation_scope=proposal_scope,
                        evidence_level='known_constraints_verified')
                    options[pos]['sources'].append(label); source['constructed_options'] += 1
                    continue
            options.append(option); source['constructed_options'] += 1

    version = _version(params)
    if version is not None:
        report = enumerate_known_candidates(state, source_snapshot_ref=ref, limit=limit, version=version)
        label = 'known_candidates_v' + str(version)
        if version == 6:
            include(report['cast_members'], label + '.cast_members')
            include(report['activate_payment'], label + '.activate_payment', relation=True)
        else:
            include(report, label)
    else:
        result['unresolved'].append({'evidence_level': 'unsupported', 'reason': 'reviewed_request_parameters_not_observed'})
    result['options'] = options[:limit]
    coverage.update(returned_options=len(result['options']),
        reviewed_candidate_count=sum(o['evidence_level'] == 'known_constraints_verified' for o in result['options']),
        omitted_constructed_options=max(0, len(options)-limit),
        truncated=len(options)>limit or any(s['truncated'] for s in sources))
    for source in sources:
        source['returned_options'] = sum(source['source'] in o['sources'] for o in result['options'])
        source['omitted_constructed_options'] = source['constructed_options']-source['returned_options']
    if not options and not params and not ac['inventory_integrity_verified']:
        result['status'] = 'unsupported'
    _bounded_json(result)
    return result


def assess_current_decision_options(consumer, *, limit=MAX_OPTIONS):
    """Owner-thread current/ref/lease gate, one bounded cached collection per ref.

    Cache is data only. Every read rechecks currentness, including cache hits;
    the Consumer clears it on invalidation. Returned dictionaries are detached.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_OPTIONS:
        raise ValueError('invalid_current_decision_options_limit')
    def evaluate(state, *, source_snapshot_ref):
        key = (source_snapshot_ref, limit)
        cached = consumer._decision_options_cache
        if cached is not None and cached[0] == key:
            return copy.deepcopy(cached[1])
        try:
            result = _build(state, source_snapshot_ref, limit)
        except (ValueError, TypeError, KeyError, IndexError, StopIteration, RecursionError, UnicodeError, OverflowError):
            return _unknown('current_options_evidence_invalid_or_output_limit')
        consumer._decision_options_cache = (copy.deepcopy(key), copy.deepcopy(result))
        return result
    if not isinstance(consumer, DecisionConsumer): return _unknown('requires_current_consumer')
    result = _assess_current_report(consumer, evaluate, _unknown)
    if result['source_snapshot_ref'] is None:
        consumer._decision_options_cache = None
    return result
