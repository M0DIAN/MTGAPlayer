"""Opt-in accepted-state untap event witnesses, never tap defaults or payability."""
import copy
import hashlib
import json

from .semantic_samples import _need, _keys
from .decision_consumer import EXECUTION

PROVENANCE = 'mtgaplayer.payment-source-tap-provenance.v1'
VERSION = 'mtgaplayer.payment-source-untap-witness.v1'
FIELD = 'payment_source_tap_provenance'
PRIVATE = '_payment_source_tap_provenance'
GOOD = 'explicit_pre_request_untap_then_continuous'
GRADES = (GOOD, 'current_explicit_tapped', 'unknown', 'conflict')
SCOPE = 'same_current_two_payment_sources_explicit_untap_event_witnesses_only'
TAP = 'AnnotationType_TappedUntappedPermanent'
MAX_SOURCES = 512
REASONS = {
    GOOD: {'explicit_event_pair_then_continuous'},
    'current_explicit_tapped': {'current_explicit_tapped'},
    'conflict': {'ambiguous_or_conflicting_tap_event'},
    'unknown': {'no_explicit_event_pair', 'source_identity_changed', 'source_not_current_own_public_battlefield',
                'source_row_replaced', 'other_source_annotation', 'prior_explicit_tap_pair_not_observed'}}


def _location(value, annotation=False):
    from .decision_consumer import _integer
    _keys(value, ('record', 'message', 'state_id') + (('annotation',) if annotation else ()))
    _integer(value['record'], 1); _integer(value['message'], 0, 511); _integer(value['state_id'], 1)
    if annotation: _integer(value['annotation'], 0, 511)
    return value['record'], value['message']


def _fingerprints(reducer):
    from .action_target_menus import public_battlefield_refs
    result = {}
    for ref in public_battlefield_refs(reducer):
        obj = reducer.objects[ref]
        if (obj.get('type') != 'GameObjectType_Card' or type(obj.get('ownerSeatId')) is not int or
                obj['ownerSeatId'] != reducer.seat or type(obj.get('controllerSeatId')) is not int or
                obj['controllerSeatId'] != reducer.seat):
            continue
        value = {k: obj.get(k) for k in ('type', 'grpId', 'overlayGrpId', 'zoneId',
            'ownerSeatId', 'controllerSeatId', 'visibility', 'uniqueAbilities')}
        encoded = json.dumps(value, sort_keys=True, allow_nan=False).encode()
        _need(len(encoded) <= 16384)
        result[ref] = hashlib.sha256(encoded).hexdigest()
    _need(len(result) <= MAX_SOURCES)
    return result


class TapObserver:
    """Bounded last-witness cache on ONE reducer, not a second board or ledger.

    The owner calls prepare before apply and reset at source reset. Only the
    reducer's synchronous accepted-state/request callbacks admit observations.
    """
    def __init__(self, reducer):
        self.reducer = reducer
        self.reset()

    def reset(self):
        self.record = None; self.ordinal = 0; self.scope = None
        self.sources = {}; self.through = None; self.frozen = None
        self.quarantined = False

    def prepare(self, record):
        self.record = record; self.ordinal += 1

    def location(self, message, state_id):
        messages = self.record.get('greToClientEvent', {}).get('greToClientMessages', [])
        index = next((i for i, item in enumerate(messages) if item is message or
                      type(item) is dict and item.get('gameStateMessage') is message), None)
        value = {'record': self.ordinal, 'message': index, 'state_id': state_id}
        _location(value)
        return value

    def clear(self):
        self.sources = {}; self.through = None; self.frozen = None
        if self.reducer.request is not None: self.reducer.request.pop(PRIVATE, None)

    @staticmethod
    def invalidate(entry, reason, grade='unknown'):
        entry.update(grade=grade, reason=reason, tap_pair=None, untap=None)

    def observe(self, event, details):
        try:
            if event == 'continuity_error':
                self.clear()
            elif event == 'request_ended':
                self.frozen = None
                details['request'].pop(PRIVATE, None)
            elif event == 'state_accepted':
                if details['kind'] == 'full_retransmit':
                    self.clear()
                else:
                    self.state(details['message'])
            elif event == 'request_accepted':
                self.request(details)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError, OverflowError):
            # Optional instrumentation must never throw after core state commit.
            self.clear(); self.quarantined = True

    def state(self, gs):
        reducer = self.reducer
        scope = (reducer.generation, reducer.match, reducer.game, reducer.seat)
        if scope != self.scope or gs['type'] == 'GameStateType_Full':
            self.clear(); self.quarantined = False; self.scope = scope
        if self.quarantined: return
        here = self.location(gs, reducer.version)
        current = _fingerprints(reducer)
        annotations = gs.get('annotations', [])
        _need(type(annotations) is list and len(annotations) <= 512)
        related = {ref: [] for ref in current}
        tap_ids = set()
        for index, ann in enumerate(annotations):
            _need(type(ann) is dict and type(ann.get('type')) is list and ann['type'] and
                  all(type(t) is str for t in ann['type']))
            refs = list(ann.get('affectedIds', []))
            _need(type(ann.get('affectedIds', [])) is list and len(refs) <= 512 and
                  all(type(r) is int and r >= 0 for r in refs))
            if TAP in ann['type']:
                # An unlocatable tap cannot be classified as unrelated.
                _need(refs and len(refs) == len(set(refs)) and all(r > 0 for r in refs) and
                      type(ann.get('id')) is int and ann['id'] > 0 and ann['id'] not in tap_ids)
                tap_ids.add(ann['id'])
            if 'affectorId' in ann:
                _need(type(ann['affectorId']) is int and ann['affectorId'] >= 0)
                refs.append(ann['affectorId'])
            details = ann.get('details', [])
            _need(type(details) is list and len(details) <= 64)
            for item in details:
                _need(type(item) is dict)
                if 'valueInt32' in item:
                    ids = item['valueInt32']
                    _need(type(ids) is list and len(ids) <= 512 and all(type(x) is int for x in ids))
                    refs.extend(ids)
            for ref in set(refs) & current.keys(): related[ref].append((index, ann))
        rows = {obj['instanceId']: obj for obj in gs.get('gameObjects', [])}
        for ref, entry in self.sources.items():
            if ref not in current:
                self.invalidate(entry, 'source_not_current_own_public_battlefield')
                entry['fingerprint'] = None
        _need(len(self.sources.keys() | current.keys()) <= MAX_SOURCES)
        for ref, fingerprint in current.items():
            entry = self.sources.setdefault(ref, {'fingerprint': None, 'seen': set(),
                'grade': 'unknown', 'reason': 'no_explicit_event_pair', 'tap_pair': None, 'untap': None})
            prior_pair = copy.deepcopy(entry['tap_pair'])
            same = entry['fingerprint'] == fingerprint
            if not same:
                self.invalidate(entry, 'source_identity_changed'); prior_pair = None
            entry['fingerprint'] = fingerprint
            row = rows.get(ref)
            if row is not None:
                self.invalidate(entry, 'source_row_replaced')
            events = [(i, a) for i, a in related[ref] if TAP in a['type'] and ref in a.get('affectedIds', [])]
            other = [(i, a) for i, a in related[ref] if (i, a) not in events]
            if other:
                self.invalidate(entry, 'other_source_annotation'); prior_pair = None
            if not events:
                if row is not None and row.get('isTapped') is True:
                    self.invalidate(entry, 'current_explicit_tapped', 'current_explicit_tapped')
                continue
            from .semantic_cast import _detail
            try:
                _need(len(events) == 1)
                index, ann = events[0]
                _need(set(ann) in ({'id','affectedIds','type','details'},
                                  {'id','affectorId','affectedIds','type','details'}) and
                      ann['type'] == [TAP] and ann['affectedIds'] == [ref] and
                      type(ann['id']) is int and ann['id'] > 0)
                detail = _detail(ann)
                _need(set(detail) == {'tapped'} and type(detail['tapped']) is int and detail['tapped'] in (0, 1))
                _need(not any(ann['id'] in e['seen'] for e in self.sources.values()) and len(entry['seen']) < 64)
                entry['seen'].add(ann['id'])
                value = detail['tapped']; literal = row.get('isTapped') if row is not None else None
                _need(literal is None or literal is bool(value))
                at = {**here, 'annotation': index}
                if value == 1:
                    self.invalidate(entry, 'current_explicit_tapped', 'current_explicit_tapped')
                    # Calibrate this client's explicit 1 against this same raw row.
                    if literal is True: entry['tap_pair'] = at
                elif same and prior_pair is not None and not other:
                    # A fresh explicit event, never an omitted-field inference.
                    entry.update(grade=GOOD, reason='explicit_event_pair_then_continuous',
                                 tap_pair=prior_pair, untap=at)
                else:
                    self.invalidate(entry, 'prior_explicit_tap_pair_not_observed')
            except (ValueError, TypeError, KeyError):
                self.invalidate(entry, 'ambiguous_or_conflicting_tap_event', 'conflict')
        self.through = here

    def request(self, details):
        from .response_evidence import _current_verified_raw_request
        from .activate_target_payment import PROFILE
        reducer = self.reducer; request = details['request']; message = details['message']
        if not _current_verified_raw_request(reducer, message) or self.quarantined:
            self.frozen = None; return
        if details['is_retransmission']:
            if self.frozen is not None: request[PRIVATE] = copy.deepcopy(self.frozen)
            return
        self.frozen = None
        params = request.get('_request_parameters')
        if (type(params) is not dict or params.get('profile') != PROFILE or
                len(params['target_actions']) != 1 or self.through is None): return
        target = params['target_actions'][0]
        taps = target['action']['parameters']['autoTapSolution']['autoTapActions']
        if len(taps) != 2 or taps[0]['instanceId'] == taps[1]['instanceId']: return
        records = []
        for payment in taps:
            matches = [r for r in params['mana_actions'] if
                r['action']['identifier_refs']['instanceId'] == payment['instanceId'] and
                r['action']['identifier_refs']['abilityGrpId'] == payment['abilityGrpId']]
            if len(matches) != 1: return
            witness = matches[0]; entry = self.sources.get(payment['instanceId'])
            if entry is None:
                entry = {'grade': 'unknown', 'reason': 'no_explicit_event_pair', 'tap_pair': None, 'untap': None}
            records.append({'mana_action_position': witness['list_position'],
                'identifier_refs': copy.deepcopy(witness['action']['identifier_refs']),
                'witness_grade': entry['grade'], 'reason': entry['reason'],
                'tap_pair': copy.deepcopy(entry['tap_pair']) if entry['grade'] == GOOD else None,
                'untap': copy.deepcopy(entry['untap']) if entry['grade'] == GOOD else None})
        binding = {'source_generation': reducer.generation, 'match': reducer.match, 'game': reducer.game,
            'game_state_id': reducer.version, 'self_seat': reducer.seat,
            'request_id': request['id'], 'request_type': request['type']}
        value = {'schema_version': PROVENANCE, 'binding': binding, 'action_position': target['list_position'],
            'request_location': self.location(message, reducer.version), 'checked_through': copy.deepcopy(self.through),
            'sources': records, 'historical_response_used': False}
        self.frozen = copy.deepcopy(value); request[PRIVATE] = value


def check(value, binding, params, visible):
    """Portable producer claims; cannot reauthenticate withheld raw events."""
    from .decision_consumer import _binding, _integer
    if value is None: return
    _keys(value, ('schema_version','binding','action_position','request_location','checked_through','sources','historical_response_used'))
    _need(value['schema_version'] == PROVENANCE and value['historical_response_used'] is False)
    _binding(value['binding'], complete=True); _need(value['binding'] == binding and binding['request_id'] is not None)
    from .activate_target_payment import PROFILE
    _need(type(params) is dict and params.get('profile') == PROFILE and len(params['target_actions']) == 1)
    target = params['target_actions'][0]; _integer(value['action_position'], 0, 255)
    _need(value['action_position'] == target['list_position'])
    through = _location(value['checked_through']); request_at = _location(value['request_location'])
    _need(through < request_at and value['checked_through']['state_id'] == binding['game_state_id'] and
          value['request_location']['state_id'] == binding['game_state_id'])
    _need(type(value['sources']) is list and len(value['sources']) == 2)
    taps = target['action']['parameters']['autoTapSolution']['autoTapActions']; seen = set()
    _need(len(taps) == 2)
    for entry, payment in zip(value['sources'], taps):
        _keys(entry, ('mana_action_position','identifier_refs','witness_grade','reason','tap_pair','untap'))
        _integer(entry['mana_action_position'], 0, 255)
        _need(entry['witness_grade'] in GRADES and entry['reason'] in REASONS[entry['witness_grade']])
        _need(entry['mana_action_position'] not in seen); seen.add(entry['mana_action_position'])
        matches = [r for r in params['mana_actions'] if r['list_position'] == entry['mana_action_position']]
        _need(len(matches) == 1 and json.dumps(matches[0]['action']['identifier_refs'], sort_keys=True) ==
              json.dumps(entry['identifier_refs'], sort_keys=True) and
              entry['identifier_refs']['instanceId'] == payment['instanceId'] and
              entry['identifier_refs']['abilityGrpId'] == payment['abilityGrpId'])
        if entry['witness_grade'] == GOOD:
            start = _location(entry['tap_pair'], True); end = _location(entry['untap'], True)
            _need(start < end <= through and entry['tap_pair']['state_id'] < entry['untap']['state_id'] <= binding['game_state_id'])
            objects = [o for o in visible if o['instance_id'] == entry['identifier_refs']['instanceId']]
            _need(len(objects) == 1 and objects[0]['tapped'] is not True)
        else:
            _need(entry['tap_pair'] is None and entry['untap'] is None)


def unknown(reason, ref=None):
    return {'schema_version': VERSION, 'scope': SCOPE, 'status': 'insufficient_evidence', 'reason': reason,
        'request_binding': None, 'source_snapshot_ref': copy.deepcopy(ref), 'source_witnesses': [],
        'verified_source_count': 0, 'untapped_pre_request_witness_verified': False,
        'payment_source_readiness': 'unknown_global_conditions_not_evaluated',
        'overall_payability_verified': False, 'complete_costs_verified': False, 'complete_payment_verified': False,
        'target_quantity_verified': False, 'target_domain_complete_verified': False, 'rules_effect_verified': False,
        'historical_response_used': False, 'raw_source_reauthenticated': False, 'diagnostics_only': True,
        'read_only': True, **EXECUTION}


def evaluate_witness(state, *, source_snapshot_ref=None):
    from .decision_consumer import _bounded_json, _state, _reference, _binding
    from .activate_target_payment import evaluate_relation, CONSISTENT, VERSION as RELATION_VERSION, SCOPE as RELATION_SCOPE
    try:
        _bounded_json(state); _state(state, state['binding'])
        if source_snapshot_ref is not None:
            _reference(source_snapshot_ref, source_snapshot_ref['session_id'], source_snapshot_ref['sequence'], snapshot=True)
            _need(source_snapshot_ref['binding'] == state['binding'])
        if state['schema_version'] != 'mtgaplayer.decision-state.v10' or state[FIELD] is None:
            return unknown('current_tap_provenance_not_observed')
        relation = evaluate_relation(state, source_snapshot_ref=source_snapshot_ref)
        _bounded_json(relation); _binding(relation['request_binding'], complete=True)
        _need(relation['schema_version'] == RELATION_VERSION and relation['scope'] == RELATION_SCOPE and
              relation['read_only'] is True and relation['source_snapshot_ref'] == source_snapshot_ref and
              relation['diagnostics_only'] is True and relation['request_binding'] == state['binding'] and
              relation['payment_source_readiness'] == 'unknown_not_evaluated' and
              all(relation[k] is False for k in (*EXECUTION,
              'overall_payability_verified','payment_source_untapped_verified','complete_costs_verified',
              'complete_payment_verified','target_quantity_verified','target_domain_complete_verified',
              'target_selection_legality_verified','full_action_domain_complete','rules_effect_verified',
              'historical_response_used','raw_source_reauthenticated')))
        _need(all(k not in relation or relation[k] is False for k in (
            'payment_completed_verified','mana_payment_verified','target_quantity_completeness_verified',
            'complete_target_legality_verified','global_restrictions_verified','target_selection_legal_verified',
            'untapped_pre_request_witness_verified')))
        if source_snapshot_ref is not None:
            _reference(relation['source_snapshot_ref'], source_snapshot_ref['session_id'], source_snapshot_ref['sequence'], snapshot=True)
        if relation['status'] != CONSISTENT or type(relation['returned_relations']) is not int or relation['returned_relations'] != 1:
            return unknown('same_current_joint_association_not_verified', source_snapshot_ref)
        evidence = state[FIELD]; row = relation['relations'][0]
        _need(type(relation['relations']) is list and len(relation['relations']) == 1)
        target = state['legal_action_space']['request_parameters']['target_actions'][0]['action']
        _need(json.dumps(row['action_identifier_refs'], sort_keys=True) == json.dumps(target['identifier_refs'], sort_keys=True) and
              json.dumps(row['action_flags'], sort_keys=True) == json.dumps(target['flags'], sort_keys=True))
        _need(type(row['list_position']) is int and row['list_position'] == evidence['action_position'] and
              row['relation_status'] == CONSISTENT and type(row['mana_row_witnesses']) is list and
              len(row['mana_row_witnesses']) == 2 and all(type(r['list_position']) is int for r in row['mana_row_witnesses']) and
              [r['list_position'] for r in row['mana_row_witnesses']] == [s['mana_action_position'] for s in evidence['sources']])
        target_params = target['parameters']['targets'][0]
        _need(json.dumps(row['target_member'], sort_keys=True) == json.dumps(
            {'identifier_refs': target['identifier_refs'], 'target_idx': target_params['targetIdx'],
             'object_ref': target_params['targets'][0]['targetInstanceId']}, sort_keys=True))
        for witness, source in zip(row['mana_row_witnesses'], evidence['sources']):
            _need(json.dumps(witness['identifier_refs'], sort_keys=True) == json.dumps(source['identifier_refs'], sort_keys=True))
            mana = next(r['action'] for r in state['legal_action_space']['request_parameters']['mana_actions']
                        if r['list_position'] == source['mana_action_position'])
            _need(json.dumps(witness['flags'], sort_keys=True) == json.dumps(mana['flags'], sort_keys=True))
        result = unknown('one_or_both_source_chains_unknown', source_snapshot_ref)
        result.update(request_binding=copy.deepcopy(state['binding']), source_witnesses=copy.deepcopy(evidence['sources']))
        result['verified_source_count'] = sum(s['witness_grade'] == GOOD for s in evidence['sources'])
        if result['verified_source_count'] == 2:
            result.update(status='two_explicit_pre_request_untap_event_witnesses',
                reason='same_current_sources_have_continuous_explicit_event_witnesses', untapped_pre_request_witness_verified=True)
        _bounded_json(result)
        return result
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, OverflowError):
        return unknown('state_or_tap_evidence_invalid')


def assess_current_witness(consumer):
    from .choice_candidates import _assess_current_report
    return _assess_current_report(consumer, evaluate_witness, unknown)
