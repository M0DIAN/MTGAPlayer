"""Opt-in assembly of already checked current evidence, never a future plan.

No parser, generator or rule checker lives here. MP65 supplies its checked
inventory/probes; request parameters and continuation sidecars were checked by
the same State validator. Positions join these views within one snapshot only.
"""
import copy

from .decision_consumer import EXECUTION
from .cast_target_members import _equal

VERSION = 'mtgaplayer.finite-action-intents.v1'
COMPLEX = ('ActionType_Cast', 'ActionType_Activate')
UNKNOWN = ('complete_target_constraints_unknown', 'complete_payment_unknown',
           'additional_costs_modes_x_unknown', 'dynamic_effects_unknown',
           'complete_legality_unknown', 'tactical_value_unknown',
           'response_encoding_unknown', 'server_acceptance_unknown')


def empty(reason):
    return {'schema_version': VERSION, 'status': 'insufficient_evidence', 'reason': reason,
        'request_binding': None, 'source_snapshot_ref': None, 'intents': [],
        'coverage': {'unit': 'parent_action_rows; current_child_stages_counted_separately',
            'observed_complex_action_rows': None, 'returned_parent_rows': 0,
            'reviewed_target_rows': 0, 'predictive_payment_association_rows': 0,
            'finite_stage_intent_rows': 0, 'current_child_stage_intents': 0, 'omitted_parent_rows': None,
            'full_legal_complex_actions': None},
        'complete_legality_verified': False, 'read_only': True, **EXECUTION}


def _base(binding, ref):
    return {'request_binding': copy.deepcopy(binding), 'source_snapshot_ref': copy.deepcopy(ref),
        'finite_stage_intent_structure_verified': False,
        'complete_action_proposal_verified': False, 'complete_legality_verified': False,
        'payment_legality_verified': False, 'target_combination_legality_verified': False,
        'response_encoding_verified': False, 'execution_ready': False,
        'unresolved': list(UNKNOWN), 'read_only': True, **EXECUTION}


def _witness(witness, descriptor, family):
    """Identity join only; the existing generator already checked the route."""
    position = witness['list_position']
    if type(position) is not int or not 0 <= position < len(family['rows']):
        raise ValueError('intent_payment_row_missing')
    row = family['rows'][position]
    if (row['action_type'] != 'ActionType_Activate_Mana' or
            not _equal(witness['identifier_refs'], row['identifier_refs']) or
            not _equal(witness['flags'], row['flags']) or
            not _equal(descriptor['instanceId'], row['identifier_refs']['instanceId']) or
            not _equal(descriptor['abilityGrpId'], row['identifier_refs']['abilityGrpId'])):
        raise ValueError('intent_payment_identity_mismatch')


def _parent_intents(state, options, retained):
    from .cast_activate_associations import cast_family, activate_family
    from .multi_slot_cast import FIELD as MULTI
    params = state['legal_action_space']['request_parameters']
    graph = state['legal_action_space']['choice_graph']
    nodes = {n['action_key']['list_position']: n for n in graph['action_nodes']} if graph else {}
    families = (cast_family(params), activate_family(params))
    literals = {}
    for family, key in zip(families, ('cast_actions', 'target_actions')):
        for item in (family or {}).get(key, []):
            literals[item['list_position']] = (item['action'], family)
    returned_probes = [o for o in options['options'] if o['kind'] == 'parent_cast_member_probe']
    relations = [o for o in options['options'] if o['kind'] == 'activate_target_payment_association']
    complete = not options['coverage']['truncated']
    result = []
    for option in options['options']:
        observation = option['observation']
        if option['kind'] != 'engine_action' or observation['engine_action_type'] not in COMPLEX:
            continue
        position = option['list_position']; literal, family = literals.get(position, (None, None))
        intent = _base(options['request_binding'], options['source_snapshot_ref'])
        intent.update(stage='current_parent_action', action_type=observation['engine_action_type'],
            list_position=position, action_key=copy.deepcopy(nodes[position]['action_key']),
            action_identity=copy.deepcopy(nodes[position]['action_identity']),
            option_keys=[copy.deepcopy(option['option_key'])], current=True,
            action_literal=copy.deepcopy(literal), target_slots=None,
            reviewed_target_members=[], predictive_payment_witnesses=[],
            observed_mana_cost=None, auto_tap_solution_observed=None,
            target_members_reviewed=False, predictive_payment_association_verified=False,
            successor_stage_status='unknown_not_yet_observed', historical_parent=None)
        if literal is not None:
            if literal['action_type'] != intent['action_type']:
                raise ValueError('intent_action_type_mismatch')
            parameters = literal['parameters']
            intent['observed_mana_cost'] = copy.deepcopy(parameters.get('manaCost'))
            intent['auto_tap_solution_observed'] = 'autoTapSolution' in parameters
            intent['target_slots'] = [{'slot_position': i, 'target_idx': slot['targetIdx'],
                'provided_object_refs': [entry['targetInstanceId'] for entry in slot['targets']],
                'minimum': None, 'maximum': None, 'selected_count': None}
                for i, slot in enumerate(parameters.get('targets', []))]
        elif MULTI in observation:
            multi = observation[MULTI]
            intent.update(action_literal=copy.deepcopy(multi['action_literal']),
                target_slots=copy.deepcopy(multi['slots']),
                observed_mana_cost=copy.deepcopy(multi['action_literal']['parameters'].get('manaCost')),
                auto_tap_solution_observed=False)
        if literal is not None and intent['action_type'] == 'ActionType_Cast':
            probes = [o for o in returned_probes if o['list_position'] == position]
            selected = [item for item in retained if item['proposal']['list_position'] == position]
            if len(probes) != len(selected):
                # A truncated MP65 view cannot be expanded through retained data.
                selected = []
            for item, probe in zip(selected, probes):
                proposal = item['proposal']; member = proposal['proposed_cast_target_member']
                if (not _equal(item['action_key'], intent['action_key']) or
                        not _equal(proposal, probe['proposal']) or
                        not _equal(member['identifier_refs'], literal['identifier_refs']) or
                        not _equal(member['flags'], literal['flags']) or
                        len(intent['target_slots']) != 1 or
                        not _equal(member['target_idx'], intent['target_slots'][0]['target_idx']) or
                        member['object_ref'] not in intent['target_slots'][0]['provided_object_refs']):
                    raise ValueError('intent_cast_probe_identity_mismatch')
                witness = item['payment_witness']
                descriptors = literal['parameters']['autoTapSolution']['autoTapActions']
                if len(descriptors) != 1 or not _equal(witness['predictive_payment'], descriptors[0]):
                    raise ValueError('intent_cast_payment_mismatch')
                _witness(witness, descriptors[0], family)
                intent['reviewed_target_members'].append(copy.deepcopy(member))
                intent['option_keys'].append(copy.deepcopy(probe['option_key']))
                if not intent['predictive_payment_witnesses']:
                    intent['predictive_payment_witnesses'].append(copy.deepcopy(witness))
                elif not _equal(intent['predictive_payment_witnesses'][0], witness):
                    raise ValueError('intent_cast_payment_disagreement')
        elif literal is not None:
            matches = [o for o in relations if o['list_position'] == position]
            if len(matches) > 1: raise ValueError('intent_ambiguous_activate_relation')
            for relation in matches:
                value = relation['observation']; member = value['target_member']
                if (not _equal(value['action_identifier_refs'], literal['identifier_refs']) or
                        not _equal(value['action_flags'], literal['flags']) or
                        len(intent['target_slots']) != 1 or
                        not _equal(member['target_idx'], intent['target_slots'][0]['target_idx']) or
                        member['object_ref'] not in intent['target_slots'][0]['provided_object_refs']):
                    raise ValueError('intent_activate_identity_mismatch')
                witnesses = value['mana_row_witnesses']
                descriptors = literal['parameters']['autoTapSolution']['autoTapActions']
                if len(witnesses) != len(descriptors): raise ValueError('intent_payment_count_mismatch')
                for witness, descriptor in zip(witnesses, descriptors):
                    _witness(witness, descriptor, family)
                intent['reviewed_target_members'] = [copy.deepcopy(member)]
                intent['predictive_payment_witnesses'] = copy.deepcopy(witnesses)
                intent['option_keys'].append(copy.deepcopy(relation['option_key']))
        members = intent['reviewed_target_members']
        intent['target_members_reviewed'] = bool(members)
        intent['predictive_payment_association_verified'] = bool(intent['predictive_payment_witnesses'])
        intent['finite_stage_intent_structure_verified'] = complete and bool(members) and bool(intent['predictive_payment_witnesses'])
        result.append(intent)
    return result


def assemble(state, options, retained):
    """Called inside MP65's before/after Consumer gate; no new state or lease."""
    report = empty(options['reason'])
    if options['request_binding'] is None: return report
    report.update(status='partial', reason='finite_current_stage_evidence_only',
        request_binding=copy.deepcopy(options['request_binding']),
        source_snapshot_ref=copy.deepcopy(options['source_snapshot_ref']))
    parent_request = options['request_binding']['request_type'] == 'GREMessageType_ActionsAvailableReq'
    if parent_request:
        report['intents'] = _parent_intents(state, options, retained)
        # Count the authenticated inventory, including rows omitted by the opt-in budget.
        # Reuse the already collected inventory count below; do not run Advisor again.
        frontier = state['legal_action_space']['immediate_frontier']
        templates = frontier['projection']['templates']
        observed = (sum(t['engine_action_type'] in COMPLEX for t in templates)
            if options['coverage']['engine_offered_count'] is not None else None)
        report['coverage'].update(observed_complex_action_rows=observed,
            returned_parent_rows=len(report['intents']),
            omitted_parent_rows=observed-len(report['intents']) if observed is not None else None)
    elif options['continuation_context'] is not None:
        context = options['continuation_context']; field = context['field']; sidecar = state[field]
        parent = sidecar['first_child']['parent'] if field == 'revised_choice_continuation' else sidecar['parent']
        intent = _base(options['request_binding'], options['source_snapshot_ref'])
        intent.update(stage='current_revised_target_request' if field == 'revised_choice_continuation' else 'current_target_request',
            current=True, action_type='ActionType_Cast' if field == 'cast_choice_continuation' else 'ActionType_Activate',
            list_position=None, action_key=None, action_literal=None,
            historical_parent=copy.deepcopy(parent), continuation_provenance=sidecar['schema_version'],
            target_constraints=copy.deepcopy(options['request_observation']['target_literals']),
            current_proposals=[{'option_key': copy.deepcopy(o['option_key']), 'kind': o['kind'],
                'proposal': copy.deepcopy(o['proposal'])} for o in options['options'] if o['proposal'] is not None],
            successor_stage_status='unknown_not_yet_observed')
        intent['finite_stage_intent_structure_verified'] = bool(intent['current_proposals']) and not options['coverage']['truncated']
        report['intents'] = [intent]
        report['coverage']['current_child_stage_intents'] = 1
    for intent in report['intents']:
        if intent['stage'] != 'current_parent_action': continue
        for name, key in (('reviewed_target_rows', 'target_members_reviewed'),
                          ('predictive_payment_association_rows', 'predictive_payment_association_verified'),
                          ('finite_stage_intent_rows', 'finite_stage_intent_structure_verified')):
            report['coverage'][name] += bool(intent.get(key))
    return report
