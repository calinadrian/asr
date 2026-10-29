"""Down-convert a retail character model (MD21 v274 + .skel + LOD 0 .skin) to a 1.12 MD20 v256 file.

Only what a 1.12 character needs is carried over: bones, the embedded sequences whose animation
IDs 1.12 knows, attachments, one embedded view, textures, materials and the texture weight and
transform tracks. Retail-only geosets are dropped or folded into the base mesh by `geosets`, and
body-textured vertices are moved from the retail character texture layout (2048x1024, face in
its own right-hand square) to the classic one (face strips at the bottom left).
Cameras, events, lights, ribbons and particles are not carried over.
"""
import struct

HEADER_SIZE = 0x144
IDENTITY = {12: struct.pack('<3f', 0, 0, 0), 16: struct.pack('<4f', 0, 0, 0, 1)}


def chunks(data):
    out, pos = {}, 0
    while pos + 8 <= len(data):
        tag, size = struct.unpack_from('<4sI', data, pos)
        out[tag.decode('latin-1')] = data[pos + 8:pos + 8 + size]
        pos += 8 + size
    return out


def arr(buf, off):
    return struct.unpack_from('<II', buf, off)


def comp_quat(raw):
    """A retail int16 quaternion as the four floats 1.12 bones use."""
    return struct.pack('<4f', *((v + 32768 if v < 0 else v - 32767) / 32767.0
                                for v in struct.unpack('<4h', raw)))


class Sequence:
    def __init__(self, buf, off, index):
        (self.id, self.variation, self.duration, self.speed, self.flags, self.frequency, _,
         self.replay_min, self.replay_max, blend_in, _) = struct.unpack_from('<HHIfIhHIIHH', buf, off)
        self.blend = blend_in
        self.bounds = buf[off + 32:off + 60]
        self.variation_next, self.alias_next = struct.unpack_from('<hH', buf, off + 60)
        self.index = index


class Writer:
    def __init__(self):
        self.data = bytearray(HEADER_SIZE)

    def put(self, blob, align=16):
        while len(self.data) % align:
            self.data.append(0)
        offset = len(self.data)
        self.data += blob
        return offset

    def array(self, header_off, count, blob, align=16):
        offset = self.put(blob, align) if count else 0
        struct.pack_into('<II', self.data, header_off, count, offset)
        return offset


class Converter:
    def __init__(self, model, skel, skin, name, keep_ids, geosets, playable, texture_files=None,
                 remap_body=True, texture_names=None):
        """model, skel, skin: retail file bytes. keep_ids: animation IDs to carry. geosets maps a
        retail geoset ID to its 1.12 ID (0 folds it into the base mesh) and leaves out the ones
        to drop. playable: a 1.12 PlayableAnimationLookup to reuse, as (fallback id, flags).
        texture_files maps retail-only texture types to a fixed 1.12 file; batches drawing any
        other retail-only type are dropped."""
        self.texture_files = texture_files or {}
        self.texture_names = texture_names or {}
        self.remap_body = remap_body
        self.usable = {0, 1, 2, 6, 8} | set(self.texture_files)
        self.m = model if model[:4] == b'MD20' else chunks(model)['MD21']
        self.version = struct.unpack_from('<I', self.m, 4)[0]
        if self.m[:4] != b'MD20' or self.version < 264:
            raise ValueError('Not a supported retail model (v264 or later)')
        # Trolls and many equipment models still embed their skeleton in MD20.
        if skel is None:
            sk = {}
            for tag, fields in {'SKB1': (0x2C, 0x34), 'SKS1': (0x14, 0x1C, 0x24),
                                'SKA1': (0xF0, 0xF8)}.items():
                buf = bytearray(self.m)
                for index, field in enumerate(fields):
                    struct.pack_into('<II', buf, 8 * index, *arr(self.m, field))
                sk[tag] = bytes(buf)
        else:
            sk = chunks(skel)
        self.bones_buf, self.seq_buf, self.att_buf = sk['SKB1'], sk['SKS1'], sk.get('SKA1', b'')
        self.skin = skin
        if skin[:4] != b'SKIN':
            raise ValueError('Not a retail skin')
        self.name, self.keep_ids, self.geosets, self.playable = name, keep_ids, geosets, playable
        self.report = {}

    # --- sequences -----------------------------------------------------------------------------

    def pick_sequences(self):
        count, off = arr(self.seq_buf, 8)
        seqs = [Sequence(self.seq_buf, off + 64 * i, i) for i in range(count)]

        def data_index(s):
            seen = set()
            while s.flags & 0x40 and s.index not in seen:
                seen.add(s.index)
                s = seqs[s.alias_next]
            return s.index if s.flags & 0x20 else None

        self.seqs, cursor = [], 0
        for s in seqs:
            if s.id not in self.keep_ids or data_index(s) is None:
                continue
            s.data = data_index(s)
            s.start, s.end = cursor, cursor + s.duration
            cursor = s.end + 1
            self.seqs.append(s)
        self.gloops = self.seq_buf[arr(self.seq_buf, 0)[1]:][:arr(self.seq_buf, 0)[0] * 4]
        self.report['sequences'] = len(self.seqs)

    # --- tracks --------------------------------------------------------------------------------

    def track(self, buf, off, size, value=bytes, identity=None):
        """A retail M2Track at buf[off] as (interp, gseq, ranges, timestamps, values) for 1.12."""
        interp, gseq, tn, to, vn, vo = struct.unpack_from('<HhIIII', buf, off)
        stored = 8 if value is comp_quat else size

        def keys(index):
            if index >= min(tn, vn):
                return []
            cn, co = arr(buf, to + 8 * index)
            n, o = arr(buf, vo + 8 * index)
            return [(struct.unpack_from('<I', buf, co + 4 * k)[0],
                     value(buf[o + stored * k:o + stored * k + stored])) for k in range(min(cn, n))]

        times, values, ranges = [], [], []
        if gseq >= 0:
            for t, v in keys(0):
                times.append(t)
                values.append(v)
            return interp, gseq, ranges, times, values
        per = [keys(s.data) for s in self.seqs]
        if not any(per):
            return interp, gseq, [], [], []
        for s, ks in zip(self.seqs, per):
            lo = len(times)
            if not ks:
                ks = [(0, identity if identity is not None else IDENTITY.get(size, bytes(size)))]
            for t, v in ks:
                times.append(s.start + t)
                values.append(v)
            ranges.append((lo, len(times) - 1))
        return interp, gseq, ranges, times, values

    def write_track(self, w, record, at, track):
        interp, gseq, ranges, times, values = track
        struct.pack_into('<Hh', w.data, record + at, interp, gseq)
        w.array(record + at + 4, len(ranges), b''.join(struct.pack('<II', *r) for r in ranges))
        w.array(record + at + 12, len(times), struct.pack(f'<{len(times)}I', *times))
        w.array(record + at + 20, len(values), b''.join(values), 4)

    # --- mesh ----------------------------------------------------------------------------------

    def build_view(self):
        m, sk = self.m, self.skin
        vn, vo = arr(sk, 4)
        lookup = struct.unpack_from(f'<{vn}H', sk, vo)
        indices = struct.unpack_from(f'<{arr(sk, 12)[0]}H', sk, arr(sk, 12)[1])
        props = sk[arr(sk, 20)[1]:][:vn * 4]
        sn, so = arr(sk, 28)
        bn, bo = arr(sk, 36)
        batches = [bytearray(sk[bo + 24 * i:bo + 24 * i + 24]) for i in range(bn)]
        tex_types = self.texture_types()
        tex_lookup = self.u16s(0x80)
        mn, mo = arr(m, 0x3C)
        # HD LOD skins address a different window in the global vertex array.
        # This field was a bone-count limit in old skins; retail uses it as
        # lodVertexBase. Ignoring it produces a valid-index but shredded mesh.
        vertex_base = struct.unpack_from('<I', sk, 44)[0] if self.version >= 272 else 0

        self.vertices, self.props, self.triangles, self.submeshes = bytearray(), bytearray(), [], []
        self.vertex_sources = []
        section_map, dropped = {}, {}
        for i in range(sn):
            rec = sk[so + 48 * i:so + 48 * i + 48]
            sid, level, vstart, vcount, istart, icount = struct.unpack_from('<6H', rec)
            new_id = self.geosets.get(sid)
            kinds = {tex_types.get(tex_lookup[struct.unpack_from('<H', b, 0x10)[0]])
                     for b in batches if struct.unpack_from('<H', b, 4)[0] == i}
            if new_id is None or not kinds & self.usable:
                dropped[sid] = dropped.get(sid, 0) + icount
                continue
            body = self.remap_body and 1 in kinds
            first = len(self.vertices) // 48
            for k in range(vstart, vstart + vcount):
                source_index = vertex_base + lookup[k]
                if source_index >= mn:
                    raise ValueError('Skin LOD vertex base indexes outside the model')
                vertex = bytearray(m[mo + 48 * source_index:mo + 48 * source_index + 48])
                if body:
                    u, v = struct.unpack_from('<2f', vertex, 32)
                    u, v = (u - 0.5, 0.625 + 0.375 * v) if u >= 0.5 else (u * 2, v)
                    struct.pack_into('<2f', vertex, 32, u, v)
                self.vertices += vertex
                self.vertex_sources.append(source_index)
                self.props += props[4 * k:4 * k + 4]
            tri_start = len(self.triangles)
            base = istart | level << 16
            tris = [indices[t] for t in range(base, base + icount)]
            if tris and not vstart <= min(tris) <= max(tris) < vstart + vcount:
                raise ValueError(f'Submesh {i} indexes outside its vertex range')
            self.triangles += [t - vstart + first for t in tris]
            if len(self.triangles) > 0xFFFF or len(self.vertices) // 48 > 0xFFFF:
                total = sum(c for s, c in self.index_counts().items() if self.geosets.get(s) is not None)
                raise ValueError(f'The kept geosets need {total} indices; 1.12 allows 65535')
            section = bytearray(rec[:32])
            struct.pack_into('<6H', section, 0, new_id, 0, first, vcount, tri_start, icount)
            section_map[i] = len(self.submeshes)
            self.submeshes.append(section)
        self.batches = []
        for b in batches:
            section = struct.unpack_from('<H', b, 4)[0]
            kind = tex_types.get(tex_lookup[struct.unpack_from('<H', b, 0x10)[0]])
            if section not in section_map or kind not in self.usable:
                continue
            struct.pack_into('<HH', b, 4, section_map[section], section_map[section])
            struct.pack_into('<H', b, 2, 0)  # retail shader combos mean nothing to 1.12
            struct.pack_into('<H', b, 0x0E, 1)
            struct.pack_into('<H', b, 0x12, 0)
            self.batches.append(b)
        self.report.update(vertices=len(self.vertices) // 48, indices=len(self.triangles),
                           submeshes=len(self.submeshes), batches=len(self.batches),
                           dropped=dict(sorted(dropped.items())))

    def index_counts(self):
        """Indices per retail geoset ID in the skin."""
        sn, so = arr(self.skin, 28)
        counts = {}
        for i in range(sn):
            sid, _, _, _, _, icount = struct.unpack_from('<6H', self.skin, so + 48 * i)
            counts[sid] = counts.get(sid, 0) + icount
        return counts

    def u16s(self, header):
        n, o = arr(self.m, header)
        return list(struct.unpack_from(f'<{n}H', self.m, o))

    def texture_types(self):
        n, o = arr(self.m, 0x50)
        result = {}
        for i in range(n):
            kind, _, length, pos = struct.unpack_from('<IIII', self.m, o + 16 * i)
            result[i] = kind if kind != 0 or i in self.texture_names or (
                length and self.m[pos:pos + length].rstrip(b'\0')) else None
        return result

    # --- output --------------------------------------------------------------------------------

    def convert(self):
        self.pick_sequences()
        self.build_view()
        m, w = self.m, Writer()
        d = w.data
        d[0:8] = b'MD20' + struct.pack('<I', 256)
        w.array(0x08, len(self.name) + 1, self.name.encode() + b'\0')
        struct.pack_into('<I', d, 0x10, 0)
        w.array(0x14, len(self.gloops) // 4, self.gloops)

        seq_blob, by_id = bytearray(), {}
        for n, s in enumerate(self.seqs):
            by_id.setdefault(s.id, []).append(n)
        for n, s in enumerate(self.seqs):
            chain = by_id[s.id]
            nxt = chain[chain.index(n) + 1] if chain.index(n) + 1 < len(chain) else -1
            seq_blob += struct.pack('<HHIIfIhHIII', s.id, chain.index(n), s.start, s.end, s.speed,
                                    s.flags & ~0x40 | 0x20, s.frequency, 0, s.replay_min,
                                    s.replay_max, s.blend)
            seq_blob += s.bounds + struct.pack('<hH', nxt, n)
        w.array(0x1C, len(self.seqs), seq_blob)
        top = max(by_id, default=-1) + 1
        w.array(0x24, top, struct.pack(f'<{top}H', *(by_id[i][0] if i in by_id else 0xFFFF
                                                     for i in range(top))))
        play = [(f if f in by_id else 0, flags if f in by_id else 0) for f, flags in self.playable]
        w.array(0x2C, len(play), b''.join(struct.pack('<hh', *p) for p in play))

        bn, bo = arr(self.bones_buf, 0)
        bones_off = w.array(0x34, bn, bytes(108 * bn))
        for i in range(bn):
            src = bo + 88 * i
            rec = bones_off + 108 * i
            d[rec:rec + 12] = self.bones_buf[src:src + 12]
            self.write_track(w, rec, 12, self.track(self.bones_buf, src + 16, 12))
            self.write_track(w, rec, 40, self.track(self.bones_buf, src + 36, 16, comp_quat,
                                                   struct.pack('<4f', 0, 0, 0, 1)))
            self.write_track(w, rec, 68, self.track(self.bones_buf, src + 56, 12,
                                                   identity=struct.pack('<3f', 1, 1, 1)))
            d[rec + 96:rec + 108] = self.bones_buf[src + 76:src + 88]
        kn, ko = arr(self.bones_buf, 8)
        w.array(0x3C, kn, self.bones_buf[ko:ko + 2 * kn])
        w.array(0x44, len(self.vertices) // 48, bytes(self.vertices))

        view = w.array(0x4C, 1, bytes(44))
        nv = len(self.vertices) // 48
        w.array(view, nv, struct.pack(f'<{nv}H', *range(nv)))
        w.array(view + 8, len(self.triangles), struct.pack(f'<{len(self.triangles)}H', *self.triangles))
        w.array(view + 16, nv, bytes(self.props))
        w.array(view + 24, len(self.submeshes), b''.join(self.submeshes))
        w.array(view + 32, len(self.batches), b''.join(self.batches))
        struct.pack_into('<I', d, view + 40, 256)

        cn, co = arr(m, 0x48)
        colors = w.array(0x54, cn, bytes(56 * cn))
        for i in range(cn):
            self.write_track(w, colors + 56 * i, 0, self.track(m, co + 40 * i, 12))
            self.write_track(w, colors + 56 * i, 28, self.track(m, co + 40 * i + 20, 2))
        types = self.texture_types()
        tex = bytearray()
        empty = w.put(b'\0')
        for i in range(len(types)):
            texture_flags = struct.unpack_from('<I', m, arr(m, 0x50)[1]+16*i+4)[0]
            if i in self.texture_names:
                name = self.texture_names[i].encode() + b'\0'
                tex += struct.pack('<IIII', 0, texture_flags, len(name), w.put(name, 1))
            elif types[i] in self.texture_files:
                name = self.texture_files[types[i]].encode() + b'\0'
                tex += struct.pack('<IIII', 0, texture_flags, len(name), w.put(name, 1))
            elif types[i] == 0:
                _, flags, length, pos = struct.unpack_from('<IIII', m, arr(m, 0x50)[1] + 16 * i)
                name = m[pos:pos + length]
                tex += struct.pack('<IIII', 0, flags, len(name), w.put(name, 1))
            else:
                tex += struct.pack('<IIII', types[i] if types[i] in (1, 2, 6, 8) else 1,
                                   texture_flags, 1, empty)
        w.array(0x5C, len(types), bytes(tex))

        tn, to = arr(m, 0x58)
        weights = w.array(0x64, tn, bytes(28 * tn))
        for i in range(tn):
            self.write_track(w, weights + 28 * i, 0, self.track(m, to + 20 * i, 2,
                                                                identity=struct.pack('<h', 0x7FFF)))
        w.array(0x6C, 0, b'')  # texture flipbooks
        tn, to = arr(m, 0x60)
        transforms = w.array(0x74, tn, bytes(84 * tn))
        for i in range(tn):
            for k, (size, ident) in enumerate(((12, None), (16, None), (12, struct.pack('<3f', 1, 1, 1)))):
                self.write_track(w, transforms + 84 * i, 28 * k,
                                 self.track(m, to + 60 * i + 20 * k, size, identity=ident))
        repl = [0xFFFF] * 14
        for i in range(len(types) - 1, -1, -1):
            if types[i] in (1, 2, 6, 8):
                repl[types[i]] = i
        w.array(0x7C, len(repl), struct.pack(f'<{len(repl)}H', *repl))
        mn, mo = arr(m, 0x70)
        mats = b''.join(struct.pack('<HH', f & 0x1F, b) for f, b in
                        (struct.unpack_from('<HH', m, mo + 4 * i) for i in range(mn)))
        w.array(0x84, mn, mats)
        for header, src in ((0x8C, 0x78), (0x94, 0x80), (0xA4, 0x90), (0xAC, 0x98)):
            values = self.u16s(src)
            w.array(header, len(values), struct.pack(f'<{len(values)}H', *values))
        w.array(0x9C, 1, struct.pack('<H', 0))
        d[0xB4:0xEC] = m[0xA0:0xD8]
        # Retail's global box includes excluded Demon Hunter and effect geosets.
        # The portrait booth aims at this box's center; copying it can put the
        # entire retained humanoid below the camera. Bound the mesh we actually emit.
        positions = list(struct.iter_unpack('<3f', b''.join(
            self.vertices[i:i+12] for i in range(0, len(self.vertices), 48))))
        if positions:
            low = [min(p[i] for p in positions) for i in range(3)]
            high = [max(p[i] for p in positions) for i in range(3)]
            radius = sum(((b-a)*0.5)**2 for a, b in zip(low, high))**0.5
            struct.pack_into('<7f', d, 0xB4, *low, *high, radius)
        for header, src, size in ((0xEC, 0xD8, 2), (0xF4, 0xE0, 12), (0xFC, 0xE8, 12)):
            n, o = arr(m, src)
            w.array(header, n, m[o:o + n * size])

        if self.att_buf:
            an, ao = arr(self.att_buf, 0)
            atts = w.array(0x104, an, bytes(48 * an))
            for i in range(an):
                src = ao + 40 * i
                ident, bone = struct.unpack_from('<IH', self.att_buf, src)
                struct.pack_into('<IHH', d, atts + 48 * i, ident, bone, 0)
                d[atts + 48 * i + 8:atts + 48 * i + 20] = self.att_buf[src + 8:src + 20]
            ln, lo = arr(self.att_buf, 8)
            w.array(0x10C, ln, self.att_buf[lo:lo + 2 * ln])
        return bytes(d)


def preserve_body_palette(data, converter):
    """Keep oral/detail UVs that overlap the destination's legacy face strips.

    Tauren female has two dark oral triangles in the old face-strip rectangle
    of retail's *left* body atlas. Packing the face there overwrites them with
    an unused white area. The extended skin-extra atlas stores fur on its left
    and the untouched retail body half on its right. Split only those triangles
    onto texture type 8; the rest of the face remains customizable type 1.
    """
    vertices = bytearray(converter.vertices)
    props = bytearray(converter.props)
    old_triangles = converter.triangles
    types = converter.texture_types()
    lookup = converter.u16s(0x80)
    extra_combo = next((i for i, t in enumerate(lookup) if types.get(t) == 8), None)
    if extra_combo is None:
        raise ValueError('Body-palette preservation requires a skin-extra texture')
    _, source_at = arr(converter.m, 0x3C)
    source_uv = [struct.unpack_from('<2f', converter.m, source_at+48*i+32)
                 for i in converter.vertex_sources]
    triangles, sections, batches = [], [], []
    count_details = 0
    for section_index, old in enumerate(converter.submeshes):
        sid, _, first, count, start, length = struct.unpack_from('<6H', old)
        old_batches = [b for b in converter.batches if struct.unpack_from('<H', b, 4)[0] == section_index]
        kinds = {types.get(lookup[struct.unpack_from('<H', b, 16)[0]]) for b in old_batches}
        if 8 in kinds:
            texture_index = lookup[extra_combo]
            flags = struct.unpack_from('<I', converter.m, arr(converter.m, 0x50)[1]+16*texture_index+4)[0]
            for i in range(first, first+count):
                u = struct.unpack_from('<f', vertices, 48*i+32)[0]
                if flags & 1:
                    u %= 1.0
                struct.pack_into('<f', vertices, 48*i+32, u*0.5)
        ordinary, details = [], []
        for at in range(start, start+length, 3):
            tri = old_triangles[at:at+3]
            uv = [source_uv[i] for i in tri]
            if 1 in kinds and all(u < 0.5 for u, _ in uv) and any(u < 0.25 and v > 0.625 for u, v in uv):
                details.extend(tri)
            else:
                ordinary.extend(tri)
        new = bytearray(old)
        struct.pack_into('<HH', new, 8, len(triangles), len(ordinary))
        main_index = len(sections)
        sections.append(new)
        triangles.extend(ordinary)
        for old_batch in old_batches:
            batch = bytearray(old_batch)
            struct.pack_into('<HH', batch, 4, main_index, main_index)
            batches.append(batch)
        if details:
            first_new = len(vertices)//48
            copies = {}
            detail_indices = []
            for old_index in details:
                if old_index not in copies:
                    index = len(vertices)//48
                    copies[old_index] = index
                    vertex = bytearray(converter.vertices[48*old_index:48*old_index+48])
                    u, v = source_uv[old_index]
                    struct.pack_into('<2f', vertex, 32, 0.5+u, v)
                    vertices.extend(vertex)
                    props.extend(converter.props[4*old_index:4*old_index+4])
                detail_indices.append(copies[old_index])
            detail_section = bytearray(old)
            struct.pack_into('<6H', detail_section, 0, sid, 0, first_new, len(copies),
                             len(triangles), len(detail_indices))
            detail_index = len(sections)
            sections.append(detail_section)
            triangles.extend(detail_indices)
            batch = bytearray(old_batches[0])
            struct.pack_into('<HH', batch, 4, detail_index, detail_index)
            struct.pack_into('<H', batch, 16, extra_combo)
            batches.append(batch)
            count_details += len(details)//3
    n = len(vertices)//48
    if n > 65535 or len(triangles) > 65535:
        raise ValueError('Body-palette preservation exceeds the legacy view limit')
    w = Writer()
    w.data = bytearray(data)
    w.array(0x44, n, vertices)
    view = w.array(0x4C, 1, bytes(44))
    w.array(view, n, struct.pack(f'<{n}H', *range(n)))
    w.array(view+8, len(triangles), struct.pack(f'<{len(triangles)}H', *triangles))
    w.array(view+16, n, props)
    w.array(view+24, len(sections), b''.join(sections))
    w.array(view+32, len(batches), b''.join(batches))
    struct.pack_into('<I', w.data, view+40, 256)
    converter.report.update(vertices=n, submeshes=len(sections), batches=len(batches),
                            preserved_body_palette_triangles=count_details)
    return bytes(w.data)
