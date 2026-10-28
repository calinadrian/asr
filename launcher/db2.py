"""Read retail WDC5 DB2 tables into {id: [field values]}.

Fields come back in table order as unsigned integers (arrays as lists); callers interpret signs,
floats and strings with the helpers below. Sparse (offset-map) tables and encrypted sections
are not supported: the former raises, the latter are skipped.
"""
import struct

HEADER = struct.Struct('<4sI128sIIIIIIIIIHHIIIIIII')
SECTION = struct.Struct('<QIIIIIIII')
STORAGE = struct.Struct('<HHIIIII')


class Table:
    def __init__(self, data):
        (magic, version, _, records, fields, record_size, _, self.table_hash, _, _, _, _, flags,
         id_index, total_fields, _, _, storage_size, common_size, pallet_size,
         sections) = HEADER.unpack_from(data)
        if magic != b'WDC5' or version != 5:
            raise ValueError('Not a WDC5 table')
        if flags & 1:
            raise ValueError('Sparse DB2 tables are not supported')
        self.data = data
        pos = HEADER.size
        heads = [SECTION.unpack_from(data, pos + i * SECTION.size) for i in range(sections)]
        pos += sections * SECTION.size + fields * 4
        storage = [STORAGE.unpack_from(data, pos + i * STORAGE.size) for i in range(total_fields)]
        pos += storage_size
        pallet = {}
        for i, (_, _, size, kind, *_) in enumerate(storage):
            if kind in (3, 4):
                pallet[i] = struct.unpack_from(f'<{size // 4}I', data, pos)
                pos += size
        common = {}
        for i, (_, _, size, kind, *_) in enumerate(storage):
            if kind == 2:
                pairs = struct.unpack_from(f'<{size // 4}I', data, pos)
                common[i] = dict(zip(pairs[::2], pairs[1::2]))
                pos += size
        self.rows = {}
        self.field_offsets = [offset // 8 for offset, *_ in storage]
        for key, start, count, strings, _, id_size, rel_size, _, copies in heads:
            body = data[start:start + count * record_size]
            if key and not any(body):
                continue  # encrypted section without its key
            after = start + count * record_size + strings
            ids = struct.unpack_from(f'<{id_size // 4}I', data, after) if id_size else None
            after += id_size
            copy = struct.unpack_from(f'<{copies * 2}I', data, after) if copies else ()
            after += copies * 8
            relation = {}
            if rel_size:
                entries = struct.unpack_from('<I', data, after)[0]
                for j in range(entries):
                    foreign, index = struct.unpack_from('<II', data, after + 12 + j * 8)
                    relation[index] = foreign
            for index in range(count):
                base = start + index * record_size
                record = int.from_bytes(data[base:base + record_size], 'little')
                values = []
                for f, (bit, bits, _, kind, v1, v2, v3) in enumerate(storage):
                    if kind == 0:
                        raw = (record >> bit) & ((1 << bits) - 1)
                        if bits > 32:
                            values.append([(raw >> (32 * k)) & 0xFFFFFFFF for k in range(bits // 32)])
                        else:
                            values.append(raw)
                    elif kind in (1, 5):
                        raw = (record >> bit) & ((1 << bits) - 1)
                        if kind == 5 and raw >> (bits - 1):
                            raw -= 1 << bits
                        values.append(raw)
                    elif kind == 2:
                        values.append(None)  # filled once the ID is known
                    elif kind == 3:
                        values.append(pallet[f][(record >> bit) & ((1 << bits) - 1)])
                    elif kind == 4:
                        slot = (record >> bit) & ((1 << bits) - 1)
                        values.append(list(pallet[f][slot * v3:slot * v3 + v3]))
                    else:
                        raise ValueError(f'Unsupported DB2 storage type {kind}')
                row_id = ids[index] if ids else values[id_index]
                for f, (*_, kind, v1, _, _) in enumerate(storage):
                    if kind == 2:
                        values[f] = common[f].get(row_id, v1)
                if index in relation:
                    values.append(relation[index])
                values.append(base)  # record position, for strings
                self.rows[row_id] = values
            for new, old in zip(copy[::2], copy[1::2]):
                if old in self.rows:
                    self.rows[new] = self.rows[old]

    def string(self, row, field):
        """A string field: its value is an offset from the field's own position."""
        values = self.rows[row]
        start = values[-1] + self.field_offsets[field] + values[field]
        end = self.data.index(b'\0', start)
        return self.data[start:end].decode('utf-8', 'replace')


def f32(value):
    return struct.unpack('<f', struct.pack('<I', value & 0xFFFFFFFF))[0]


def i32(value):
    return value - (1 << 32) if value >> 31 else value
