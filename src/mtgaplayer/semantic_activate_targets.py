"""Opt-in historical actual Activate -> single-slot targets -> public facts.

One reducer authenticates the private source. Portable replay checks the finite
exported relationships, never raw authentication, a new proposal or input.
"""
from collections import Counter
import copy
import json

from .raw_log import RawReducer, _id, _frontier_row, _OBSERVED_ACTION_TYPES
from .response_evidence import (_current_verified_request, _current_verified_raw_request,
                                _paired_response, _paired_terminal_submit)
from .semantic_samples import (_need, _keys, SampleError, _Refs, _snapshot, _scope,
    _check_snapshot, _check_envelope, _check_episode_base, _check_successor,
    _response, IDS, PARAMS, PROJECTION as BASE_PROJECTION, REASONS)
from .semantic_cast import RequestManaRefs, check_action
from . import semantic_activate as activate, semantic_targets as targets
from .decision_consumer import EXECUTION

VERSION = 'mtgaplayer.semantic-samples.v10'
PROFILE = 'historical_actual_activate_single_slot_public_chain'
LIMIT = 64
ENDS = ('eof', 'interrupted', 'full_baseline_not_continuous', 'limit_reached',
        'superseded_by_new_activate', 'explicit_ability_deleted')
PROJECTION = {**copy.deepcopy(BASE_PROJECTION),
    'state_fields': 'strict_public_battlefield_and_stack_no_catalog_identity',
    'nonempty_action_parameters': 'reviewed_actual_selected_row_only_other_positions_opaque',
    'targets': 'actual_single_slot_request_update_submit_and_explicit_public_facts',
    'raw_inventory_uniqueness': 'producer_attestation_not_portable_reauthentication',
    'action_target_highlight': 'presentation_value_omitted_after_exact_raw_row_match',
    'complete_legality_and_effect_causation': 'unverified'}


def _same(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def _positive(value):
    return _id(value) and value > 0


def _exact_selected_position(actions, selected):
    """One complete offered row AND one complete identity, before normalization."""
    _need(type(actions) is list and 1 <= len(actions) <= 256 and
          all(type(row) is dict for row in actions), 'request_unsupported')
    _need(type(selected) is dict and all(_id(selected.get(key)) for key in IDS), 'response_unsupported')
    identities = [i for i, row in enumerate(actions) if row.get('actionType') == 'ActionType_Activate' and
        all(_id(row.get(key)) and _same(row[key], selected[key]) for key in IDS)]
    full = [i for i, row in enumerate(actions) if _same(row, selected)]
    _need(len(full) == len(identities) == 1 and full == identities, 'response_unsupported')
    return full[0]


def _target_link_matches(request, selected, ability):
    """Shared observed source/group/slot join; not unique-ID or rules causation."""
    return (ability is not None and request['source_object_ref'] == ability and
        request['ability_grp_ref'] == selected['identifier_refs']['abilityGrpId'] and
        _same(request['target_idx'], selected['parameters']['targets'][0]['targetIdx']))


def _without_highlight(row):
    """The recaptured action adds the same presentation-only field as target requests."""
    result = copy.deepcopy(row)
    slots = result.get('targets')
    _need(type(slots) is list and len(slots) == 1, 'request_unsupported')
    _keys(slots[0], ('targetIdx', 'targets'))
    _need(type(slots[0]['targets']) is list and len(slots[0]['targets']) <= 256, 'request_unsupported')
    for entry in slots[0]['targets']:
        _need(type(entry) is dict and set(entry) in
              ({'targetInstanceId'}, {'targetInstanceId', 'highlight'}), 'request_unsupported')
        _need('highlight' not in entry or type(entry['highlight']) is str, 'request_unsupported')
        entry.pop('highlight', None)
    return result


def _objects(snapshot):
    return {obj['object_ref']: obj for obj in snapshot['objects']}


def _public(reducer, refs, scope):
    snapshot = _snapshot(reducer, refs, scope)
    admitted = set()
    for obj in reducer.document()['current']['objects']:
        raw = reducer.objects.get(obj['id'], {})
        if not _id(raw.get('zoneId')):
            continue
        zone = reducer.zones.get(raw['zoneId'], {})
        members = zone.get('objectInstanceIds')
        if (raw.get('visibility') == 'Visibility_Public' and
                zone.get('visibility') == 'Visibility_Public' and
                obj['zone'] in ('ZoneType_Battlefield', 'ZoneType_Stack') and
                zone.get('type') == obj['zone'] and type(members) is list and
                sum(_same(ident, obj['id']) for ident in members) == 1):
            admitted.add(refs.ref('object', scope, obj['id']))
    snapshot['objects'] = [{**obj, 'card_id': None} for obj in snapshot['objects']
                           if obj['object_ref'] in admitted]
    return snapshot


def _check_public(snapshot):
    _check_snapshot(snapshot)
    _need(all(obj['card_id'] is None and obj['zone'] in
              ('ZoneType_Battlefield', 'ZoneType_Stack') for obj in snapshot['objects']))


def _check_visible_action(action, snapshot, seat):
    check_action(action, target_actions=True)
    _need(action['action_type'] == 'ActionType_Activate' and
          set(action['identifier_refs']) == set(IDS))
    objects = _objects(snapshot)
    source = objects.get(action['identifier_refs']['instanceId'])
    _need(source is not None and source['zone'] == 'ZoneType_Battlefield' and source['controller'] == seat)
    slots = action['parameters'].get('targets')
    _need(type(slots) is list and len(slots) == 1 and slots[0]['targets'])
    _need(len({entry['targetInstanceId'] for entry in slots[0]['targets']}) == len(slots[0]['targets']))
    pending = [action['parameters']]
    while pending:
        value = pending.pop()
        if type(value) is list:
            pending.extend(value)
        elif type(value) is dict:
            for key, child in value.items():
                if key in ('instanceId', 'srcInstanceId', 'targetInstanceId'):
                    _need(_positive(child) and child in objects and objects[child]['zone'] == 'ZoneType_Battlefield')
                pending.append(child)


def _location(record, message=None):
    return {'record': record, 'message': message}


def _loc_key(value):
    _keys(value, ('record', 'message'))
    _need(_positive(value['record']) and (value['message'] is None or
          type(value['message']) is int and 0 <= value['message'] <= 512))
    return value['record'], value['message'] if value['message'] is not None else 0


def _binding(reducer, refs, scope, request):
    return {'generation_ref': refs.ref('generation', (), reducer.generation),
        'match_ref': refs.ref('match', (), scope[1]), 'game': scope[2], 'self_seat': scope[3],
        'request_ref': refs.ref('request', scope, request['id']),
        'state_ref': refs.ref('state', scope, request['game_state_id'])}


class _Collector:
    def __init__(self, generation, max_samples):
        self.refs, self.samples, self.counts, self.rejected = _Refs(), [], Counter(), Counter()
        self.max_samples = max_samples
        self.cached = self.active = None
        self.record = None
        self.ordinal = 0
        self.reducer = RawReducer(observer=self.observe, include_state_messages=True)
        self.reducer.reset(generation)

    def location(self, message):
        messages = self.record.get('greToClientEvent', {}).get('greToClientMessages', [])
        # Observer receives the original message object, not a reconstructed one.
        index = next((i for i, item in enumerate(messages) if item is message or
                      type(item) is dict and item.get('gameStateMessage') is message), None)
        _need(index is not None, 'mixed_record_ordering')
        return _location(self.ordinal, index)

    def finish(self, status):
        if self.active is not None:
            self.active['sample']['trace']['status'] = status
            self.active = None

    def observe(self, event, details):
        if event == 'continuity_error':
            self.cached = None
            self.finish('interrupted')
            return
        if event == 'state_accepted':
            self.cached = None
            if self.active is None or details['kind'] == 'full_retransmit':
                return
            if not _same(_scope(self.reducer), self.active['scope']):
                self.finish('interrupted')
            elif details['kind'] != 'diff':
                self.finish('full_baseline_not_continuous')
            elif len(self.active['sample']['trace']['states']) >= LIMIT:
                self.finish('limit_reached')
            else:
                try:
                    self.state(details['message'])
                except (SampleError, KeyError, TypeError, ValueError):
                    self.finish('interrupted')
            return
        if event != 'request_accepted':
            return
        message = details['message']
        request = _current_verified_raw_request(self.reducer, message)
        if request is None or request.get('_continuity_verified') is not True:
            self.cached = None
            return
        # The sampled profile keeps state and request messages separate. The
        # reducer may recognize hybrids; this projection does not certify them.
        if 'gameStateMessage' in message:
            self.cached = None
            self.finish('interrupted')
            return
        scope = _scope(self.reducer)
        snapshot = _public(self.reducer, self.refs, scope)
        self.cached = {'raw': copy.deepcopy(message), 'request': copy.deepcopy(request),
            'scope': scope, 'snapshot': snapshot, 'location': self.location(message), 'step': None}
        if self.active is None:
            return
        if not _same(scope, self.active['scope']):
            self.finish('interrupted')
            return
        sample = self.active['sample']
        if request['type'] == 'GREMessageType_ActionsAvailableReq':
            if len(sample['priority_requests']) >= LIMIT:
                self.finish('limit_reached')
                return
            sample['priority_requests'].append({'location': self.location(message),
                'binding': _binding(self.reducer, self.refs, scope, request)})
        elif request['type'] == 'GREMessageType_SelectTargetsReq':
            if len(sample['targets']) >= LIMIT:
                self.finish('limit_reached')
                return
            if sample['targets'] and (sample['targets'][-1]['response'] is None or
                    sample['targets'][-1]['response']['operation'] == 'final_submit'):
                self.finish('interrupted')
                return
            try:
                projected = targets.project_request(message, snapshot['objects'], self.reducer.seat, self.refs, scope)
            except (SampleError, KeyError, TypeError, ValueError):
                self.finish('interrupted')
            else:
                step = {'binding': _binding(self.reducer, self.refs, scope, request),
                    'location': self.location(message), 'request': projected,
                    'response': None, 'response_location': None}
                sample['targets'].append(step)
                self.cached['step'] = step
        else:
            # Other choices are outside this finite single-slot profile.
            self.finish('interrupted')

    def start(self, before, payload, saved):
        self.finish('superseded_by_new_activate')
        self.counts['matched_pairs'] += 1
        if len(self.samples) >= self.max_samples:
            self.counts['sample_limit_omissions'] += 1
            return
        try:
            actions = saved['raw'].get('actionsAvailableReq', {}).get('actions')
            selected = payload['performActionResp']['actions'][0]
            selected_position = _exact_selected_position(actions, selected)
            scope, snapshot = saved['scope'], saved['snapshot']
            source = self.reducer.objects.get(selected['instanceId'], {})
            _need(activate.ability_observation(selected, source.get('uniqueAbilities')) == 'verified_observed_pair' and
                  _id(source.get('grpId')) and _same(source['grpId'], selected['grpId']), 'request_unsupported')
            action_refs = RequestManaRefs(self.refs, before)
            offered = targets.action(_without_highlight(actions[selected_position]), action_refs, scope)
            projected_payload = copy.deepcopy(payload)
            projected_payload['performActionResp']['actions'][0] = _without_highlight(selected)
            response = _response(projected_payload, before, self.refs, scope, 4)
            _need(_same(offered, response['payload']['action']), 'response_unsupported')
            _check_visible_action(offered, snapshot, self.reducer.seat)
            rows = []
            for position, row in enumerate(actions):
                kind = row.get('actionType')
                label = kind if type(kind) is str and kind in _OBSERVED_ACTION_TYPES else '_unrecognized_action_type'
                rows.append({**_frontier_row(position, label, row),
                             'selected_literal': offered if position == selected_position else None})
            identity = {'match_ref': self.refs.ref('match', (), scope[1]), 'game': scope[2],
                'self_seat': scope[3], 'request_ref': self.refs.ref('request', scope, before['id'])}
            sample = {'identity': identity, 'generation_ref': self.refs.ref('generation', (), self.reducer.generation),
                'before': snapshot, 'request': {'kind': 'actions_available', 'payload': {
                    'profile': PROFILE, 'rows': rows, 'selected_position': selected_position}},
                'response': response,
                'source_observation': {'object_ref': offered['identifier_refs']['instanceId'],
                    'card_grp_ref': offered['identifier_refs']['grpId'],
                    'unique_ability_ref': offered['identifier_refs']['uniqueAbilityId'],
                    'ability_grp_ref': offered['identifier_refs']['abilityGrpId']},
                'locations': {'request': saved['location'], 'response': _location(self.ordinal)},
                'successor': {'status': 'not_observed', 'snapshot': None, 'request_kind': None, 'request_ref': None},
                'trace': {'status': 'eof', 'states': []}, 'targets': [], 'priority_requests': [],
                'provenance': {'exact_source_pair_verified_by_producer': True,
                    'private_auth_revalidated_by_replay': False, 'client_submission_only': True}}
        except (SampleError, KeyError, TypeError, ValueError) as error:
            reason = str(error) if isinstance(error, SampleError) and str(error) in REASONS else 'request_unsupported'
            self.rejected[reason] += 1
            return
        self.samples.append(sample)
        self.active = {'sample': sample, 'scope': scope, 'previous': snapshot, 'facts': [],
                       'final': None, 'complete_record': None}

    def state(self, gs):
        active, reducer = self.active, self.reducer
        sample, scope, previous = active['sample'], active['scope'], active['previous']
        snapshot = _public(reducer, self.refs, scope)
        chosen = sample['response']['payload']['action']
        facts, status, omitted = activate.facts(gs, reducer, self.refs, scope, previous, snapshot, chosen, active['facts'])
        # Facts referring to endpoints outside the strict public projection are withheld.
        objects = set(_objects(previous)) | set(_objects(snapshot))
        facts = [fact for fact in facts if all(value in objects for key, value in fact.items()
                 if key in ('source_object_ref', 'ability_object_ref'))]
        active['facts'].extend(facts)
        submitted, attachments = [], []
        created = {fact['ability_object_ref'] for fact in active['facts'] if fact['kind'] == 'ability_created'}
        source = chosen['identifier_refs']['instanceId']
        final = active['final']
        annotations = gs.get('annotations', [])
        if type(annotations) is list:
            for ann in annotations:
                if (type(ann) is not dict or set(ann) != {'id', 'affectorId', 'affectedIds', 'type'} or
                        not _id(ann.get('id')) or not _id(ann.get('affectorId')) or
                        type(ann.get('affectedIds')) is not list or len(ann['affectedIds']) != 1 or
                        not _id(ann['affectedIds'][0])):
                    continue
                actor = self.refs.ref('object', scope, ann['affectorId'])
                affected = self.refs.ref('object', scope, ann['affectedIds'][0])
                if (ann['type'] == ['AnnotationType_PlayerSubmittedTargets'] and
                        final is not None and _same(ann['affectorId'], reducer.seat) and len(created) == 1 and affected in created and
                        affected in objects):
                    submitted.append({'source_object_ref': affected})
                elif (ann['type'] == ['AnnotationType_AttachmentCreated'] and final is not None and
                        actor == source and final == [affected] and
                        all(_objects(snapshot).get(ident, {}).get('zone') == 'ZoneType_Battlefield'
                            for ident in (actor, affected))):
                    attachments.append({'source_object_ref': actor, 'target_object_ref': affected})
        row = {'location': self.location(gs), 'snapshot': snapshot,
            'previous_state_ref': self.refs.ref('state', scope, gs['prevGameStateId']),
            'facts': facts, 'facts_status': status, 'omitted_annotations': omitted,
            'target_submissions': submitted, 'attachments': attachments}
        sample['trace']['states'].append(row)
        if len(sample['trace']['states']) == 1:
            sample['successor'] = {'status': 'continuous_state_observed', 'snapshot': snapshot,
                                   'request_kind': None, 'request_ref': None}
        active['previous'] = snapshot
        if len(created) == 1 and all(any(fact['kind'] == kind and fact['ability_object_ref'] in created
                for fact in active['facts']) for kind in ('resolution_start', 'resolution_complete', 'ability_deleted')):
            active['complete_record'] = self.ordinal

    def apply(self, record, ordinal):
        self.record, self.ordinal = record, ordinal
        before, saved = copy.deepcopy(_current_verified_request(self.reducer)), self.cached
        payload = record.get('payload') if type(record) is dict else None
        self.reducer.apply(record)
        if self.active is not None and (not _same(_scope(self.reducer), self.active['scope']) or
                self.reducer.error is not None or self.reducer.game_info.get('stage') == 'GameStage_GameOver' or
                self.reducer.room_state == 'MatchGameRoomStateType_MatchCompleted'):
            self.finish('interrupted')
        mixed = type(payload) is dict and type(record) is dict and any(key in record for key in
            ('greToClientEvent', 'authenticateResponse', 'matchGameRoomStateChangedEvent'))
        paired = _paired_response(self.reducer, before, payload)
        terminal = _paired_terminal_submit(self.reducer, before, payload)
        current_saved = (not mixed and saved is not None and before is not None and
            _same(before, saved['request']) and _same(saved['scope'], _scope(self.reducer)) and
            before.get('_continuity_verified') is True)
        if current_saved and (paired or terminal):
            if before['type'] == 'GREMessageType_ActionsAvailableReq' and paired:
                actions = payload.get('performActionResp', {}).get('actions')
                if (type(actions) is list and len(actions) == 1 and type(actions[0]) is dict and
                        actions[0].get('actionType') == 'ActionType_Activate' and actions[0].get('targets')):
                    self.start(before, payload, saved)
            elif before['type'] == 'GREMessageType_SelectTargetsReq' and self.active is not None and saved['step'] is not None:
                try:
                    if not terminal:
                        target = payload.get('selectTargetsResp', {}).get('target', {})
                        _need(_id(target.get('targetIdx')), 'response_unsupported')
                        entries = target.get('targets')
                        _need(type(entries) is list and len(entries) == 1 and type(entries[0]) is dict and
                            ('highlight' not in entries[0] or type(entries[0]['highlight']) is str), 'response_unsupported')
                    projected = targets.response(payload, before, saved['step']['request'], self.refs, saved['scope'])
                    if not terminal and projected['payload']['entries'][0]['legal_action'] != targets.SELECT:
                        self.finish('interrupted')
                        return
                    saved['step']['response'] = projected['payload']
                    saved['step']['response_location'] = _location(ordinal)
                    if terminal:
                        self.active['final'] = targets.literal_selected(saved['step']['request'])
                except (SampleError, KeyError, TypeError, ValueError):
                    self.finish('interrupted')
        if type(payload) is dict and payload.get('type') == 'ClientMessageType_CancelActionReq':
            self.finish('interrupted')
        if mixed:
            self.finish('interrupted')
        if self.active is not None and self.active['complete_record'] == ordinal:
            self.finish('explicit_ability_deleted')
        if _current_verified_request(self.reducer) is None:
            self.cached = None


def collect_records(records, generation, origin, max_samples):
    collector = _Collector(generation, max_samples)
    for ordinal, record in enumerate(records, 1):
        try:
            collector.apply(record, ordinal)
        except (KeyError, TypeError, ValueError, RecursionError):
            raise SampleError('request_unsupported') from None
    collector.finish('eof')
    counts, rejected = collector.counts, collector.rejected
    document = {'schema_version': VERSION, 'projection': copy.deepcopy(PROJECTION),
        'source': {'format': 'player-log-gre-v1', 'mode': 'offline', 'origin': origin,
            'origin_is_user_supplied': True, 'framing_complete': True, 'framed_records': len(records),
            'raw_gre_replay': False, 'source_auth_revalidated_by_portable_replay': False},
        'counts': {'matched_pairs': counts['matched_pairs'], 'exported': len(collector.samples),
            'sample_limit_omissions': counts['sample_limit_omissions'], 'unsupported_pairs': sum(rejected.values())},
        'unsupported_reasons': [{'reason': reason, 'count': rejected[reason]} for reason in REASONS if rejected[reason]],
        'samples': collector.samples, 'read_only': True, 'execution': dict(EXECUTION)}
    replay(document)
    return document


def _check_inventory(payload, chosen, before, seat):
    _keys(payload, ('profile', 'rows', 'selected_position'))
    _need(payload['profile'] == PROFILE and type(payload['rows']) is list and 1 <= len(payload['rows']) <= 256)
    position = payload['selected_position']
    _need(type(position) is int and 0 <= position < len(payload['rows']))
    literals = []
    for i, row in enumerate(payload['rows']):
        _keys(row, ('list_position', 'action_type', 'known_parameter_shapes',
                    'other_top_level_fields_present', 'structurally_interpreted', 'selected_literal'))
        _need(type(row['list_position']) is int and row['list_position'] == i and
            type(row['action_type']) is str and row['action_type'] in _OBSERVED_ACTION_TYPES | {'_unrecognized_action_type'} and
            type(row['other_top_level_fields_present']) is bool and row['structurally_interpreted'] is False)
        shapes = row['known_parameter_shapes']
        _need(type(shapes) is dict and not set(shapes) - set(PARAMS))
        for key, value in shapes.items():
            count = 'auto_tap_actions_count' if key == 'autoTapSolution' else 'element_count'
            _keys(value, ('kind', count))
            _need(value['kind'] in (('object' if key == 'autoTapSolution' else 'array'), 'unexpected') and
                  (value[count] is None or type(value[count]) is int and 0 <= value[count] <= 1000000))
        if row['selected_literal'] is not None:
            _need(i == position and _same(row['selected_literal'], chosen) and row['action_type'] == 'ActionType_Activate')
            literals.append(i)
    _need(literals == [position])
    _check_visible_action(chosen, before, seat)


def _check_binding(binding, sample, snapshot):
    _keys(binding, ('generation_ref', 'match_ref', 'game', 'self_seat', 'request_ref', 'state_ref'))
    _need(all(_positive(value) for value in binding.values()))
    _need(all(_same(binding[key], sample['identity'][key]) for key in ('match_ref', 'game', 'self_seat')) and
          _same(binding['generation_ref'], sample['generation_ref']) and binding['state_ref'] == snapshot['state_ref'])


def replay(document):
    _check_envelope(document, VERSION, PROJECTION)
    reports = []
    for index, sample in enumerate(document['samples']):
        def location(value, client=False):
            result = _loc_key(value)
            _need(result[0] <= document['source']['framed_records'] and
                  ((value['message'] is None) if client else (value['message'] is not None)))
            return result

        _check_episode_base(sample, ('generation_ref', 'source_observation', 'locations', 'trace', 'targets', 'priority_requests'))
        _need(_positive(sample['generation_ref']))
        _check_public(sample['before'])
        _keys(sample['request'], ('kind', 'payload')); _keys(sample['response'], ('kind', 'payload'))
        _need(sample['request']['kind'] == sample['response']['kind'] == 'actions_available')
        response = sample['response']['payload']
        _need(type(response) is dict and set(response) in ({'action'}, {'action', 'auto_pass_priority'}) and
              ('auto_pass_priority' not in response or response['auto_pass_priority'] == 'AutoPassPriority_Yes'))
        chosen = response['action']; source = chosen['identifier_refs']['instanceId']
        _check_inventory(sample['request']['payload'], chosen, sample['before'], sample['identity']['self_seat'])
        observation = sample['source_observation']
        _keys(observation, ('object_ref', 'card_grp_ref', 'unique_ability_ref', 'ability_grp_ref'))
        _need(all(_positive(value) for value in observation.values()) and _same(observation, {
            'object_ref': source, 'card_grp_ref': chosen['identifier_refs']['grpId'],
            'unique_ability_ref': chosen['identifier_refs']['uniqueAbilityId'],
            'ability_grp_ref': chosen['identifier_refs']['abilityGrpId']}))
        _keys(sample['locations'], ('request', 'response'))
        request_location = location(sample['locations']['request'])
        response_location = location(sample['locations']['response'], client=True)
        _need(request_location < response_location)
        trace = sample['trace']; _keys(trace, ('status', 'states'))
        _need(trace['status'] in ENDS and type(trace['states']) is list and len(trace['states']) <= LIMIT)
        base_states = []; checkpoints = [(response_location, sample['before'])]
        last_location = response_location
        all_facts = []
        for row in trace['states']:
            _keys(row, ('location', 'snapshot', 'previous_state_ref', 'facts', 'facts_status',
                        'omitted_annotations', 'target_submissions', 'attachments'))
            state_location = location(row['location']); _need(last_location < state_location)
            _check_public(row['snapshot'])
            base_states.append({key: value for key, value in row.items() if key not in
                                ('location', 'target_submissions', 'attachments')})
            checkpoints.append((state_location, row['snapshot'])); last_location = state_location
            all_facts.extend(row['facts'])
        activate.check_trace({'status': 'limit_reached' if trace['status'] == 'limit_reached' else 'eof',
            'truncated': trace['status'] == 'limit_reached', 'next_request_ref': None, 'states': base_states}, sample['before'], chosen)
        _check_successor(sample['successor'], sample['before'])
        if trace['states']:
            _need(sample['successor']['status'] == 'continuous_state_observed' and
                  _same(sample['successor']['snapshot'], trace['states'][0]['snapshot']))
        else:
            _need(sample['successor']['status'] == 'not_observed')

        def snapshot_at(location):
            matches = [snapshot for position, snapshot in checkpoints if position <= location]
            _need(matches)
            return matches[-1]

        created = [fact['ability_object_ref'] for fact in all_facts if fact['kind'] == 'ability_created']
        ability = created[0] if len(created) == 1 else None
        _need(type(sample['targets']) is list and len(sample['targets']) <= LIMIT and
              type(sample['priority_requests']) is list and len(sample['priority_requests']) <= LIMIT)
        previous_step = None; final = None; final_location = None; linked = True; bounds_known = True
        seen_requests = {sample['identity']['request_ref']}
        for step in sample['targets']:
            _keys(step, ('binding', 'location', 'request', 'response', 'response_location'))
            request_position = location(step['location']); _need(request_position > response_location)
            snapshot = snapshot_at(request_position); _check_binding(step['binding'], sample, snapshot)
            _need(step['binding']['request_ref'] not in seen_requests)
            seen_requests.add(step['binding']['request_ref'])
            request = step['request']; targets.check_request(request, snapshot['objects'], sample['identity']['self_seat'])
            relation = _target_link_matches(request, chosen, ability)
            linked &= relation
            if previous_step is not None:
                previous_reply = previous_step['response']
                _need(previous_step['response_location'] is not None and
                      location(previous_step['response_location'], client=True) < request_position)
                binding_fields = ('source_object_ref', 'ability_grp_ref', 'targeting_ability_grp_ref', 'target_idx', 'targeting_player')
                _need(all(_same(previous_step['request'][key], request[key]) for key in binding_fields))
                if previous_reply is not None and previous_reply['operation'] == 'selection_update':
                    _need(previous_reply['entries'][0]['legal_action'] == targets.SELECT and
                        targets.literal_selected(request) == [previous_reply['entries'][0]['object_ref']])
            reply = step['response']
            if reply is None:
                _need(step['response_location'] is None)
            else:
                reply_location = location(step['response_location'], client=True)
                _need(request_position < reply_location)
                if reply.get('operation') == 'selection_update':
                    _keys(reply, ('operation', 'target_idx', 'entries'))
                    _need(_id(reply['target_idx']) and _same(reply['target_idx'], request['target_idx']) and
                          type(reply['entries']) is list and len(reply['entries']) == 1)
                    entry = reply['entries'][0]; _keys(entry, ('object_ref', 'legal_action'))
                    _need(_positive(entry['object_ref']) and entry['legal_action'] in (targets.SELECT, targets.UNSELECT) and
                          request['entries'] is not None and any(_same(entry, offered) for offered in request['entries']))
                    linked &= any(target['targetInstanceId'] == entry['object_ref']
                                  for target in chosen['parameters']['targets'][0]['targets'])
                    verdict, _ = targets.check_final_set(request, {'source_object_ref': request['source_object_ref'],
                        'target_idx': request['target_idx'], 'object_refs': [entry['object_ref']]})
                    _need(verdict != 'violated_known_constraints')
                    bounds_known &= verdict == 'verified_known_constraints'
                else:
                    _keys(reply, ('operation',)); _need(reply['operation'] == 'final_submit')
                    selected = targets.literal_selected(request)
                    _need(previous_step is not None and selected is not None and len(selected) == 1 and
                          previous_step['response'] is not None and previous_step['response']['operation'] == 'selection_update')
                    _need(final is None)
                    final, final_location = selected, reply_location
                    minimum, maximum = request['min_targets'], request['max_targets']
                    _need((minimum is None or len(final) >= minimum) and (maximum is None or len(final) <= maximum))
                    bounds_known &= minimum is not None and maximum is not None
            previous_step = step
        for checkpoint in sample['priority_requests']:
            _keys(checkpoint, ('location', 'binding'))
            request_position = location(checkpoint['location']); _need(request_position > response_location)
            _check_binding(checkpoint['binding'], sample, snapshot_at(request_position))
            _need(checkpoint['binding']['request_ref'] not in seen_requests)
            seen_requests.add(checkpoint['binding']['request_ref'])
        request_locations = [location(step['location']) for step in sample['targets']] + [
            location(checkpoint['location']) for checkpoint in sample['priority_requests']]
        _need(len(set(request_locations)) == len(request_locations))
        state_locations = [location(row['location']) for row in trace['states']]
        _need(not set(state_locations) & set(request_locations))
        gre_records = {location[0] for location in [request_location, *request_locations, *state_locations]}
        _need(response_location[0] not in gre_records)
        for step in sample['targets']:
            if step['response_location'] is not None:
                reply_location = location(step['response_location'], client=True)
                _need(reply_location[0] not in gre_records and not any(
                    location(step['location']) < checkpoint_position < reply_location
                    for checkpoint_position in [*request_locations, *state_locations]))
        if trace['status'] == 'explicit_ability_deleted':
            _need(trace['states'])
            end_record = trace['states'][-1]['location']['record']
            _need(all(position[0] <= end_record for position in [response_location, *request_locations,
                *[location(step['response_location'], client=True) for step in sample['targets']
                  if step['response_location'] is not None]]))
        submitted = attachment = False
        submission_locations = []
        attachment_locations = []
        previous_snapshot = sample['before']
        for row in trace['states']:
            objects = _objects(row['snapshot']); state_location = location(row['location'])
            _need(type(row['target_submissions']) is list and len(row['target_submissions']) <= 512 and
                  type(row['attachments']) is list and len(row['attachments']) <= 512)
            for fact in row['target_submissions']:
                _keys(fact, ('source_object_ref',))
                _need(_positive(fact['source_object_ref']) and fact['source_object_ref'] == ability and
                      final_location is not None and state_location > final_location and
                      any(_objects(snapshot).get(ability, {}).get('zone') == 'ZoneType_Stack'
                          for snapshot in (previous_snapshot, row['snapshot'])))
                submitted = True
                submission_locations.append(state_location)
            for fact in row['attachments']:
                _keys(fact, ('source_object_ref', 'target_object_ref'))
                _need(all(_positive(value) for value in fact.values()) and fact['source_object_ref'] == source and
                      final == [fact['target_object_ref']] and final_location is not None and state_location > final_location and
                      all(objects.get(ident, {}).get('zone') == 'ZoneType_Battlefield' for ident in fact.values()))
                attachment = True
                attachment_locations.append(state_location)
            previous_snapshot = row['snapshot']
        lifecycle = {}
        for row in trace['states']:
            for fact_index, fact in enumerate(row['facts']):
                if fact['kind'] not in ('ability_created', 'resolution_start', 'resolution_complete', 'ability_deleted'):
                    continue
                _need(fact['kind'] not in lifecycle)
                lifecycle[fact['kind']] = (location(row['location']), fact_index)
        ordered_kinds = ('ability_created', 'resolution_start', 'resolution_complete', 'ability_deleted')
        present = [lifecycle[kind] for kind in ordered_kinds if kind in lifecycle]
        _need(present == sorted(present))
        if 'resolution_start' in lifecycle and final_location is not None:
            _need(lifecycle['resolution_start'][0] > final_location)
        if 'resolution_start' in lifecycle and submission_locations:
            _need(all(position < lifecycle['resolution_start'][0] for position in submission_locations))
        resolved = ability is not None and all(kind in lifecycle for kind in ordered_kinds)
        if trace['status'] == 'explicit_ability_deleted':
            _need(resolved)
        continuous = trace['status'] == 'explicit_ability_deleted'
        complete_target_steps = (len(sample['targets']) == 2 and
            all(step['response'] is not None for step in sample['targets']) and
            sample['targets'][0]['response']['operation'] == 'selection_update' and
            sample['targets'][1]['response']['operation'] == 'final_submit')
        reviewed_trace = all(row['facts_status'] == 'reviewed_activate_subset' for row in trace['states'])
        result_coincident = ('resolution_start' in lifecycle and 'resolution_complete' in lifecycle and
            lifecycle['resolution_start'][0] == lifecycle['resolution_complete'][0] and
            lifecycle['resolution_start'][0] in attachment_locations)
        complete = bool(continuous and linked and bounds_known and complete_target_steps and reviewed_trace and
                        final is not None and submitted and resolved and attachment and result_coincident)
        reports.append({'sample_index': index, 'selected_action_position': sample['request']['payload']['selected_position'],
            'validation_level': 'verified_known_constraints' if complete else 'insufficient_evidence',
            'validation_scope': PROFILE, 'actual_activate_submission_observed': True,
            'public_parent_group_creation_observed': ability is not None,
            'target_request_linked_to_created_ability': bool(sample['targets'] and linked),
            'actual_target_selection_and_final_submit_observed': final is not None,
            'actual_selected_set_satisfies_explicit_request_bounds': bool(final is not None and bounds_known),
            'public_targets_submitted_observed': submitted, 'same_ability_resolution_and_deletion_observed': resolved,
            'public_attachment_endpoints_observed': bool(complete and attachment),
            'trace_status': trace['status'], 'continuation_unique_ability_identity_verified': False,
            'relevant_annotation_profile_supported': reviewed_trace,
            'attachment_and_ability_resolution_same_message_observed': bool(result_coincident),
            'raw_inventory_uniqueness_reauthenticated': False, 'effect_causation_verified': False})
    return {'schema_version': 'mtgaplayer.semantic-sample-replay.v10', 'samples': reports,
        'artifact_checks_passed': True, 'raw_source_auth_revalidated': False,
        'complete_legality_verified': False, 'complete_payment_verified': False,
        'server_acceptance_verified': False, 'read_only': True, 'execution': dict(EXECUTION)}
