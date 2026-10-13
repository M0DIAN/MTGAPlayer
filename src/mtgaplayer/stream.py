"""Strict normalized NDJSON stream, not an Arena raw-log decoder.

Follower reset/prefix/anchor logic adapted from mtga-play 0.4.6 arena_log.py,
MIT Copyright (c) 2026 MODIAN. See THIRD_PARTY.md and LICENSES/mtga-play-MIT.txt.
Unlike the original brace framer, malformed *complete lines* are ordered errors.
"""
import json
from pathlib import Path


class FramingError(ValueError):
    pass


class LineFramer:
    def __init__(self, limit=1024 * 1024):
        self.buffer = bytearray()
        self.limit = limit
        self.discard = False

    def feed(self, data):
        result = []
        # A partial record waits; overlong records fail immediately and discard
        # through their newline, never interpret an arbitrary tail as a baseline.
        for part in data.splitlines(keepends=True):
            ended = part.endswith(b'\n')
            if not self.discard:
                self.buffer.extend(part)
                if len(self.buffer) > self.limit:
                    result.append(FramingError('record_size'))
                    self.buffer.clear()
                    self.discard = True
            if ended:
                if not self.discard and self.buffer.strip():
                    try:
                        obj = json.loads(self.buffer)
                        if not isinstance(obj, dict):
                            raise ValueError()
                        result.append(obj)
                    except (ValueError, UnicodeError):
                        result.append(FramingError('malformed_complete_record'))
                self.buffer.clear()
                self.discard = False
        return result

    @property
    def partial(self):
        return bool(self.buffer) or self.discard


class Follower:
    def __init__(self, path):
        self.path = Path(path)
        self.identity = None
        self.offset = self.generation = 0
        self.prefix = self.anchor = b''
        self.anchor_start = 0
        self.framer = LineFramer()

    def poll(self):
        # fstat the opened handle, avoiding stat/open replacement races.
        import os
        with self.path.open('rb') as stream:
            stat = os.fstat(stream.fileno())
            identity = (stat.st_dev, stat.st_ino) if stat.st_ino else (stat.st_ctime_ns,)
            reset = identity != self.identity or stat.st_size < self.offset
            if not reset and self.offset:
                reset = stream.read(len(self.prefix)) != self.prefix
                stream.seek(self.anchor_start)
                reset |= stream.read(len(self.anchor)) != self.anchor
            if reset:
                self.identity, self.offset = identity, 0
                self.generation += 1
                self.framer = LineFramer()
            stream.seek(self.offset)
            records = []
            remaining = stat.st_size - self.offset
            while remaining > 0:
                data = stream.read(min(65536, remaining))
                if not data:
                    break
                records.extend(self.framer.feed(data))
                self.offset += len(data)
                remaining -= len(data)
            stream.seek(0)
            self.prefix = stream.read(min(256, self.offset))
            self.anchor_start = max(0, self.offset - 64)
            stream.seek(self.anchor_start)
            self.anchor = stream.read(self.offset - self.anchor_start)
        return reset, records
