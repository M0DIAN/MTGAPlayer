"""Optional strict-request combat observations; no legality or input authority."""
from collections import Counter
from dataclasses import dataclass

from .decision_input import build_decision_input
from .response_evidence import (_current_verified_raw_request,
    _current_verified_request, _identity, _id)

ATTACK = 'GREMessageType_DeclareAttackersReq'
BLOCK = 'GREMessageType_DeclareBlockersReq'
SCHEMAS = {ATTACK: ('declareAttackersReq', 'qualifiedAttackers', 'attackerInstanceId'),
           BLOCK: ('declareBlockersReq', 'blockers', 'blockerInstanceId')}
LIMIT = 256
FLAGS = {key: False for key in ('legal_choice_verified', 'complete_legality_verified',
    'response_encoding_verified', 'server_acceptance_verified', 'execution_ready', 'input_sent')}

def _reference(value):
    return value if _id(value) and value > 0 else None

@dataclass(frozen=True)
class _Candidate:
    reference: int | None
    attackers: tuple | None
    attacker_count: int | None
    relationship_issue: str | None
    recipient_count: int | None
    unknown_fields: bool

@dataclass(frozen=True)
class _Capture:
    identity: tuple
    ledger_entry: tuple
    request_type: str
    count: int | None
    rows: tuple | None
    issue: str
    unknown_fields: bool

def _capture(reducer, request, message):
    wrapper, field, key = SCHEMAS[request['type']]
    body = message.get(wrapper)
    rows = body.get(field) if isinstance(body, dict) else None
    parsed = None
    issue = ('combat_body_missing_or_invalid' if not isinstance(body, dict) else
             'candidate_field_missing' if field not in body else
             'candidate_array_invalid' if not isinstance(rows, list) else
             'candidate_array_truncated' if len(rows) > LIMIT else 'observed')
    if isinstance(rows, list):
        parsed = []
        for row in rows[:LIMIT]:
            row = row if isinstance(row, dict) else {}
            related = row.get('attackerInstanceIds')
            relation_issue = ('attacker_references_missing' if 'attackerInstanceIds' not in row else
                'attacker_references_invalid' if not isinstance(related, list) else
                'attacker_references_truncated' if len(related) > LIMIT else
                'attacker_references_invalid' if any(_reference(value) is None for value in related) else
                'attacker_references_duplicate' if len(set(related)) != len(related) else None)
            recipients = row.get('legalDamageRecipients')
            known = {key, 'legalDamageRecipients' if request['type'] == ATTACK else 'attackerInstanceIds'}
            parsed.append(_Candidate(_reference(row.get(key)),
                tuple(related) if request['type'] == BLOCK and relation_issue is None else None,
                len(related) if request['type'] == BLOCK and isinstance(related, list) else None,
                relation_issue if request['type'] == BLOCK else None,
                len(recipients) if request['type'] == ATTACK and isinstance(recipients, list) else None,
                bool(set(row) - known)))
        parsed = tuple(parsed)
    return _Capture(_identity(request), reducer.request_ids[request['id']], request['type'],
        len(rows) if isinstance(rows, list) else None, parsed, issue,
        bool(set(body) - {field}) if isinstance(body, dict) else False)

class CombatFrontierObserver:
    """One immutable snapshot; all acceptance and lifecycle authority stays in RawReducer."""
    def __init__(self):
        self.current = None

    def observe(self, reducer, event, details):
        if event in ('state_accepted', 'request_ended', 'continuity_error'):
            self.current = None
        elif event == 'request_accepted':
            request = _current_verified_raw_request(reducer, details['message'])
            if request is None or request['type'] not in SCHEMAS:
                self.current = None
                return
            if details.get('is_retransmission') is not False:
                # Existing reducer ledger decides whether this is a retransmission.
                # Keep an uninterrupted snapshot, never restore one after invalidation.
                if (self.current is None or self.current.identity != _identity(request) or
                        self.current.ledger_entry != reducer.request_ids[request['id']]):
                    self.current = None
                return
            self.current = _capture(reducer, request, details['message'])

    def project(self, reducer, document):
        decision = build_decision_input(document)
        request, captured = _current_verified_request(reducer), self.current
        if (decision is None or document.get('decision_input') != decision or
                request is None or captured is None or reducer.conflict or
                request['type'] != captured.request_type or _identity(request) != captured.identity or
                reducer.request_ids.get(request['id']) != captured.ledger_entry or
                (reducer.match, reducer.game, request['id']) in reducer.consumed or
                request['id'] in reducer.superseded):
            return None
        binding = decision['binding']
        identity = {name: binding[name] for name in
            ('generation', 'match', 'game', 'self_seat', 'game_state_id', 'request_id')}
        if tuple(identity.values()) != captured.identity or decision['request']['type'] != captured.request_type:
            return None
        identity['request_type'] = captured.request_type
        objects = decision['visible_objects']
        actual = reducer.document()['current'].get('objects', [])
        if [(obj['instance_id'], obj['zone'], obj['owner_seat'], obj['controller_seat']) for obj in objects] != [
                (obj['id'], obj['zone'], obj['owner'], obj['controller']) for obj in actual]:
            return None  # Caller metadata cannot manufacture a public source identity.
        counts = Counter(obj['instance_id'] for obj in objects)
        public = {obj['instance_id']: obj for obj in objects
                  if counts[obj['instance_id']] == 1 and obj['zone'] == 'ZoneType_Battlefield'}
        def linked(value, controller):
            obj = public.get(value)
            return value if obj is not None and obj['controller_seat'] == controller else None
        duplicates = Counter(row.reference for row in captured.rows or () if row.reference is not None)
        candidates = None if captured.rows is None else []
        for position, row in enumerate(captured.rows or ()):
            value = linked(row.reference, identity['self_seat'])
            reason = ('candidate_array_truncated' if captured.issue == 'candidate_array_truncated' else
                'candidate_reference_invalid' if row.reference is None else
                'candidate_reference_duplicate' if duplicates[row.reference] != 1 else
                'candidate_not_unique_public_own_battlefield' if value is None else None)
            edges = None
            if reason is None and row.attackers is not None:
                edges = [{'list_position': index,
                          'attacker_instance_id': linked(ref, 3 - identity['self_seat']),
                          'public_reference_verified': linked(ref, 3 - identity['self_seat']) is not None}
                         for index, ref in enumerate(row.attackers)]
            candidates.append({'candidate_position': position,
                'candidate_key': {'request_identity': identity.copy(), 'candidate_position': position},
                'candidate_instance_id': value if reason is None else None,
                'reference_verified': reason is None, 'unresolved_reference_reason': reason,
                'engine_listed_attacker_references': edges,
                'observed_attacker_reference_count': row.attacker_count,
                'verified_attacker_reference_count': (sum(edge['public_reference_verified'] for edge in edges)
                                                     if edges is not None else None),
                'unresolved_attacker_reference_count': (row.attacker_count -
                    sum(edge['public_reference_verified'] for edge in edges or ())
                    if row.attacker_count is not None else None),
                'attacker_relationship_issue': row.relationship_issue,
                'observed_recipient_count': row.recipient_count, 'attack_target_domain': None,
                'unknown_candidate_fields_present': row.unknown_fields,
                'unresolved_constraints': ['combination_legality_unknown', 'special_restrictions_unknown'] +
                    (['additional_candidate_fields_uninterpreted'] if row.unknown_fields else []) +
                    (['attacker_public_identity_unresolved'] if edges is not None and
                      any(not edge['public_reference_verified'] for edge in edges) else []) +
                    (['attacker_relationship_unavailable'] if captured.request_type == BLOCK and edges is None else []),
                **FLAGS})
        verified = sum(row['reference_verified'] for row in candidates) if candidates is not None else None
        return {'schema': 'mtga-combat-frontier-v1', 'request_identity': identity,
            'combat_request_type': captured.request_type, 'engine_offered_candidates': candidates,
            'observed_candidate_count': captured.count, 'verified_reference_count': verified,
            'unresolved_count': captured.count - verified if captured.count is not None else None,
            'count_scope': 'candidate_public_reference_occurrences_not_legal_combinations',
            'completeness': 'partial' if candidates is not None else 'unknown',
            'reason': captured.issue, 'unexamined_candidate_count':
                max(0, captured.count - LIMIT) if captured.count is not None else None,
            'truncated': captured.issue == 'candidate_array_truncated' or
                any(row.relationship_issue == 'attacker_references_truncated' for row in captured.rows or ()),
            'unknown_request_fields_present': captured.unknown_fields,
            'complete_attacker_domain': None, 'known_constraints': [],
            'unresolved_constraints': ['candidate_domain_completeness_unknown', 'mandatory_combat_unknown',
                'attack_target_domain_unknown', 'blocking_combinations_unknown', 'blocking_order_unknown',
                'damage_assignment_unknown', 'response_encoding_unknown', 'server_acceptance_unknown'],
            'provenance': {'candidate_path': '.'.join(SCHEMAS[captured.request_type][:2]),
                'reference_field': SCHEMAS[captured.request_type][2], 'accepted_request_digest_verified': True,
                'request_ownership_verified': True, 'source_mode': decision['source']['mode'],
                'source_phase': decision['source'].get('phase'), 'source_stopped': decision['source'].get('stopped'),
                'freshness_verified': False, 'history_or_default_completion_used': False,
                'response_or_server_acceptance_used': False, 'retransmission_restored': False},
            'scope': 'latest_authenticated_snapshot_not_live_action_authority',
            'legal_actions': None, 'read_only': True, 'usable_now': False, 'actionable': False,
            'executor_connected': False, **FLAGS}
