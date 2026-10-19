"""Bounded source-build witness for the one independently reviewed target map.

Consumes the existing follower's bytes; no file reader, GRE parser or game state.
The private capability is tied to one reducer/reset and cannot be transferred.
"""
import hashlib
import re
import weakref

BUILD = '2026.64.0.14517.1329972'
PROFILE = 'reviewed_14517_1329972_player_system_seat_to_entity_instance'
PREFIX_BYTES = 16384
_HEADER = re.compile(rb'^Version: (\d+(?:\.\d+){3}) / (\d+(?:\.\d+){4}) /[ \t]*\r?\n', re.M)


class _BuildContext:
    def __init__(self, reducer, generation, header_hash):
        self.owner = weakref.ref(reducer)
        self.epoch = reducer._target_build_epoch
        self.generation = generation
        self.header_hash = header_hash
        self.build = BUILD
        self.profile = PROFILE

    def current(self, reducer):
        if (self.owner() is not reducer or self.epoch is not reducer._target_build_epoch or
                type(self.generation) is not int or self.generation != reducer.generation or
                self.build != BUILD or self.profile != PROFILE):
            return None
        return {'client_build': self.build, 'mapping_profile': self.profile,
            'generation': self.generation, 'header_sha256': self.header_hash}


def current_build(reducer):
    context = getattr(reducer, '_target_build_context', None)
    return context.current(reducer) if type(context) is _BuildContext else None


class TargetBuildObserver:
    """MP77 follower byte-observer protocol, only a finite version prelude."""
    def __init__(self):
        self.generation = None
        self.prefix = bytearray()
        self.failed_closed = False
        self.tail = b''
        self.header_start = None
        self.byte_end = 0

    def begin(self, info):
        if info['reset']:
            self.prefix.clear()
            self.generation = info['generation']
            self.tail = b''
            self.header_start = None
            self.byte_end = 0

    def write(self, offset, chunk):
        if offset != self.byte_end:
            self.failed_closed = True
        combined = self.tail + chunk
        start = offset - len(self.tail)
        for match in re.finditer(rb'^Version:', combined, re.M):
            absolute = start + match.start()
            if match.start() == 0 and start != 0:
                continue
            if self.header_start is None:
                self.header_start = absolute
            elif absolute != self.header_start:
                self.failed_closed = True
        self.tail = combined[-256:]
        self.byte_end = offset + len(chunk)
        if offset < PREFIX_BYTES:
            if offset != len(self.prefix):
                self.failed_closed = True
            self.prefix.extend(chunk[:max(0, PREFIX_BYTES-offset)])

    def end(self, info):
        digest = info.get('identity_prefix_sha256')
        # Source growth is safe only if the same follower's final reread still
        # agrees with the accepted prelude. A changed header cannot be blessed
        # by updating the follower's future anchor to its new bytes.
        if digest is not None:
            if digest != hashlib.sha256(self.prefix).hexdigest():
                self.failed_closed = True
        elif info.get('source_changed_during_poll'):
            self.failed_closed = True

    def failed(self):
        self.failed_closed = True

    def bind(self, reducer):
        reducer._target_build_context = None
        if self.failed_closed or self.generation != reducer.generation:
            return
        headers = list(_HEADER.finditer(bytes(self.prefix)))
        if len(headers) != 1:
            return
        short, full = (x.decode('ascii') for x in headers[0].groups())
        if full != BUILD or short != BUILD.rsplit('.', 1)[0]:
            return
        reducer._target_build_context = _BuildContext(reducer, self.generation,
            hashlib.sha256(headers[0].group()).hexdigest())
