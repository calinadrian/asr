"""Native roster lists, class restrictions and portrait cells for expanded races."""
import struct

import bloodelf_patch
from durotar_patch import Code
from race_catalog import ADDITIONS, PORTRAITS


def groups():
    alliance, horde = [1, 3, 4, 7], [2, 5, 6, 8, 10]
    for race in ADDITIONS:
        if race.faction in ('alliance', 'neutral'):
            alliance.append(race.id)
        if race.faction in ('horde', 'neutral'):
            horde.append(race.id)
    return alliance, horde


def patch_picker(image, catalog, source_records):
    p = bloodelf_patch.PROFILE['picker']
    alliance, horde = groups()
    a, h = image.put(bytes(alliance), 1), image.put(bytes(horde), 1)
    code = (Code().raw('4883bd9007000002').jcc('ne', 'alliance')
            .raw('4883f8'+bytes([len(horde)]).hex()).jmp('test')
            .label('alliance').raw('4883f8'+bytes([len(alliance)]).hex())
            .label('test').jcc('e', p['loop_done']).jmp(p['loop_continue']))
    image.hook(p['hooks']['loop']['rva'], 10, image.code(code))
    code = (Code().raw('52').raw('4883bd9007000002').jcc('ne', 'alliance')
            .rel('488d15', h).jmp('get').label('alliance').rel('488d15', a)
            .label('get').raw('400fb63c02').raw('5a').jmp(p['hooks']['race']['rva']+8))
    image.hook(p['hooks']['race']['rva'], 8, image.code(code))
    # Include a new race iff its explicit template was already allowed. The
    # existing unlock filter after this bridge remains in charge of account rules.
    counts = struct.unpack('<11Q', image.read(p['counts'], 88))
    pointers = struct.unpack('<11Q', image.read(p['pointers'], 88))
    code = Code()
    for slot, (count, pointer) in enumerate(zip(counts, pointers)):
        allowed = list(image.read(pointer-image.base, count))
        if str(slot+1) in p['classes']:
            allowed.append(10)
        original = list(allowed)
        allowed += [race.id for race in ADDITIONS if race.template in original]
        target = image.put(bytes(allowed), 1)
        code.raw('83f8'+bytes([slot]).hex()).jcc('ne', f'next{slot}')
        code.raw('bb'+struct.pack('<I', len(allowed)).hex()).rel('4c8d35', target).jmp('done')
        code.label(f'next{slot}')
    # The native caller checks class <= 11 before entering this hook.
    code.raw('bb01000000').rel('4c8d35', image.put(b'\x01', 1))
    code.label('done').jmp(p['hooks']['allowed']['rva']+25)
    image.hook(p['hooks']['allowed']['rva'], 25, image.code(code))
    code = Code()
    for race in (*ADDITIONS,):
        x, y = PORTRAITS[race.id]
        xy = image.put(struct.pack('<f', float(x)), 4)
        code.raw('4080ff'+bytes([race.id]).hex()).jcc('ne', f'next{race.id}')
        code.rel('f30f1005', xy).raw('b8'+struct.pack('<I', y).hex()).jmp(p['portrait_ready'])
        code.label(f'next{race.id}')
    x, y = PORTRAITS[10]
    xy = image.put(struct.pack('<f', float(x)), 4)
    code.raw('4080ff0a').jcc('ne', 'legacy').rel('f30f1005', xy)
    code.raw('b8'+struct.pack('<I', y).hex()).jmp(p['portrait_ready'])
    code.label('legacy').raw(p['hooks']['portrait']['before']).jmp(p['hooks']['portrait']['rva']+9)
    image.hook(p['hooks']['portrait']['rva'], 9, image.code(code))
    # Reviewed Bevy 0.18.1 Node layout, confirmed by native reflected-field
    # accessors: width +0x88, row_gap +0x140, flex_wrap +0x174. The Node starts
    # at rbp+0x838. Keep faction groups, with four icons per row.
    site = 0x1fbdf3
    original = bytes.fromhex('4c89ad30080000')
    if image.read(site, len(original)) != original:
        raise ValueError('Unsupported native race row layout')
    # Constrain the row as well as enabling wrap; an auto-width flex child can
    # otherwise keep its entire intrinsic width and never reach the wrap edge.
    code = (Code().raw(original).raw('c685ac09000001')
            .raw('c785c008000001000000c785c408000000000443')
            .raw('c7857809000001000000c7857c09000000008040')
            .jmp(site+len(original)))
    image.hook(site, len(original), image.code(code))
