"""Bounded, value-free historical GRE choice relation evidence.

The public report is counts only. In-memory observed_edges preserve exact
request/action identity for an offline caller; no edge claims causation.
"""
from collections import Counter

from .choice_graph import build_historical_source_graph
from .semantic_evidence import _complex_classify, _COMPLEX_TYPES, _IDENTIFIERS


_PARAMETERS = ('targets', 'manaCost', 'manaPaymentOptions',
               'manaSelections', 'autoTapSolution')
_LINKS = ('auto_tap_mana_links', 'mana_selection_links')
_STATE_TYPES = frozenset(('GREMessageType_GameStateMessage',
                          'GREMessageType_QueuedGameStateMessage'))
_NEXT_TYPES = frozenset((
    'GREMessageType_ActionsAvailableReq', 'GREMessageType_SelectNReq',
    'GREMessageType_MulliganReq', 'GREMessageType_GroupReq',
    'GREMessageType_SelectTargetsReq', 'GREMessageType_DeclareBlockersReq'))
_MAX_GRAPHS = 512


def _set_status(graph, action_key, status):
    if graph is None:
        return
    graph['successor_observation_status'] = status
    for node in graph['action_nodes']:
        if action_key is None or node['action_key'] == action_key:
            node['successor_observation_status'] = status
            if status == 'temporal_observed':
                node['unresolved_parameters'] = [
                    item for item in node['unresolved_parameters']
                    if item != 'future_choice_request_unobserved']


def _identity(request):
    binding = request['binding']
    return {name: value for name, value in (
        ('generation', binding['generation']), ('match', binding['match']),
        ('game', binding['game']), ('self_seat', binding['self_seat']),
        ('game_state_id', request['game_state_id']),
        ('request_id', request['id']))}


def _selected_position(request, response, kind):
    """Use Phase 2's unique verdict; flags and parameters never break ties."""
    action = response['performActionResp']['actions'][0]
    fields = set(action) & _IDENTIFIERS.keys()
    rows = request['action_inventory']['complex_raw_shapes']
    matches = [row['list_position'] for row in rows
               if row['action_type'] == kind and
               set(row['raw_identifiers']) == {_IDENTIFIERS[f] for f in fields} and
               all(row['raw_identifiers'][_IDENTIFIERS[f]] == action[f]
                   for f in fields)]
    return matches[0] if len(matches) == 1 else None


class ChoiceHistoryCounter:
    """Feed only entries reduced by the existing exact response envelope gate."""

    def __init__(self):
        self.counts = Counter()
        self.parameter_counts = Counter()
        self.link_counts = Counter()
        self.pending = None
        self.observed_edges = []
        self.graphs = []
        self.source_integrity_complete = True

    def observe_request(self, request):
        inventory = request.get('action_inventory')
        rows = inventory.get('complex_raw_shapes') if isinstance(inventory, dict) else None
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict) or row.get('action_type') not in _COMPLEX_TYPES:
                continue
            self.counts['complex_active_rows'] += 1
            shapes = row.get('opaque_parameter_shapes')
            if not isinstance(shapes, dict):
                self.counts['malformed_complex_rows'] += 1
                continue
            for name in _PARAMETERS:
                if name in shapes:
                    self.parameter_counts[name] += 1
            relations = row.get('raw_relations')
            if not isinstance(relations, dict):
                self.counts['malformed_complex_rows'] += 1
                continue
            target = relations.get('target_slots')
            if isinstance(target, dict):
                self.counts['target_group_rows'] += len(target.get('entries', []))
                self.counts['target_group_truncated_rows'] += int(target.get('truncated') is True)
                self.counts['target_group_valid_rows'] += sum(
                    item.get('valid_shape') is True for item in target.get('entries', []))
            for name in _LINKS:
                links = relations.get(name)
                if isinstance(links, dict):
                    self.link_counts[name + '_unique'] += sum(
                        item.get('status') == 'unique_pair'
                        for item in links.get('entries', []))
                    self.link_counts[name + '_ambiguous_or_missing'] += sum(
                        item.get('status') != 'unique_pair'
                        for item in links.get('entries', []))
                    self.link_counts[name + '_truncated'] += int(links.get('truncated') is True)

    def observe_entry(self, entry, reducer):
        """Advance a pending response only through a later valid state/request.

        Ignore harmless GRE messages. More than one relevant state/request
        message, except one state then one request, has unsupported ordering.
        """
        if self.pending is None:
            return
        gre = entry.get('greToClientEvent') if isinstance(entry, dict) else None
        messages = gre.get('greToClientMessages') if isinstance(gre, dict) else None
        relevant = ([m for m in messages if not isinstance(m, dict) or
                     m.get('type') in _STATE_TYPES or
                     isinstance(m.get('type'), str) and m['type'].endswith('Req')]
                    if isinstance(messages, list) else [])
        state_messages = [m for m in relevant if isinstance(m, dict) and
                          m.get('type') in _STATE_TYPES]
        if isinstance(messages, list) and messages:
            kinds = [m.get('type') if isinstance(m, dict) else None for m in relevant]
            allowed_sequence = (len(kinds) == 1 and (
                kinds[0] in _STATE_TYPES or
                isinstance(kinds[0], str) and kinds[0].endswith('Req'))) or (
                len(kinds) == 2 and kinds[0] in _STATE_TYPES and
                isinstance(kinds[1], str) and kinds[1].endswith('Req'))
            if kinds and (not allowed_sequence or isinstance(entry.get('payload'), dict)):
                self._end('ordering_unsupported')
                return
        if (reducer.error is not None or
                (reducer.generation, reducer.match, reducer.game, reducer.seat) !=
                self.pending['scope'] or
                len(state_messages) > 1 or
                (isinstance(relevant, list) and any(not isinstance(m, dict) for m in relevant))):
            self._end('discontinuity')
            return
        if state_messages:
            state = state_messages[0].get('gameStateMessage')
            if (reducer.version <= self.pending['last_version'] or
                    not isinstance(state, dict) or
                    state.get('type') != 'GameStateType_Diff' or
                    state.get('prevGameStateId') != self.pending['last_version'] or
                    state.get('gameStateId') != reducer.version or
                    not all(isinstance(m.get('gameStateMessage'), dict)
                            for m in state_messages)):
                self._end('discontinuity')
                return
            self.pending['later_valid_state'] = True
            self.pending['last_version'] = reducer.version
        elif reducer.version != self.pending['last_version']:
            self._end('discontinuity')
            return
        request = reducer.request
        if (isinstance(messages, list) and any(
                isinstance(m, dict) and isinstance(m.get('type'), str) and
                m['type'].endswith('Req') and m.get('systemSeatIds') == [reducer.seat]
                for m in relevant) and request is None):
            self._end('discontinuity')
            return
        if (request is not None and request.get('current') is True and
                (request.get('id'), request.get('game_state_id')) !=
                (self.pending['identity']['request_id'],
                 self.pending['response_state'])):
            binding = request.get('binding')
            if (not self.pending['later_valid_state'] or
                    not isinstance(binding, dict) or
                    binding.get('ownership_verified') is not True or
                    request.get('type') not in _NEXT_TYPES or
                    request.get('game_state_id') != reducer.version or
                    request['game_state_id'] <= self.pending['response_state'] or
                    binding.get('self_seat') != reducer.seat):
                self._end('ordering_unsupported' if request.get('type') not in _NEXT_TYPES
                          else 'discontinuity')
                return
            choice = None
            if (request.get('type') == 'GREMessageType_SelectNReq' and
                    request.get('supported') is True and
                    isinstance(request.get('selection'), dict) and
                    isinstance(request.get('candidates'), list)):
                choice = {'kind': 'select_n_engine_offered_ids',
                          'offered_count': len(request['candidates']),
                          'max_sel_raw': request['selection'].get('max_sel'),
                          'min_sel_verified': None,
                          'combinations_complete': False,
                          'provenance_request_identity': _identity(request)}
            successor = {'request_identity': _identity(request),
                         'request_type': request['type'],
                         'request_shape_supported': request.get('supported') is True,
                         'next_request_choice_evidence': choice,
                         'relation': 'temporal_after_matched_client_submission_and_later_valid_state',
                         'causal_evidence': False,
                         'legal_choice_verified': False}
            if len(self.observed_edges) < _MAX_GRAPHS:
                self.observed_edges.append({
                    'action_key': self.pending['action_key'],
                    'observed_successor': successor,
                })
            else:
                self.counts['observed_edges_truncated'] += 1
            graph = self.pending.get('graph')
            if graph is not None:
                graph['observed_successors'].append(successor)
                for node in graph['action_nodes']:
                    if node['action_key'] == self.pending['action_key']:
                        node['observed_successors'].append(successor)
            self._end('temporal_successor_observed')

    def matched_response(self, request, response, reducer):
        if self.pending is not None:
            self._end('discontinuity')
        kind, result, truncated, unknown, _ = _complex_classify(request, response)
        if kind not in _COMPLEX_TYPES:
            return
        self.counts['matched_complex_responses'] += 1
        self.counts['correlation_' + result] += 1
        body = response.get('performActionResp') if isinstance(response, dict) else None
        if isinstance(body, dict) and set(body) - {'actions'}:
            # Unknown wrapper siblings keep response encoding unresolved; the
            # Phase 2 unique identity verdict is still valid for temporal use.
            self.counts['responses_with_unknown_wrapper_fields'] += 1
        graph = build_historical_source_graph(request)
        if graph is not None:
            if len(self.graphs) < _MAX_GRAPHS:
                self.graphs.append(graph)
            else:
                self.counts['historical_graphs_truncated'] += 1
                graph = None
        if result != 'unique' or truncated or unknown:
            self.counts['response_not_action_linked'] += 1
            _set_status(graph, None, 'not_action_linked')
            return
        position = _selected_position(request, response, kind)
        if position is None:
            self.counts['response_not_action_linked'] += 1
            _set_status(graph, None, 'not_action_linked')
            return
        identity = _identity(request)
        self.pending = {
            'identity': identity,
            'action_key': {'request_identity': identity, 'list_position': position},
            'scope': (reducer.generation, reducer.match, reducer.game, reducer.seat),
            'response_state': request['game_state_id'],
            'last_version': request['game_state_id'],
            'later_valid_state': False,
            'graph': graph,
        }
        self.counts['response_action_linked'] += 1

    def _end(self, outcome):
        self.counts[outcome] += 1
        if self.pending is not None:
            _set_status(self.pending.get('graph'), self.pending['action_key'],
                        'temporal_observed' if outcome == 'temporal_successor_observed'
                        else outcome)
        self.pending = None

    def finish(self, source_complete):
        self.source_integrity_complete = source_complete
        if self.pending is not None:
            self._end('no_successor_observed' if source_complete else 'discontinuity')
        if not source_complete and self.counts['temporal_successor_observed']:
            # Framing errors have no trustworthy per-record span. Withhold all
            # edges instead of guessing which recovered chain they affected.
            self.counts['source_incomplete_edges_withheld'] += self.counts['temporal_successor_observed']
            self.counts['discontinuity'] += self.counts['temporal_successor_observed']
            self.counts['temporal_successor_observed'] = 0
            self.observed_edges.clear()
            for graph in self.graphs:
                if graph['successor_observation_status'] == 'temporal_observed':
                    graph['successor_observation_status'] = 'discontinuity'
                graph['observed_successors'].clear()
                for node in graph['action_nodes']:
                    if node['successor_observation_status'] == 'temporal_observed':
                        node['successor_observation_status'] = 'discontinuity'
                        if 'future_choice_request_unobserved' not in node['unresolved_parameters']:
                            node['unresolved_parameters'].append(
                                'future_choice_request_unobserved')
                            node['unresolved_parameters'].sort()
                    node['observed_successors'].clear()

    def report(self):
        return {
            'scope': 'authenticated_historical_own_complex_requests_only',
            'complex_active_rows': self.counts['complex_active_rows'],
            'matched_complex_responses': self.counts['matched_complex_responses'],
            'correlation_counts': {name: self.counts['correlation_' + name] for name in
                                   ('unique', 'multiple', 'no_match', 'incomplete_or_unsupported')},
            'response_action_linked': self.counts['response_action_linked'],
            'response_not_action_linked': self.counts['response_not_action_linked'],
            'responses_with_unknown_wrapper_fields':
                self.counts['responses_with_unknown_wrapper_fields'],
            'temporal_successor_observed': self.counts['temporal_successor_observed'],
            'no_successor_observed': self.counts['no_successor_observed'],
            'discontinuity': self.counts['discontinuity'],
            'ordering_unsupported': self.counts['ordering_unsupported'],
            'source_integrity_complete': self.source_integrity_complete,
            'source_incomplete_edges_withheld':
                self.counts['source_incomplete_edges_withheld'],
            'historical_graphs_truncated': self.counts['historical_graphs_truncated'],
            'observed_edges_truncated': self.counts['observed_edges_truncated'],
            'parameter_container_rows': {name: self.parameter_counts[name]
                                         for name in _PARAMETERS},
            'target_group_rows': self.counts['target_group_rows'],
            'target_group_valid_rows': self.counts['target_group_valid_rows'],
            'target_group_truncated_rows': self.counts['target_group_truncated_rows'],
            'mana_pair_link_counts': {name: self.link_counts[name] for name in
                                      tuple(k + '_' + suffix for k in _LINKS
                                            for suffix in ('unique', 'ambiguous_or_missing',
                                                           'truncated'))},
            'successor_relation_is_temporal_only': True,
            'causal_evidence': False,
            'response_encoding_verified': False,
            'legal_choice_verified': False,
            'execution_ready': False,
            'input_sent': False,
            'raw_values_or_identifiers_exported': False,
        }
