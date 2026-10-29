"""Route the native AddOns folder action to ASR's embedded addon manager.

Only one RIP-relative string reference changes. The original function's unwind
metadata and process-launch logic remain intact. Unknown helper layouts fail closed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

SECTION = b'.asradd\0'
PAYLOAD = b'ASR addon manager v1\0'.ljust(32, b'\0') + b'ASRAddOn\0'
PROFILES = (
    (0x3af50, 0x3b379, 0x3b0ad, '488d156c271406', 'c66cf6041f9c84e6833988167ee97d8426cf71c65e73f0482ffc677e02333370'),
    (0x2210f0, 0x221519, 0x22124d, '488d151c3cfe05', '958fdc0b8773bc7f5d5b84927ccbe946919c5e48d773da0faaae9ac1a5c33c1f'),
    (0x2c0d70, 0x2c1199, 0x2c0ecd, '488d156c8af405', 'c5f1514d5c9424cdd1a82e5b99062222fd085cc60a1d25e2b5ecaf085a5228b8'),
)
LABELS = dict(zip([
    'Open AddOns Folder', 'Otwórz folder dodatków', 'Otevřít složku doplňků', 'AddOn-Ordner öffnen',
    'Abrir pasta de addons', 'Abrir carpeta de accesorios', 'Ouvrir le dossier AddOns', 'Deschide folderul AddOns',
    'Eklenti Klasörünü Aç', 'Открыть папку AddOns', 'Відкрити теку AddOns', '打开插件文件夹', 'AddOnsフォルダーを開く', '애드온 폴더 열기',
], [
    'Manage AddOns', 'Zarządzaj dodatkami', 'Správa doplňků', 'AddOns verwalten', 'Gerir addons', 'Gestionar addons',
    'Gérer les AddOns', 'Gestionează AddOns', 'Eklentileri yönet', 'Управлять AddOns', 'Керувати AddOns', '管理插件', 'AddOns管理', '애드온 관리',
]))


def apply(source):
    data = bytearray(source)
    pe = struct.unpack_from('<I', data, 60)[0]
    optional = pe + 24
    if data[pe:pe+4] != b'PE\0\0' or struct.unpack_from('<H', data, optional)[0] != 0x20b:
        raise ValueError('Expected a native 64-bit Windows game')
    count = struct.unpack_from('<H', data, pe+6)[0]
    table = optional + struct.unpack_from('<H', data, pe+20)[0]
    sections = []
    for i in range(count):
        at = table+i*40
        name = bytes(data[at:at+8])
        virtual, va, size, raw = struct.unpack_from('<IIII', data, at+8)
        sections.append((name, va, raw, size, virtual))

    def offset(rva):
        for _, va, raw, size, _ in sections:
            if va <= rva < va+size:
                return raw+rva-va
        raise ValueError('Unsupported native addon-manager address')

    existing = [s for s in sections if s[0] == SECTION]
    if len(existing) > 1:
        raise ValueError('Duplicate addon manager sections')
    if existing:
        _, va, raw, size, virtual = existing[0]
        if virtual != len(PAYLOAD) or data[raw:raw+virtual] != PAYLOAD:
            raise ValueError('Unknown addon manager section')
    else:
        section_alignment, file_alignment = struct.unpack_from('<II', data, optional+32)
        align = lambda value, boundary: (value+boundary-1)//boundary*boundary
        va = align(max(v+max(s, z) for _, v, _, s, z in sections), section_alignment)
        raw = align(len(data), file_alignment)
        size = align(len(PAYLOAD), file_alignment)
        header = table+count*40
        if header+40 > min(s[2] for s in sections) or any(data[header:header+40]):
            raise ValueError('No room for the addon manager PE section')

    selected = None
    for start, end, hook, original, digest in PROFILES:
        try:
            at = offset(start); pos = offset(hook)
        except ValueError:
            continue
        old = bytes.fromhex(original)
        replacement = old[:3] + struct.pack('<i', va+32-(hook+7))
        if data[pos:pos+7] not in (old, replacement) or (not existing and data[pos:pos+7] != old):
            continue
        function = bytearray(data[at:at+end-start])
        function[hook-start:hook-start+7] = old
        if hashlib.sha256(function).hexdigest() == digest:
            selected = (pos, replacement)
            break
    if selected is None:
        raise ValueError('Unsupported native AddOns handler; analyze this build first')

    # Keep every embedded JSON blob's length and all native pointers unchanged.
    def label(match):
        value = json.loads(match[2])
        if value in LABELS:
            new = json.dumps(LABELS[value], ensure_ascii=False).encode('utf-8')
        elif value in LABELS.values():
            return match[0]
        else:
            raise ValueError('Unknown AddOns button translation')
        if len(new) > len(match[2]):
            raise ValueError('Addon button translation exceeds its reserved slot')
        return match[1]+new+b' '*(len(match[2])-len(new))
    data = bytearray(re.sub(rb'("options.open_addons_folder": )("(?:[^"\\]|\\.)*")', label, data))
    # Expanded race locales contain copies of the same translations. The
    # original native regions still own exactly fourteen entries.
    native_labels = sum(data[raw:raw+size].count(b'"options.open_addons_folder": ')
                        for name, _, raw, size, _ in sections if not name.startswith(b'.asr'))
    if native_labels != 14:
        raise ValueError('Missing AddOns button translations')
    old_note = b'"Put each addon\'s folder (made for WoW 1.12) in {path}"'
    new_note = b'"Add or remove addons. Changes apply next run."'
    data = data.replace(old_note, new_note+b' '*(len(old_note)-len(new_note)))

    if not existing:
        data.extend(b'\0'*(raw+size-len(data)))
        data[raw:raw+len(PAYLOAD)] = PAYLOAD
        struct.pack_into('<8sIIIIIIHHI', data, header, SECTION, len(PAYLOAD), va, size, raw, 0, 0, 0, 0, 0x40000040)
        struct.pack_into('<H', data, pe+6, count+1)
        struct.pack_into('<I', data, optional+56, align(va+len(PAYLOAD), section_alignment))
        struct.pack_into('<I', data, optional+8, struct.unpack_from('<I',data,optional+8)[0]+size)
        struct.pack_into('<I', data, optional+64, 0)
    data[selected[0]:selected[0]+7] = selected[1]
    return bytes(data)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('exe', type=Path)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    result = apply(args.exe.read_bytes())
    args.out.write_bytes(result)
    print('Prepared native AddOns manager: '+str(args.out))
