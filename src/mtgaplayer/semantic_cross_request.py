"""Opt-in, artifact-only correlation of two observed public Stack endpoints.

One v9 export uses a scoped alias table, but portable replay does not revalidate
its private raw source. Equality is a candidate shared object reference, NEVER
a proof that PayCosts originated from an Activate or caused a later Search.
"""
from collections import Counter

from .semantic_samples import _need

SCHEMA = 'mtgaplayer.shared-stack-observation.v1'
SOURCE_VERSION = 'mtgaplayer.semantic-samples.v9'
REPORT_VERSION = 'mtgaplayer.semantic-sample-replay.v9'


def _same_stack_at_endpoints(cost, search, ref, seat):
    """Four independently retained public Stack endpoints; never hidden data."""
    states = (cost['before'], cost['trace']['states'][0]['snapshot'],
              search['before'], search['trace']['states'][0]['snapshot'])
    for state in states:
        hits = [obj for obj in state['objects'] if obj['object_ref'] == ref]
        if (len(hits) != 1 or hits[0]['zone'] != 'ZoneType_Stack' or
                hits[0]['owner'] != seat or hits[0]['controller'] != seat):
            return False
    return True


def analyze(document, report):
    """Post-validation observation within ONE v9 document, not two exports.

    Caller must have run replay_samples(document) to obtain report. The
    document can still be forged or curated; replay does not authenticate raw
    logs. No historical evidence is fed to current DecisionState/ChoiceValidation.
    """
    _need(type(document) is dict and document.get('schema_version') == SOURCE_VERSION and
          type(report) is dict and report.get('schema_version') == REPORT_VERSION and
          type(document.get('samples')) is list and type(report.get('samples')) is list and
          len(document['samples']) == len(report['samples']), 'shared_stack_requires_valid_v9')
    samples, assessments = document['samples'], report['samples']
    proposals = []
    for i, cost in enumerate(samples):
        cost_result = assessments[i]
        if (cost['request']['kind'] != 'effect_cost_select' or
                cost_result.get('selected_card_sacrifice_observed') is not True):
            continue
        affector = cost_result.get('observed_affector_ref')
        if type(affector) is not int or affector < 1:
            continue
        # The existing v9 checker verifies the explicit annotation chain. No
        # request source ID was supplied, and the affector cannot fill it in.
        if cost['request']['payload']['source_object_ref'] is not None:
            continue
        identity = cost['identity']
        for j in range(i + 1, len(samples)):
            search = samples[j]
            result = assessments[j]
            if (search['request']['kind'] != 'search' or
                    result.get('selected_item_public_transfer_observed') is not True or
                    search['request']['payload']['source_object_ref'] != affector):
                continue
            if any(identity[key] != search['identity'][key]
                   for key in ('match_ref', 'game', 'self_seat')):
                continue
            if (not cost['trace']['states'] or not search['trace']['states'] or
                    not (cost['before']['state_ref'] <
                         cost['trace']['states'][0]['snapshot']['state_ref'] <
                         search['before']['state_ref'] <
                         search['trace']['states'][0]['snapshot']['state_ref'])):
                continue
            if not _same_stack_at_endpoints(cost, search, affector, identity['self_seat']):
                continue
            proposals.append((i, j, affector))
    # Refuse ambiguous many-to-one or one-to-many exported episodes rather than
    # claiming that mere ordering proves a unique parent/child relationship.
    left, right = Counter(i for i, _, _ in proposals), Counter(j for _, j, _ in proposals)
    accepted = [(i, j, ref) for i, j, ref in proposals
                if left[i] == 1 and right[j] == 1]
    links = [{'effect_cost_sample_index': i, 'search_sample_index': j,
              'shared_visible_stack_object_ref': ref,
              'observed_relation': 'same_scoped_alias_at_four_public_stack_endpoints',
              'sacrifice_result_observed': True,
              'search_public_transfer_observed': True,
              'paycosts_request_source': None,
              'parent_activate_causality_verified': False,
              'paycosts_to_search_causality_verified': False,
              'same_live_raw_source_reauthenticated': False}
             for i, j, ref in accepted]
    return {'schema_version': SCHEMA, 'scope': 'one_portable_v9_export_only',
            'source_auth_revalidated': False, 'causality_verified': False,
            'complete_payment_verified': False, 'complete_legality_verified': False,
            'server_acceptance_verified': False, 'input_sent': False,
            'ambiguous_pairs_withheld': len(proposals) - len(accepted),
            'links': links}
