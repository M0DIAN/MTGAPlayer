"""Isolated qualification instrumentation, loaded ONLY by temporary sitecustomize.

The real ``python -m mtgaplayer`` CLI still reads/decodes/validates/caches every
event. The direct producer stdout -> consumer stdin pipe is untouched. Extra
confirmations and copies add overhead to the measured path. No game identity
or card content is emitted; binding digests exist only for controller matching.
"""
import hashlib
import json
import os
import sys
import time


def binding_tag(binding):
    return hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def install():
    role = os.environ['MTGAPLAYER_DELIVERY_PROBE_ROLE']
    if role == 'producer':
        from mtgaplayer.decision_publisher import DecisionPublisher
        original = DecisionPublisher.observe

        def observe(self, document, metadata):
            pause_file = os.environ.get('MTGAPLAYER_DELIVERY_PAUSE_FILE')
            if pause_file and not os.path.exists(pause_file):
                print(json.dumps({'_delivery_gate': True}), file=sys.stderr, flush=True)
                deadline = time.perf_counter() + 2
                while not os.path.exists(pause_file) and time.perf_counter() < deadline:
                    time.sleep(.01)
                if not os.path.exists(pause_file):
                    raise ValueError('test_producer_gate_deadline')
            events = original(self, document, metadata)
            print(json.dumps({'_delivery_poll': True,
                'offset': document['source']['byte_offset'],
                'generation': document['source']['generation'],
                'sequences': [e['sequence'] for e in events],
                'event_types': [e['event_type'] for e in events]}), file=sys.stderr, flush=True)
            return events
        DecisionPublisher.observe = observe
    elif role in ('consumer', 'consumer_terminal'):
        import mtgaplayer.decision_consumer as consumer
        original = consumer.DecisionConsumer.accept_event

        def accept(self, event, **kwargs):
            before = time.perf_counter_ns()
            accepted = original(self, event, **kwargs)
            after = time.perf_counter_ns()
            view = self.current_view()  # Actual validated, detached cached view.
            viewed = time.perf_counter_ns()
            state = view['decision_state']
            ref = view['current_snapshot_ref']
            flags_safe = (view['read_only'] is True and all(view[k] is False for k in
                ('actionable', 'executor_connected', 'legal_choice_verified', 'complete_legality_verified',
                 'response_encoding_verified', 'server_acceptance_verified', 'execution_ready', 'input_sent')) and
                (state is None or state['source']['freshness_verified'] is False))
            print(json.dumps({'_delivery_ack': True, 'sequence': event['sequence'],
                'event_type': event['event_type'], 'accepted': accepted,
                'last_sequence': view['last_sequence'], 'status': view['consumer_status'],
                'reference_sequence': None if ref is None else ref['sequence'],
                'binding_tag': None if state is None else binding_tag(state['binding']),
                'has_state': state is not None, 'flags_safe': flags_safe,
                'phase': event['phase'], 'new_request_observed': view['new_request_observed'],
                'reason': event.get('reason'), 'revoked_sequence': event.get('revoked', {}).get('sequence'),
                'timing': {k: event['timing'][k] for k in ('poll_read_ns', 'reducer_apply_ns',
                    'decision_state_assembly_ns', 'event_publication_ns', 'poll_to_publish_ns')},
                'consumer_validate_cache_ns': after - before,
                'probe_view_copy_ns': viewed - after}), flush=True)
            return accepted
        if role == 'consumer':
            consumer.DecisionConsumer.accept_event = accept
        original_stream = consumer.consume_events

        def consume_events(stream, emit, instance=None, **options):
            instance = instance if instance is not None else consumer.DecisionConsumer()
            def checked_emit(diagnostic):
                emit(diagnostic)
                if diagnostic['consumer_status'] in ('CLOSED', 'STALE', 'PROTOCOL_ERROR'):
                    view = instance.current_view()
                    print(json.dumps({'_delivery_terminal_view': True,
                        'status': view['consumer_status'], 'last_sequence': view['last_sequence'],
                        'has_state': view['decision_state'] is not None,
                        'has_reference': view['current_snapshot_ref'] is not None}), flush=True)
            return original_stream(stream, checked_emit, instance, **options)
        consumer.consume_events = consume_events
    else:
        raise ValueError('unsupported_delivery_probe_role')
