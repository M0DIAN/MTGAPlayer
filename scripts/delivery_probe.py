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
import threading
import inspect


def internal_probe(module):
    """Read-only sampling: never call current_view/tick from the observer.

    stderr is test evidence, not an alternative product notification channel.
    Only the real consume core invokes the original state transition methods.
    """
    original_stream = module.consume_events

    def consume(stream, emit, instance=None, **options):
        instance = instance if instance is not None else module.DecisionConsumer()
        stats = {'ticks': 0, 'accepted': 0, 'order_errors': 0, 'emit_started': 0,
                 'emit_returned': 0, 'emit_active_since_ns': None, 'input_peak': 0,
                 'input_overflows': 0}
        stop = threading.Event()
        original_tick, original_accept, original_clear = instance._tick, instance.accept_event, instance._clear
        original_queue = module.queue.Queue
        writer = []
        if hasattr(module, '_DiagnosticOutput'):
            original_output = module._DiagnosticOutput.__init__
            def output_init(self, *args, **kwargs):
                original_output(self, *args, **kwargs)
                writer.append(self)
            module._DiagnosticOutput.__init__ = output_init

        class MeteredQueue(original_queue):
            def _put(self, item):
                super()._put(item)
                stats['input_peak'] = max(stats['input_peak'], self._qsize())
            def put_nowait(self, item):
                try:
                    return super().put_nowait(item)
                except module.queue.Full:
                    stats['input_overflows'] += 1
                    raise
        module.queue.Queue = MeteredQueue

        def tick(now):
            stats['ticks'] += 1
            return original_tick(now)
        def accept(event, **kwargs):
            delay_file = os.environ.get('MTGAPLAYER_TEST_SLOW_ACCEPT_FILE')
            if delay_file and os.path.exists(delay_file):
                time.sleep(.03)
            previous = instance._sequence
            result = original_accept(event, **kwargs)
            if result:
                stats['accepted'] += 1
                if event['sequence'] != (previous or 0) + 1:
                    stats['order_errors'] += 1
            return result
        def snapshot(kind):
            return {'_consumer_internal': True, 'kind': kind, **stats,
                'child_ns': time.perf_counter_ns(), 'status': instance._status,
                'reason': instance._reason, 'last_sequence': instance._sequence,
                'has_state': instance._state is not None, 'has_reference': instance._ref is not None,
                'output': None if not writer else writer[0].metrics()}
        def send(kind):
            data = (json.dumps(snapshot(kind)) + '\n').encode()
            while data:
                count = os.write(2, data)
                if count <= 0:
                    return
                data = data[count:]
        def clear(status, reason):
            original_clear(status, reason)
            send('clear')
        def checked_emit(value):
            stats['emit_started'] += 1
            stats['emit_active_since_ns'] = time.perf_counter_ns()
            try:
                emit(value)
            finally:
                stats['emit_returned'] += 1
                stats['emit_active_since_ns'] = None
        def observe():
            cancel_file = os.environ.get('MTGAPLAYER_TEST_CANCEL_FILE')
            cancelled = False
            for _ in range(300):  # Hard evidence bound: six seconds.
                if stop.wait(.02):
                    return
                send('sample')
                if cancel_file and not cancelled and os.path.exists(cancel_file):
                    import _thread
                    cancelled = True
                    _thread.interrupt_main()  # Synthetic Python cancellation only.
        instance._tick, instance.accept_event, instance._clear = tick, accept, clear
        observer = threading.Thread(target=observe, name='test-internal-observer', daemon=True)
        observer.start()
        supplied = json.loads(os.environ.get('MTGAPLAYER_CONSUMER_TEST_OPTIONS', '{}'))
        options.update({k: v for k, v in supplied.items() if k in inspect.signature(original_stream).parameters})
        try:
            return original_stream(stream, checked_emit, instance, **options)
        finally:
            stop.set()
            observer.join(.2)
            send('returned')
    module.consume_events = consume


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
    elif role == 'consumer_internal':
        import mtgaplayer.decision_consumer as consumer
        internal_probe(consumer)
    elif role in ('consumer', 'consumer_terminal'):
        import mtgaplayer.decision_consumer as consumer
        original = consumer.DecisionConsumer.accept_event
        acknowledgements = {}
        ack_lock = threading.Lock()
        terminal_cache = {}
        original_clear = consumer.DecisionConsumer._clear

        def clear(self, status, reason):
            original_clear(self, status, reason)
            if status in ('CLOSED', 'STALE', 'PROTOCOL_ERROR'):
                terminal_cache.update(status=status, has_state=self._state is not None,
                                      has_reference=self._ref is not None)
        consumer.DecisionConsumer._clear = clear

        def write(value):
            data = (json.dumps(value) + '\n').encode()
            while data:
                count = os.write(1, data)
                if count <= 0:
                    raise OSError('probe_short_write')
                data = data[count:]

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
            ack = {'_delivery_ack': True, 'sequence': event['sequence'],
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
                'probe_view_copy_ns': viewed - after}
            with ack_lock:
                if len(acknowledgements) >= 1024:
                    raise ValueError('test_ack_buffer_limit')
                acknowledgements[event['sequence']] = ack
            return accepted
        if role == 'consumer':
            consumer.DecisionConsumer.accept_event = accept
        original_stream = consumer.consume_events

        def consume_events(stream, emit, instance=None, **options):
            instance = instance if instance is not None else consumer.DecisionConsumer()
            def checked_emit(diagnostic):
                emit(diagnostic)
                with ack_lock:
                    ready = [acknowledgements.pop(seq) for seq in sorted(acknowledgements)
                             if seq <= diagnostic.get('last_sequence', 0)]
                for ack in ready:
                    write(ack)
                if diagnostic['consumer_status'] in ('CLOSED', 'STALE', 'PROTOCOL_ERROR'):
                    write({'_delivery_terminal_view': True, **terminal_cache,
                           'last_sequence': diagnostic.get('last_sequence')})
            return original_stream(stream, checked_emit, instance, **options)
        consumer.consume_events = consume_events
    else:
        raise ValueError('unsupported_delivery_probe_role')
