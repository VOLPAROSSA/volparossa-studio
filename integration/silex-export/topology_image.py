# SPDX-License-Identifier: GPL-3.0-only
"""Make a reproducible RGB calibration chart for the Silex file picker."""
from hashlib import shake_256
import os
import struct
import zlib

NAME = 'studio-topology.png'
WIDTH, HEIGHT = 1024, 768


def chart():
    # Alternating warm/cool tiles and fine stippling exercise independent colour
    # channels. Every byte is part of a normal compressed, rendered PNG image.
    noise = shake_256(b'VOLPAROSSA Studio colour chart v1').digest(WIDTH * HEIGHT * 3)
    rows = bytearray()
    for y in range(HEIGHT):
        rows.append(0)  # PNG filter None
        for x in range(WIDTH):
            offset = (y * WIDTH + x) * 3
            warm = ((x // 128 + y // 96) % 2) * 128
            rows.extend((warm + (noise[offset] & 127), (128 - warm) + (noise[offset + 1] & 127),
                         (y // 192 % 2) * 128 + (noise[offset + 2] & 127)))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))

    header = struct.pack('>IIBBBBB', WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(rows, level=6)) + chunk(b'IEND', b'')


def write_chart(temporary):
    path = temporary / NAME
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(chart())
    return path
