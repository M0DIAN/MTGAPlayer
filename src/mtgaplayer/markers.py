"""Harness-only visual identity protocol; no relation to MTGA object locations.

64 bits: object u16, layout u16, context-tag u16, checksum u16, big endian.
Magenta guard, 3px black/white cells, 12px high. A tag binds the frame to the
nonce, match/game, state and request. Duplicate/invalid markers are refused.
"""
import hashlib
import struct
import zlib

HEADER, DROP, PASS, SUBMIT = 65534, 65533, 65532, 65531
WIDTH, HEIGHT = 200, 12


def tag(nonce, view):
    text = '|'.join(str(x) for x in (nonce, view['match'], view['game'],
                                    view['state_version'], (view.get('request') or {}).get('id')))
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:2], 'big')


def payload(object_id, layout, context):
    data = struct.pack('>HHH', object_id, layout, context)
    return data + struct.pack('>H', zlib.crc32(data) & 65535)


def draw(canvas, x, y, object_id, layout, context):
    canvas.create_rectangle(x, y, x + WIDTH, y + HEIGHT, fill='#ff00ff', outline='')
    data = payload(object_id, layout, context)
    for bit in range(64):
        color = '#ffffff' if data[bit // 8] & (1 << (7 - bit % 8)) else '#000000'
        canvas.create_rectangle(x + 4 + bit * 3, y + 2, x + 7 + bit * 3, y + 10,
                                fill=color, outline='')


def locate(frame, expected_layout, expected_tag):
    width, height, pixels = frame
    found = {}
    def rgb(x, y):
        index = (y * width + x) * 4
        return pixels[index:index + 3]
    # Search pixel content, never infer coordinates from log object ordering.
    for y in range(height - HEIGHT):
        row = pixels[y * width * 4:(y + 1) * width * 4]
        start = 0
        while True:
            index = row.find(b'\xff\x00\xff', start)
            if index < 0:
                break
            start = index + 4
            if index % 4:
                continue
            x = index // 4
            if x + WIDTH > width or (x and rgb(x - 1, y) == b'\xff\x00\xff'):
                continue
            # Only the top edge, not every row in the 12px guard.
            if y and rgb(x, y - 1) == b'\xff\x00\xff':
                continue
            data = bytearray(8)
            good = True
            for bit in range(64):
                sample = rgb(x + 5 + bit * 3, y + 5)
                if sample not in (b'\x00\x00\x00', b'\xff\xff\xff'):
                    good = False
                    break
                if sample == b'\xff\xff\xff':
                    data[bit // 8] |= 1 << (7 - bit % 8)
            if not good:
                continue
            obj, layout, context, checksum = struct.unpack('>HHHH', data)
            if checksum != zlib.crc32(data[:6]) & 65535:
                continue
            if layout != expected_layout or context != expected_tag:
                raise ValueError('stale_visual_context')
            if obj in found:
                raise ValueError('ambiguous_visual_identity')
            found[obj] = (x + WIDTH // 2, y + HEIGHT // 2)
    if HEADER not in found:
        raise ValueError('harness_header_not_visible')
    return found
