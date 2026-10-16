"""One finite Activate proposal slice. No complete cost or rules claim.

Projection visits every current active row before any response exists. Opaque
rows retain their positions, identities and parameter shapes, not their values.
Only the existing reducer supplies authenticated, visibility-filtered sources.
"""
import copy

from .raw_log import _id, _frontier_row, _OBSERVED_ACTION_TYPES
from .semantic_samples import _need, _keys, SampleError, IDS, BOOLS, PARAMS

REQUEST_VERSION = 'mtgaplayer.request-parameters.v2'
PROFILE = 'partial_public_activate_mana_literals'
SCOPE = 'offered_activate_source_ability_and_generic_two_predictive_payment'
ABILITY = ('verified_observed_pair', 'observed_group_contradiction', 'insufficient_evidence')
VERSION = 'mtgaplayer.semantic-samples.v5'


def action(row, refs, scope):
    """The reviewed cost identifier has the ability-group namespace."""
    from .semantic_targets import action as target_action
    _need(type(row) is dict and row.get('actionType') in
          ('ActionType_Activate', 'ActionType_Activate_Mana'), 'request_unsupported')
    _need('targets' not in row or row['targets'] == [], 'request_unsupported')
    return target_action(row, refs, scope)


def raw_action(value):
    _keys(value, ('action_type', 'identifier_refs', 'flags', 'observed_empty_parameters', 'parameters'))
    ids, flags, empty, params = (value[k] for k in
        ('identifier_refs', 'flags', 'observed_empty_parameters', 'parameters'))
    _need(type(ids) is dict and not set(ids)-set(IDS) and
          type(flags) is dict and not set(flags)-set(BOOLS) and
          type(empty) is list and len(empty) == len(set(empty)) and
          all(type(k) is str and k in PARAMS for k in empty) and
          type(params) is dict and not set(params)-set(PARAMS) and not set(empty)&set(params))
    raw = {'actionType': value['action_type'], **ids, **flags, **copy.deepcopy(params)}
    for key in empty:
        raw[key] = {'autoTapActions': []} if key == 'autoTapSolution' else []
    return raw


def check_action(value):
    from .request_parameters import LiteralRefs
    _need(action(raw_action(value), LiteralRefs(), ()) == value)


def _base(raw, refs, scope):
    _need(type(raw) is dict and raw.get('actionType') in _OBSERVED_ACTION_TYPES)
    _need(all(_id(raw[k]) for k in IDS if k in raw) and
          all(type(raw[k]) is bool for k in BOOLS if k in raw))
    kind = raw['actionType']
    required = {'instanceId', 'grpId', 'facetId'}
    if kind in ('ActionType_Activate', 'ActionType_Activate_Mana'):
        required.update(('abilityGrpId', 'uniqueAbilityId'))
    if kind in ('ActionType_Pass', 'ActionType_FloatMana'):
        _need(not set(raw)&set(IDS))
    else:
        _need(required <= raw.keys())
    return {'action_type': kind,
        'identifier_refs': {k: refs.ref('object' if k == 'instanceId' else k, scope, raw[k])
                            for k in IDS if k in raw},
        'flags': {k: raw[k] for k in BOOLS if k in raw}}


def ability_observation(raw, pairs):
    """Inspect the complete current list; absence never proves no other costs."""
    if type(pairs) is not list or len(pairs) > 256:
        return 'insufficient_evidence'
    if any(type(p) is not dict or set(p) != {'id', 'grpId'} or
           not _id(p['id']) or not _id(p['grpId']) for p in pairs):
        return 'insufficient_evidence'
    hits = [p for p in pairs if p['id'] == raw['uniqueAbilityId']]
    if len(hits) != 1:
        return 'insufficient_evidence'
    return ('verified_observed_pair' if hits[0]['grpId'] == raw['abilityGrpId'] else
            'observed_group_contradiction')


def project(message, visible, seat, source_abilities):
    from .request_parameters import LiteralRefs, _visible_references
    _need(type(message) is dict and not set(message)-{'type', 'systemSeatIds', 'msgId',
        'gameStateId', 'prompt', 'actionsAvailableReq'} and
        message.get('type') == 'GREMessageType_ActionsAvailableReq')
    body = message.get('actionsAvailableReq')
    _need(type(body) is dict and not set(body)-{'actions', 'inactiveActions'})
    actions = body.get('actions')
    _need(type(actions) is list and len(actions) <= 256 and
          any(type(r) is dict and r.get('actionType') == 'ActionType_Activate' for r in actions))
    objects = {o['instance_id']: o for o in visible}
    _need(len(objects) == len(visible))
    result = []
    for position, raw in enumerate(actions):
        base = _base(raw, LiteralRefs(), ())
        source = base['identifier_refs'].get('instanceId')
        if source is not None:
            _need(source in objects)
        shape = _frontier_row(position, base['action_type'], raw)
        row = {'list_position': position, **base,
            'parameter_shapes': shape['known_parameter_shapes'],
            'other_fields_present': shape['other_top_level_fields_present'],
            'literal_action': None, 'ability_binding': None}
        if base['action_type'] in ('ActionType_Activate', 'ActionType_Activate_Mana'):
            try:
                literal = action(raw, LiteralRefs(), ())
                _need(_visible_references(literal, visible))
            except (ValueError, TypeError, KeyError):
                pass
            else:
                row['literal_action'] = literal
                if base['action_type'] == 'ActionType_Activate':
                    obj = objects[source]
                    row['ability_binding'] = (ability_observation(raw, source_abilities.get(source))
                        if obj.get('zone') == 'ZoneType_Battlefield' and
                           obj.get('controller_seat') == seat else 'insufficient_evidence')
        result.append(row)
    _need(any(r['action_type'] == 'ActionType_Activate' and r['literal_action'] is not None for r in result))
    return {'profile': PROFILE, 'rows': result}


def check_rows(rows, visible, *, portable=False):
    from .request_parameters import LiteralRefs, _visible_references
    _need(type(rows) is list and len(rows) <= 256)
    objects = {o['instance_id']: o for o in visible}
    _need(len(objects) == len(visible))
    for position, row in enumerate(rows):
        _keys(row, ('list_position', 'action_type', 'identifier_refs', 'flags', 'parameter_shapes',
                    'other_fields_present', 'literal_action', 'ability_binding'))
        _need(type(row['list_position']) is int and row['list_position'] == position and
              type(row['identifier_refs']) is dict and not set(row['identifier_refs'])-set(IDS) and
              type(row['flags']) is dict and not set(row['flags'])-set(BOOLS))
        raw = {'actionType': row['action_type'], **row['identifier_refs'], **row['flags']}
        base = _base(raw, LiteralRefs(), ())
        _need(all(base[k] == row[k] for k in base))
        source = row['identifier_refs'].get('instanceId')
        _need(source is None or source in objects)
        shapes = row['parameter_shapes']
        _need(type(shapes) is dict and not set(shapes)-set(PARAMS) and type(row['other_fields_present']) is bool)
        for key, shape in shapes.items():
            count_key = 'auto_tap_actions_count' if key == 'autoTapSolution' else 'element_count'
            _keys(shape, ('kind', count_key))
            _need(shape['kind'] in ('object' if key == 'autoTapSolution' else 'array', 'unexpected'))
            count = shape[count_key]
            _need(count is None or type(count) is int and 0 <= count <= 1000000)
        literal = row['literal_action']
        if literal is None:
            _need(row['ability_binding'] is None)
            continue
        check_action(literal)
        _need(not row['other_fields_present'] and
              all(literal[k] == row[k] for k in ('action_type', 'identifier_refs', 'flags')))
        observed = _frontier_row(position, row['action_type'], raw_action(literal))['known_parameter_shapes']
        _need(observed == shapes)
        if not portable:
            _need(_visible_references(literal, visible))
        else:
            pending = [literal['parameters']]
            while pending:
                item = pending.pop()
                if type(item) is list: pending.extend(item)
                elif type(item) is dict:
                    for key, child in item.items():
                        if key in ('instanceId', 'srcInstanceId'): _need(child in objects)
                        pending.append(child)
        _need(row['ability_binding'] in ABILITY if row['action_type'] == 'ActionType_Activate' else
              row['ability_binding'] is None)


def check_payment(rows, chosen, visible, seat, position):
    """Check the offered Generic2/two predictive-one route, not all payments."""
    unknown, bad, good = 'insufficient_evidence', 'violated_known_constraints', 'verified_known_constraints'
    checks = {k: unknown for k in ('source_identity', 'ability_identity', 'declared_mana', 'predictive_payment')}
    row = rows[position]; offered = row['literal_action']
    if offered is None or row['action_type'] != 'ActionType_Activate':
        return unknown, 'activate_row_profile_not_supported', checks
    objects = {o['instance_id']: o for o in visible}; ids = chosen['identifier_refs']
    source = objects.get(ids['instanceId'])
    if (source is None or source['zone'] != 'ZoneType_Battlefield' or source['controller_seat'] != seat):
        return unknown, 'activate_source_not_verified', checks
    checks['source_identity'] = good
    checks['ability_identity'] = {'verified_observed_pair': good, 'observed_group_contradiction': bad,
                                 'insufficient_evidence': unknown}[row['ability_binding']]
    if checks['ability_identity'] == bad:
        return bad, 'current_source_ability_group_contradicted', checks
    for a in (offered, chosen):
        if not {'manaCost', 'autoTapSolution'} <= set(a['parameters']) | set(a['observed_empty_parameters']):
            return unknown, 'required_mana_parameters_not_observed', checks
    if any(offered['parameters'].get(k) != chosen['parameters'].get(k) or
           (k in offered['observed_empty_parameters']) != (k in chosen['observed_empty_parameters'])
           for k in ('manaCost', 'autoTapSolution')):
        return unknown, 'alternative_payment_path_not_supported', checks
    cost = chosen['parameters'].get('manaCost'); tap = chosen['parameters'].get('autoTapSolution')
    if cost and any('abilityGrpId' in c and c['abilityGrpId'] != ids['abilityGrpId'] for c in cost):
        checks['declared_mana'] = bad
        return bad, 'cost_ability_group_contradicted', checks
    if cost != [{'color': ['ManaColor_Generic'], 'count': 2, 'abilityGrpId': ids['abilityGrpId']}]:
        return unknown, 'activate_mana_profile_not_supported', checks
    checks['declared_mana'] = good
    if tap is None or len(tap['autoTapActions']) != 2:
        return unknown, 'activate_mana_profile_not_supported', checks
    taps = tap['autoTapActions']
    if len({t['instanceId'] for t in taps}) != 2:
        return unknown, 'distinct_payment_sources_not_observed', checks
    for payment in taps:
        mana = payment['manaPaymentOption']['mana']
        if len(mana) != 1 or mana[0]['count'] != 1:
            return unknown, 'activate_mana_profile_not_supported', checks
        m = mana[0]
        if m['srcInstanceId'] != payment['instanceId'] or m['abilityGrpId'] != payment['abilityGrpId']:
            checks['predictive_payment'] = bad
            return bad, 'observed_predictive_payment_relation_contradicted', checks
        matches = [r for r in rows if r['action_type'] == 'ActionType_Activate_Mana' and
                   r['identifier_refs']['instanceId'] == payment['instanceId'] and
                   r['identifier_refs']['abilityGrpId'] == payment['abilityGrpId']]
        if len(matches) != 1 or matches[0]['literal_action'] is None:
            return unknown, 'unique_active_mana_relation_not_observed', checks
        params = matches[0]['literal_action']['parameters']
        if 'manaPaymentOptions' not in params or 'manaSelections' not in params:
            return unknown, 'required_mana_parameters_not_observed', checks
        expected = {'instanceId': payment['instanceId'], 'abilityGrpId': payment['abilityGrpId'],
                    'options': [{'mana': [{'color': m['color'], 'count': 1}]}]}
        if payment['manaPaymentOption'] not in params['manaPaymentOptions'] or expected not in params['manaSelections']:
            checks['predictive_payment'] = bad
            return bad, 'observed_predictive_payment_relation_contradicted', checks
        obj = objects.get(payment['instanceId'])
        if obj is None or obj['zone'] != 'ZoneType_Battlefield' or obj['controller_seat'] != seat:
            return unknown, 'visible_payment_source_not_verified', checks
    # The two explicit units must also be distinct in this request's mana
    # namespace. Distinct battlefield sources alone cannot prove that a
    # predictive mana unit was not reused under two source descriptors.
    unit_refs = [payment['manaPaymentOption']['mana'][0]['manaId'] for payment in taps]
    if len(set(unit_refs)) != len(unit_refs):
        return unknown, 'distinct_mana_units_not_observed', checks
    checks['predictive_payment'] = good
    if checks['ability_identity'] != good:
        return unknown, 'current_source_unique_ability_pair_not_observed', checks
    return good, 'offered_activate_slice_consistent', checks


def alias_rows(rows, refs, scope):
    result = copy.deepcopy(rows)
    for row in result:
        ids = row['identifier_refs']
        row['identifier_refs'] = {k: refs.ref('object' if k == 'instanceId' else k, scope, v)
                                  for k, v in ids.items()}
        if row['literal_action'] is not None:
            row['literal_action'] = action(raw_action(row['literal_action']), refs, scope)
    return result


def projection():
    from .semantic_cast import PROJECTION_V2
    return {**copy.deepcopy(PROJECTION_V2),
        'nonempty_action_parameters': 'partial_activate_literals_other_rows_opaque',
        'trace_annotations': 'matching_public_source_and_ability_group_subset',
        'unique_ability_continuation_verified': False}


def _snapshot_objects(snapshot):
    return {o['object_ref']: o for o in snapshot['objects']}


def _visible(snapshot):
    return [{'instance_id': o['object_ref'], 'card_id': o['card_id'], 'zone': o['zone'],
             'controller_seat': o['controller']} for o in snapshot['objects']]


def facts(gs, reducer, refs, scope, previous, current, selected, prior_facts):
    """Public source/ability-group association, never unique-ID continuation."""
    from .semantic_cast import _detail
    before, after = _snapshot_objects(previous), _snapshot_objects(current)
    source = selected['identifier_refs']['instanceId']; group = selected['identifier_refs']['abilityGrpId']
    payments = {t['instanceId'] for t in selected['parameters'].get('autoTapSolution', {}).get('autoTapActions', [])}
    existing = {f['ability_object_ref'] for f in prior_facts if f['kind'] == 'ability_created'}
    # Only already admitted public Stack endpoints can supply parent/group facts.
    candidates = []
    for raw in reducer.document()['current']['objects']:
        obj = refs.ref('object', scope, raw['id'])
        if obj not in after or obj in before or after[obj]['zone'] != 'ZoneType_Stack': continue
        row = reducer.objects[raw['id']]
        if (row.get('type') == 'GameObjectType_Ability' and row.get('visibility') == 'Visibility_Public' and
                _id(row.get('parentId')) and _id(row.get('grpId')) and
                refs.ref('object', scope, row['parentId']) == source and
                refs.ref('abilityGrpId', scope, row['grpId']) == group):
            candidates.append(obj)
    result = []; omitted = 0; unsupported = False
    annotations = gs.get('annotations', [])
    if type(annotations) is not list or len(annotations) > 512:
        return [], 'unsupported_relevant_annotation', 0
    recognized = {'AnnotationType_AbilityInstanceCreated', 'AnnotationType_ManaPaid',
                  'AnnotationType_ResolutionStart', 'AnnotationType_ResolutionComplete',
                  'AnnotationType_AbilityInstanceDeleted'}
    for ann in annotations:
        try:
            typ = ann.get('type') if type(ann) is dict else None
            if type(typ) is not list or len(typ) != 1 or typ[0] not in recognized:
                omitted += 1; continue
            affected = ann.get('affectedIds'); affector = ann.get('affectorId')
            _need(type(affected) is list and len(affected) == 1 and _id(affected[0]) and _id(affector))
            obj, actor = refs.ref('object', scope, affected[0]), refs.ref('object', scope, affector)
            if obj not in set(candidates)|existing and actor != source:
                omitted += 1; continue
            _need(_id(ann.get('id')))
            if typ[0] == 'AnnotationType_AbilityInstanceCreated':
                _keys(ann, ('id', 'affectorId', 'affectedIds', 'type', 'details'))
                detail = _detail(ann); _keys(detail, ('source_zone',))
                _need(_id(detail['source_zone']))
                if (len(candidates) != 1 or obj != candidates[0] or actor != source or
                        reducer.zones.get(detail['source_zone'], {}).get('type') != 'ZoneType_Battlefield'):
                    omitted += 1; continue
                result.append({'kind': 'ability_created', 'source_object_ref': source,
                    'ability_object_ref': obj, 'ability_grp_ref': group})
                existing.add(obj)
            elif typ[0] == 'AnnotationType_ManaPaid':
                _keys(ann, ('id', 'affectorId', 'affectedIds', 'type', 'details'))
                detail = _detail(ann); _keys(detail, ('id', 'color'))
                _need(all(_id(v) for v in detail.values()))
                if obj not in existing or obj not in after or actor not in payments or actor not in before:
                    omitted += 1; continue
                result.append({'kind': 'mana_paid', 'source_object_ref': actor, 'ability_object_ref': obj})
            elif typ[0] in ('AnnotationType_ResolutionStart', 'AnnotationType_ResolutionComplete'):
                _keys(ann, ('id', 'affectorId', 'affectedIds', 'type', 'details'))
                detail = _detail(ann); _keys(detail, ('grpid',)); _need(_id(detail['grpid']))
                if (obj not in existing or actor != obj or obj not in before or
                        refs.ref('abilityGrpId', scope, detail['grpid']) != group):
                    omitted += 1; continue
                result.append({'kind': 'resolution_start' if typ[0].endswith('Start') else 'resolution_complete',
                    'ability_object_ref': obj, 'ability_grp_ref': group})
            else:
                _keys(ann, ('id', 'affectorId', 'affectedIds', 'type'))
                if (obj not in existing or actor != source or obj not in before or obj in after or
                        affected[0] not in gs.get('diffDeletedInstanceIds', [])):
                    omitted += 1; continue
                result.append({'kind': 'ability_deleted', 'source_object_ref': source, 'ability_object_ref': obj})
        except (ValueError, KeyError, TypeError):
            unsupported = True; omitted += 1
    return result, 'unsupported_relevant_annotation' if unsupported else 'reviewed_activate_subset', omitted


def check_trace(trace, before, selected):
    from .semantic_cast import TRACE_ENDS, TRACE_LIMIT
    from .semantic_samples import _check_snapshot
    _keys(trace, ('status', 'truncated', 'next_request_ref', 'states'))
    _need(trace['status'] in TRACE_ENDS and type(trace['truncated']) is bool and
          trace['truncated'] == (trace['status'] == 'limit_reached') and
          type(trace['states']) is list and len(trace['states']) <= TRACE_LIMIT)
    _need((_id(trace['next_request_ref']) and trace['next_request_ref'] > 0)
          if trace['status'] == 'next_request_observed' else trace['next_request_ref'] is None)
    source = selected['identifier_refs']['instanceId']; group = selected['identifier_refs']['abilityGrpId']
    payments = {t['instanceId'] for t in selected['parameters'].get('autoTapSolution', {}).get('autoTapActions', [])}
    previous = before; seen = {before['state_ref']}; ability = None
    for row in trace['states']:
        _keys(row, ('snapshot', 'previous_state_ref', 'facts', 'facts_status', 'omitted_annotations'))
        current = row['snapshot']; _check_snapshot(current)
        _need(row['previous_state_ref'] == previous['state_ref'] and type(row['previous_state_ref']) is int and
              current['state_ref'] not in seen and row['facts_status'] in
              ('reviewed_activate_subset', 'unsupported_relevant_annotation') and
              _id(row['omitted_annotations']) and type(row['facts']) is list and len(row['facts']) <= 512)
        seen.add(current['state_ref']); old, new = _snapshot_objects(previous), _snapshot_objects(current)
        for fact in row['facts']:
            _need(type(fact) is dict)
            kind = fact.get('kind')
            fields = {'ability_created': ('source_object_ref', 'ability_object_ref', 'ability_grp_ref'),
                'mana_paid': ('source_object_ref', 'ability_object_ref'),
                'resolution_start': ('ability_object_ref', 'ability_grp_ref'),
                'resolution_complete': ('ability_object_ref', 'ability_grp_ref'),
                'ability_deleted': ('source_object_ref', 'ability_object_ref')}
            _need(kind in fields); _keys(fact, ('kind', *fields[kind]))
            _need(all(_id(fact[k]) and fact[k] > 0 for k in fields[kind]))
            obj = fact['ability_object_ref']
            if kind == 'ability_created':
                _need(ability is None and fact['source_object_ref'] == source and fact['ability_grp_ref'] == group and
                      source in old and old[source]['zone'] == 'ZoneType_Battlefield' and
                      obj not in old and obj in new and new[obj]['zone'] == 'ZoneType_Stack' and
                      new[obj]['card_id'] is None)
                ability = obj
            else:
                _need(obj == ability)
                _need(all(objects[obj]['card_id'] is None for objects in (old, new) if obj in objects))
                if kind == 'mana_paid':
                    _need(fact['source_object_ref'] in payments and fact['source_object_ref'] in old and obj in new)
                elif kind == 'ability_deleted':
                    _need(fact['source_object_ref'] == source and obj in old and obj not in new)
                else:
                    _need(fact['ability_grp_ref'] == group and obj in old and old[obj]['zone'] == 'ZoneType_Stack')
        previous = current
    if trace['status'] == 'not_observed': _need(not trace['states'])


def replay(document):
    from .semantic_samples import _check_envelope, _check_episode_base, _check_successor
    from .decision_consumer import EXECUTION
    _check_envelope(document, VERSION, projection())
    reports = []
    for index, sample in enumerate(document['samples']):
        _check_episode_base(sample, ('trace',))
        _keys(sample['request'], ('kind', 'payload')); _keys(sample['response'], ('kind', 'payload'))
        _need(sample['request']['kind'] == sample['response']['kind'] == 'actions_available')
        req = sample['request']['payload']; _keys(req, ('profile', 'rows')); _need(req['profile'] == PROFILE)
        visible = _visible(sample['before']); check_rows(req['rows'], visible, portable=True)
        response = sample['response']['payload']; _keys(response, ('action', 'auto_pass_priority'))
        _need(response['auto_pass_priority'] == 'AutoPassPriority_Yes'); chosen = response['action']; check_action(chosen)
        _need(chosen['action_type'] == 'ActionType_Activate')
        matches = [r['list_position'] for r in req['rows'] if r['action_type'] == chosen['action_type'] and
                   r['identifier_refs'] == chosen['identifier_refs']]
        position = matches[0] if len(matches) == 1 else None
        _need(position is not None and req['rows'][position]['literal_action'] == chosen)
        status, reason, checks = check_payment(req['rows'], chosen, visible, sample['identity']['self_seat'], position)
        _check_successor(sample['successor'], sample['before']); check_trace(sample['trace'], sample['before'], chosen)
        trace, successor = sample['trace'], sample['successor']
        if trace['states']:
            _need(successor['status'] == 'continuous_state_observed' and successor['snapshot'] == trace['states'][0]['snapshot'])
        elif trace['status'] == 'next_request_observed':
            _need(successor['status'] == 'next_request_observed' and successor['request_ref'] == trace['next_request_ref'] and
                  successor['snapshot'] == sample['before'])
        else:
            _need(successor['status'] == {'interrupted': 'interrupted',
                'full_baseline_not_continuous': 'full_baseline_not_continuous'}.get(trace['status'], 'not_observed'))
        fs = [f for row in trace['states'] if row['facts_status'] == 'reviewed_activate_subset' for f in row['facts']]
        created = [f['ability_object_ref'] for f in fs if f['kind'] == 'ability_created']
        ability = created[0] if len(created) == 1 else None
        payments = {t['instanceId'] for t in chosen['parameters'].get('autoTapSolution', {}).get('autoTapActions', [])}
        paid = {f['source_object_ref'] for f in fs if f['kind'] == 'mana_paid' and f['ability_object_ref'] == ability}
        tapped = any(all(_snapshot_objects(row['snapshot']).get(p, {}).get('tapped') is True for p in payments)
                     for row in trace['states']) if payments else False
        resolved = ability is not None and all(any(f['kind'] == k and f['ability_object_ref'] == ability for f in fs)
            for k in ('resolution_start', 'resolution_complete'))
        deleted = ability is not None and any(f['kind'] == 'ability_deleted' and f['ability_object_ref'] == ability for f in fs)
        reports.append({'sample_index': index, 'request_kind': 'actions_available', 'selected_action_position': position,
            'successor_status': successor['status'], 'trace_status': trace['status'],
            'activate_evidence': {'validation_scope': SCOPE, 'known_constraints': status, 'reason': reason,
                'known_checks': checks, 'activation_submission_observed': True,
                'matching_source_group_stack_ability_observed': ability is not None,
                'payment_sources_to_ability_observed': bool(payments) and paid == payments,
                'payment_sources_tapped_observed': tapped,
                'matching_ability_resolution_observed': resolved, 'matching_ability_deleted_observed': deleted,
                'public_stack_empty_verified': False,
                'unique_ability_continuation_verified': False, 'complete_costs_verified': False,
                'additional_costs': 'unknown', 'future_parameters': 'unknown',
                'complete_legality_verified': False, 'server_acceptance_verified': False}})
    return {'schema_version': 'mtgaplayer.semantic-sample-replay.v5', 'samples': reports,
        'artifact_checks_passed': True, 'raw_source_auth_revalidated': False,
        'complete_legality_verified': False, 'server_acceptance_verified': False,
        'read_only': True, 'execution': dict(EXECUTION)}
