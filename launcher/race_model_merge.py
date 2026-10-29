"""Merge converted customization attachments into one legacy character view.

Retail customization meshes carry a subset skeleton. Key bones bind to the
character's key bones; exact pivots identify unnamed bones. Accessory-only
secondary bones follow their nearest mapped ancestor (no independent physics).
The character's animation tracks and equipment attachments remain authoritative.
"""
import math
import struct

from retail_m2 import Writer, arr


def merge(body, accessory, geoset):
    bn, bo = arr(body, 0x34)
    an, ao = arr(accessory, 0x34)
    keys, pivots = {}, {}
    for i in range(bn):
        key = struct.unpack_from('<i', body, bo+108*i)[0]
        if key >= 0 and i < 256:
            keys.setdefault(key, i)
        pivots.setdefault(body[bo+108*i+96:bo+108*i+108], []).append(i)
    bone_map, inherited = {}, []
    for i in range(an):
        at = ao+108*i
        key = struct.unpack_from('<i', accessory, at)[0]
        parent = struct.unpack_from('<h', accessory, at+8)[0]
        matches = [v for v in pivots.get(accessory[at+96:at+108], []) if v < 256]
        if key in keys:
            bone_map[i] = keys[key]
        elif len(matches) == 1:
            bone_map[i] = matches[0]
        elif parent in bone_map:
            bone_map[i] = bone_map[parent]
            inherited.append(i)
        elif matches:
            bone_map[i] = matches[0]
        else:
            raise ValueError(f'Customization bone {i} has no character binding')
    vn, vo = arr(body, 0x44)
    en, eo = arr(accessory, 0x44)
    vertices = bytearray(body[vo:vo+vn*48])
    extra_vertices = bytearray(accessory[eo:eo+en*48])
    for i in range(en):
        for k, weight in enumerate(extra_vertices[48*i+12:48*i+16]):
            if weight:
                old = extra_vertices[48*i+16+k]
                if old not in bone_map:
                    raise ValueError('Customization vertex has an absent bone')
                extra_vertices[48*i+16+k] = bone_map[old]
    vertices += extra_vertices
    _, bv = arr(body, 0x4C)
    _, ev = arr(accessory, 0x4C)
    tn, to = arr(body, bv+8)
    etn, eto = arr(accessory, ev+8)
    if vn+en > 65535 or tn+etn > 65535:
        raise ValueError('Merged customization exceeds the legacy view limit')
    w = Writer()
    w.data = bytearray(body)
    w.array(0x44, vn+en, vertices)
    # Relocate each accessory texture's embedded filename before joining tables.
    textures = bytearray()
    bt, bto = arr(body, 0x5C)
    at, ato = arr(accessory, 0x5C)
    textures += body[bto:bto+bt*16]
    for i in range(at):
        kind, flags, length, offset = struct.unpack_from('<4I', accessory, ato+16*i)
        name = accessory[offset:offset+length]
        textures += struct.pack('<4I', kind, flags, length, w.put(name, 1) if length else 0)
    w.array(0x5C, bt+at, textures)
    bm, bmo = arr(body, 0x84)
    am, amo = arr(accessory, 0x84)
    w.array(0x84, bm+am, body[bmo:bmo+bm*4]+accessory[amo:amo+am*4])
    bl, blo = arr(body, 0x94)
    al, alo = arr(accessory, 0x94)
    extra_lookup = [bt+v for v in struct.unpack_from(f'<{al}H', accessory, alo)]
    w.array(0x94, bl+al, body[blo:blo+bl*2]+struct.pack(f'<{al}H', *extra_lookup))
    bbl, bblo = arr(body, 0x8C)
    ebl, eblo = arr(accessory, 0x8C)
    extra_bones = [bone_map[v] for v in struct.unpack_from(f'<{ebl}H', accessory, eblo)]
    w.array(0x8C, bbl+ebl, body[bblo:bblo+bbl*2]+struct.pack(f'<{ebl}H', *extra_bones))
    # Keep one stable UV set, full opacity and no texture transform for extras.
    # Their body/hair textures are supplied by the ordinary native selectors.
    props = b''
    for model, view, count in ((body, bv, vn), (accessory, ev, en)):
        _, offset = arr(model, view+16)
        props += model[offset:offset+count*4]
    sn, so = arr(body, bv+24)
    esn, eso = arr(accessory, ev+24)
    submeshes = bytearray(body[so:so+sn*32])
    for i in range(esn):
        sub = bytearray(accessory[eso+32*i:eso+32*(i+1)])
        _, _, first, count, start, length = struct.unpack_from('<6H', sub)
        struct.pack_into('<6H', sub, 0, geoset, 0, first+vn, count, start+tn, length)
        bone_start = struct.unpack_from('<H', sub, 14)[0]
        struct.pack_into('<H', sub, 14, bone_start+bbl)
        submeshes += sub
    batches_n, batches_o = arr(body, bv+32)
    ebn, ebo = arr(accessory, ev+32)
    batches = bytearray(body[batches_o:batches_o+batches_n*24])
    for i in range(ebn):
        batch = bytearray(accessory[ebo+24*i:ebo+24*(i+1)])
        sub, sub2 = struct.unpack_from('<HH', batch, 4)
        material = struct.unpack_from('<H', batch, 10)[0]
        tex = struct.unpack_from('<H', batch, 16)[0]
        struct.pack_into('<HHhH', batch, 4, sub+sn, sub2+sn, -1, material+bm)
        struct.pack_into('<4H', batch, 16, tex+bl, 0, 0, 0)
        batches += batch
    triangles = list(struct.unpack_from(f'<{tn}H', body, to))
    triangles += [vn+v for v in struct.unpack_from(f'<{etn}H', accessory, eto)]
    view = w.array(0x4C, 1, bytes(44))
    w.array(view, vn+en, struct.pack(f'<{vn+en}H', *range(vn+en)))
    w.array(view+8, tn+etn, struct.pack(f'<{tn+etn}H', *triangles))
    w.array(view+16, vn+en, props)
    w.array(view+24, sn+esn, submeshes)
    w.array(view+32, batches_n+ebn, batches)
    struct.pack_into('<I', w.data, view+40, 256)
    positions = [struct.unpack_from('<3f', vertices, i*48) for i in range(vn+en)]
    low = [min(v[k] for v in positions) for k in range(3)]
    high = [max(v[k] for v in positions) for k in range(3)]
    struct.pack_into('<7f', w.data, 0xB4, *low, *high, math.dist(low, high)/2)
    return bytes(w.data), dict(bones_following_ancestor=inherited, vertices=en, indices=etn)
