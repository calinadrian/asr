"""BLP2 textures: decode retail and 1.12 files to RGBA, encode 1.12 DXT1/DXT3 files with mipmaps.

Images are (width, height, bytearray RGBA). Decoding handles palettized (alpha depth 0/1/4/8),
DXT1/DXT3/DXT5 and uncompressed BGRA files.
"""
import struct

HEADER = struct.Struct('<4sIBBBBII16I16I')


def mip_count(data):
    return sum(1 for size in struct.unpack_from('<16I', data, 0x54) if size)


def decode(data, level=0):
    magic, kind, encoding, alpha_depth, alpha_type, _, width, height, *rest = HEADER.unpack_from(data)
    if magic != b'BLP2' or kind != 1:
        raise ValueError('Not a BLP2 texture')
    offsets, sizes = rest[:16], rest[16:]
    level = min(level, mip_count(data) - 1)
    w, h = max(width >> level, 1), max(height >> level, 1)
    raw = data[offsets[level]:offsets[level] + sizes[level]]
    if encoding == 1:
        palette = struct.unpack_from('<256I', data, HEADER.size)
        out = bytearray(w * h * 4)
        n = w * h
        for i in range(n):
            c = palette[raw[i]]
            out[4 * i:4 * i + 3] = bytes(((c >> 16) & 255, (c >> 8) & 255, c & 255))
            if alpha_depth == 8:
                a = raw[n + i]
            elif alpha_depth == 1:
                a = 255 if raw[n + i // 8] >> (i % 8) & 1 else 0
            elif alpha_depth == 4:
                a = (raw[n + i // 2] >> (4 * (i % 2)) & 15) * 17
            else:
                a = 255
            out[4 * i + 3] = a
        return w, h, out
    if encoding == 3:
        out = bytearray(raw[:w * h * 4])
        out[0::4], out[2::4] = raw[2:w * h * 4:4], raw[0:w * h * 4:4]
        return w, h, out
    if encoding != 2:
        raise ValueError(f'Unsupported BLP encoding {encoding}')
    fmt = 'dxt1' if alpha_type == 0 else 'dxt3' if alpha_type == 1 else 'dxt5'
    return w, h, decode_dxt(raw, w, h, fmt, alpha_depth)


def rgb565(c):
    r, g, b = c >> 11 & 31, c >> 5 & 63, c & 31
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)


def decode_dxt(raw, w, h, fmt, alpha_depth=0):
    out = bytearray(w * h * 4)
    step = 8 if fmt == 'dxt1' else 16
    pos = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            block = raw[pos:pos + step]
            pos += step
            if len(block) < step:
                return out
            alphas = None
            if fmt == 'dxt3':
                bits = int.from_bytes(block[:8], 'little')
                alphas = [(bits >> (4 * i) & 15) * 17 for i in range(16)]
                block = block[8:]
            elif fmt == 'dxt5':
                a0, a1 = block[0], block[1]
                table = [a0, a1] + ([(a0 * (7 - i) + a1 * i) // 7 for i in range(1, 7)] if a0 > a1 else
                                    [(a0 * (5 - i) + a1 * i) // 5 for i in range(1, 5)] + [0, 255])
                bits = int.from_bytes(block[2:8], 'little')
                alphas = [table[bits >> (3 * i) & 7] for i in range(16)]
                block = block[8:]
            c0, c1, bits = struct.unpack_from('<HHI', block)
            p0, p1 = rgb565(c0), rgb565(c1)
            if c0 > c1 or fmt != 'dxt1':
                colors = [p0 + (255,), p1 + (255,),
                          tuple((2 * a + b) // 3 for a, b in zip(p0, p1)) + (255,),
                          tuple((a + 2 * b) // 3 for a, b in zip(p0, p1)) + (255,)]
            else:
                colors = [p0 + (255,), p1 + (255,), tuple((a + b) // 2 for a, b in zip(p0, p1)) + (255,),
                          (0, 0, 0, 0 if alpha_depth else 255)]
            for i in range(16):
                x, y = bx + i % 4, by + i // 4
                if x < w and y < h:
                    px = list(colors[bits >> (2 * i) & 3])
                    if alphas is not None:
                        px[3] = alphas[i]
                    out[4 * (y * w + x):4 * (y * w + x) + 4] = bytes(px)
    return out


def resize(image, w, h):
    """Box-filtered resize; each output pixel averages the source pixels it covers."""
    sw, sh, src = image
    out = bytearray(w * h * 4)
    for y in range(h):
        y0, y1 = y * sh // h, max((y + 1) * sh // h, y * sh // h + 1)
        for x in range(w):
            x0, x1 = x * sw // w, max((x + 1) * sw // w, x * sw // w + 1)
            acc = [0, 0, 0, 0]
            for yy in range(y0, y1):
                row = 4 * yy * sw
                for xx in range(x0, x1):
                    p = row + 4 * xx
                    a = src[p + 3]
                    acc[0] += src[p] * a
                    acc[1] += src[p + 1] * a
                    acc[2] += src[p + 2] * a
                    acc[3] += a
            n = (y1 - y0) * (x1 - x0)
            o = 4 * (y * w + x)
            if acc[3]:
                out[o:o + 3] = bytes(min(255, round(acc[k] / acc[3])) for k in range(3))
            out[o + 3] = round(acc[3] / n)
    return w, h, out


def crop(image, x, y, w, h):
    sw, _, src = image
    out = bytearray()
    for row in range(y, y + h):
        out += src[4 * (row * sw + x):4 * (row * sw + x + w)]
    return w, h, out


def paste(base, image, x, y, blend=True):
    """Draw image onto base at (x, y), alpha-blended unless blend is False."""
    bw, bh, dst = base
    w, h, src = image
    for row in range(h):
        for col in range(w):
            s, d = 4 * (row * w + col), 4 * ((y + row) * bw + x + col)
            a = src[s + 3]
            if not blend or a == 255:
                dst[d:d + 4] = src[s:s + 4]
            elif a:
                for k in range(3):
                    dst[d + k] = (src[s + k] * a + dst[d + k] * (255 - a)) // 255
                dst[d + 3] = max(dst[d + 3], a)


def to565(px):
    return (px[0] >> 3) << 11 | (px[1] >> 2) << 5 | px[2] >> 3


def encode_block(pixels, dxt3):
    """One 4x4 block: endpoints on the bounding box diagonal, each pixel to its nearest colour."""
    lo = [min(p[k] for p in pixels) for k in range(3)]
    hi = [max(p[k] for p in pixels) for k in range(3)]
    c0, c1 = to565(hi), to565(lo)
    if c0 < c1:
        c0, c1 = c1, c0
    p0, p1 = rgb565(c0), rgb565(c1)
    palette = [p0, p1, tuple((2 * a + b) // 3 for a, b in zip(p0, p1)), tuple((a + 2 * b) // 3 for a, b in zip(p0, p1))]
    indices = 0
    if c0 != c1:
        for i, p in enumerate(pixels):
            best = min(range(4), key=lambda k: sum((p[j] - palette[k][j]) ** 2 for j in range(3)))
            indices |= best << (2 * i)
    color = struct.pack('<HHI', c0, c1, indices)
    if not dxt3:
        return color
    alpha = 0
    for i, p in enumerate(pixels):
        alpha |= (p[3] * 15 + 127) // 255 << (4 * i)
    return alpha.to_bytes(8, 'little') + color


def encode(image, alpha=None):
    """A 1.12 BLP2: DXT3 when the image has transparency (or alpha=True), DXT1 otherwise."""
    w, h, px = image
    if alpha is None:
        alpha = any(a < 255 for a in px[3::4])
    levels, level = [], image
    while True:
        levels.append(level)
        if level[0] == 1 and level[1] == 1:
            break
        level = resize(level, max(level[0] // 2, 1), max(level[1] // 2, 1))
    blobs = []
    for lw, lh, lp in levels:
        blob = bytearray()
        for by in range(0, lh, 4):
            for bx in range(0, lw, 4):
                pixels = []
                for i in range(16):
                    x, y = min(bx + i % 4, lw - 1), min(by + i // 4, lh - 1)
                    pixels.append(tuple(lp[4 * (y * lw + x):4 * (y * lw + x) + 4]))
                blob += encode_block(pixels, alpha)
        blobs.append(bytes(blob))
    offsets, sizes, pos = [], [], HEADER.size + 1024
    for blob in blobs:
        offsets.append(pos)
        sizes.append(len(blob))
        pos += len(blob)
    pad = [0] * (16 - len(blobs))
    head = HEADER.pack(b'BLP2', 1, 2, 8 if alpha else 0, 1 if alpha else 0, 1, w, h,
                       *(offsets + pad), *(sizes + pad))
    return head + bytes(1024) + b''.join(blobs)
