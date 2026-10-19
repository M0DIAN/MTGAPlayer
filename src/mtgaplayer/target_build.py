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
RESOURCE = {
    'client_build': BUILD,
    'manifest_basename': 'Manifest_c98372b34219b5c4aa478e8bf296f5ee.mtga',
    'manifest_identity_md5': 'c98372b34219b5c4aa478e8bf296f5ee',
    'manifest_sha256': '908abd96f922ad0e90c802863640cc0ac1f9df25f40fa618171bf78ca9849a5e',
    'catalog_sha256': '1be0105411ad989ca60e233f1341eaaa9276e3a679c89f1ef6f07e07ede10d25',
    'catalog_versions': {'Data': '2026.64.0.280', 'GRP': '280.1327372'},
}
_RESOURCE_LINES = (
    b'[Manifest]GET manifest pointer from https://assets.mtgarena.wizards.com/External_2026.64.0.14517.1329972-windows.mtga ...',
    b'[Manifest]Found 1 manifest metadata entries from pointer file.',
    b'[Manifest]Using manifest metadata: Automatic|Manifest_c98372b34219b5c4aa478e8bf296f5ee.mtga',
    b'[Manifest]Manifest download complete',
)
_GENERAL_RESOURCE_LINES = (
    b'[Manifest]Using manifest metadata: General|Manifest_Audio_47ac91270740b32d9181e19a86d537cd.mtga',
    b'[Manifest]Using manifest metadata: General|Manifest_Localization_b232d9b38053651edc055c44a14d7d4a.mtga',
)
_RESOURCE_MARKER = re.compile(rb'^\[Manifest\](GET manifest pointer from|Found .*?manifest metadata entries from pointer file\.|Using manifest metadata:|Manifest download complete)', re.M)


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


class _ResourceContext:
    def __init__(self, reducer, generation, prefix_hash):
        self.owner = weakref.ref(reducer)
        self.epoch = reducer._target_build_epoch
        self.generation = generation
        self.prefix_hash = prefix_hash

    def current(self, reducer):
        import copy
        if (self.owner() is not reducer or self.epoch is not reducer._target_build_epoch or
                type(self.generation) is not int or self.generation != reducer.generation or
                current_build(reducer) is None):
            return None
        return {**copy.deepcopy(RESOURCE), 'generation': self.generation,
            'startup_prefix_sha256': self.prefix_hash,
            'scope': 'archived_exact_build_official_resource_selection_not_runtime_attestation'}


def current_resource(reducer):
    """Separate exact-build resource witness; a build header alone is insufficient."""
    context = getattr(reducer, '_target_resource_context', None)
    return context.current(reducer) if type(context) is _ResourceContext else None


class TargetBuildObserver:
    """MP77 follower byte-observer protocol, only a finite version prelude."""
    def __init__(self):
        self.generation = None
        self.prefix = bytearray()
        self.failed_closed = False
        self.tail = b''
        self.header_start = None
        self.byte_end = 0
        self.resource_failed = False
        self.resource_markers = {}
        self.resource_selections = set()

    def begin(self, info):
        if info['reset']:
            self.prefix.clear()
            self.generation = info['generation']
            self.tail = b''
            self.header_start = None
            self.byte_end = 0
            self.resource_failed = False
            self.resource_markers = {}
            self.resource_selections = set()

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
        for match in _RESOURCE_MARKER.finditer(combined):
            absolute = start + match.start()
            if match.start() == 0 and start != 0:
                continue
            kind = match.group(1).split(b' ', 1)[0]
            if kind == b'Using':
                # Only three reviewed selections can occur. Unknown or late
                # selection starts remain in this bounded set and prevent any
                # later re-blessing, even if they have no complete line yet.
                if len(self.resource_selections) < 4:
                    self.resource_selections.add(absolute)
                else:
                    self.resource_failed = True
                continue
            previous = self.resource_markers.setdefault(kind, absolute)
            if previous != absolute:
                self.resource_failed = True
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
        reducer._target_resource_context = None
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
        if self.resource_failed:
            return
        positions = [headers[0].start()]
        prefix = bytes(self.prefix)
        for line in _RESOURCE_LINES:
            matches = list(re.finditer(rb'^' + re.escape(line) + rb'\r?\n', prefix, re.M))
            if len(matches) != 1:
                return
            positions.append(matches[0].start())
        if positions != sorted(set(positions)) or len(self.resource_markers) != 3:
            return
        selections = {positions[3]}
        for line in _GENERAL_RESOURCE_LINES:
            matches = list(re.finditer(rb'^' + re.escape(line) + rb'\r?\n', prefix, re.M))
            if len(matches) > 1:
                return
            if matches:
                position = matches[0].start()
                if not positions[1] < position < positions[2]:
                    return
                selections.add(position)
        if selections != self.resource_selections:
            return
        reducer._target_resource_context = _ResourceContext(reducer, self.generation,
            hashlib.sha256(prefix).hexdigest())
