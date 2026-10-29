"""Validate staged character/armor archives against their manifest and base data."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import struct

from bloodelf_assets import Dbc, dbc_name
from character_upgrade import RACES, SECTIONS
from durotar_assets import Chain, dependencies
from photo_archive import read_stored


def model(data, name):
    def array(at, stride):
        count, offset = struct.unpack_from('<II', data, at)
        if count and (offset < 0x144 or offset+count*stride > len(data)):
            raise ValueError(f'{name}: array {at:#x} is outside the model')
        return count, offset
    if data[:8] != b'MD20\x00\x01\x00\x00':
        raise ValueError(f'{name}: not a 1.12 M2')
    bn, bones = array(0x34, 108)
    vn, verts = array(0x44, 48)
    views, view = array(0x4C, 44)
    if views != 1 or not vn:
        raise ValueError(f'{name}: missing view/vertices')
    for i in range(bn):
        parent = struct.unpack_from('<h', data, bones+108*i+8)[0]
        if not -1 <= parent < bn or parent == i:
            raise ValueError(f'{name}: invalid bone parent')
    for i in range(vn):
        at = verts+48*i
        for weight, joint in zip(data[at+12:at+16], data[at+16:at+20]):
            if weight and joint >= bn:
                raise ValueError(f'{name}: vertex references absent bone {joint}')
    sn, sub = array(view+24, 32)
    tn, triangles = array(view+8, 2)
    ln, lookup = array(view, 2)
    if tn > 65535 or ln > 65535:
        raise ValueError(f'{name}: view exceeds 16-bit limits')
    for i in range(tn):
        value = struct.unpack_from('<H', data, triangles+2*i)[0]
        if value >= ln:
            raise ValueError(f'{name}: triangle index is out of range')
    geosets = set()
    for i in range(sn):
        sid, _, first, count, start, length = struct.unpack_from('<6H', data, sub+32*i)
        geosets.add(sid)
        if first+count > ln or start+length > tn or length % 3:
            raise ValueError(f'{name}: invalid submesh range')
    an, attachments = array(0x104, 48)
    for i in range(an):
        bone = struct.unpack_from('<H', data, attachments+48*i+4)[0]
        if bone >= bn:
            raise ValueError(f'{name}: attachment names absent bone')
    for at, stride in ((0x1C, 68), (0x5C, 16), (0x84, 4)):
        array(at, stride)
    return geosets


def verify(archives, installed):
    entries, manifests = {}, []
    for archive in archives:
        if not re.fullmatch(r'patch-[a-z0-9]\.mpq', archive.name, re.IGNORECASE):
            raise ValueError(f'{archive.name}: the native loader requires patch-?.MPQ names')
        report = json.loads(archive.with_suffix('.json').read_text())
        blobs = read_stored(archive.read_bytes())
        names = sorted(report['assets'])
        if len(blobs)-1 != len(names):
            raise ValueError('Manifest and archive file counts differ')
        for name, blob in zip(names, blobs[1:], strict=True):
            if hashlib.sha256(blob).hexdigest() != report['assets'][name]:
                raise ValueError(f'Manifest hash mismatch: {name}')
            key = name.lower()
            if key in entries and entries[key] != blob:
                raise ValueError(f'Archives disagree about {name}')
            entries[key] = blob
        manifests.append(report)
    base = Chain(installed)
    try:
        def read(name):
            return entries.get(name.lower()) or base.read(name)
        models = {name: model(blob, name) for name, blob in entries.items() if name.endswith('.m2')}
        for name, blob in entries.items():
            if name.endswith('.m2'):
                for dependency in dependencies(name, blob):
                    if read(dependency) is None:
                        raise ValueError(f'{name}: missing texture {dependency}')
        upgraded = {k: Dbc(read(dbc_name(k))) for k in SECTIONS}
        original = {k: Dbc(base.read(dbc_name(k))) for k in SECTIONS}
        for key in SECTIONS:
            # Preserve every key, ID, order and flags used by existing saves/NPCs.
            for old, new in zip(original[key].rows(), upgraded[key].rows(), strict=True):
                fixed = range(6) if key == 'CharSections' else range(4) if key == 'CharHairGeosets' else range(6)
                if any(old[i] != new[i] for i in fixed):
                    raise ValueError(f'{key}: changed a legacy customization key')
                if key == 'CharSections' and old[9] != new[9]:
                    raise ValueError('Changed legacy customization flags')
        for race, (folder, _, _) in RACES.items():
            for sex, label in enumerate(('Male', 'Female')):
                path = f'Character\\{folder}\\{label}\\{folder}{label}.m2'.lower()
                geosets = models[path]
                for row in upgraded['CharHairGeosets'].rows():
                    if row[1:3] == (race, sex) and row[4] > 1 and row[4] not in geosets:
                        raise ValueError(f'{path}: hairstyle {row[3]} has absent geoset {row[4]}')
                for row in upgraded['CharacterFacialHairStyles'].rows():
                    if row[:2] == (race, sex):
                        for group, variant in zip((100, 300, 200), row[6:9]):
                            if variant and group+variant not in geosets:
                                raise ValueError(f'{path}: facial style {row[2]} has absent geoset {group+variant}')
                for row in upgraded['CharSections'].rows():
                    if row[1:3] == (race, sex):
                        for offset in row[6:9]:
                            if row[3] == 2 and offset:
                                name = upgraded['CharSections'].string(offset)
                                expected = f'Character\\{folder}\\{label}\\{folder}{label}Facial'
                                if not name.lower().startswith(expected.lower()):
                                    raise ValueError(f'{path}: legacy facial overlay is incompatible: {name}')
                            if offset and read(upgraded['CharSections'].string(offset)) is None:
                                raise ValueError(f'{path}: missing customization texture '
                                                 f'{upgraded["CharSections"].string(offset)} for {row[3:6]}')
        retained = []
        for report in manifests:
            for issue in report.get('unsupported', []):
                retained.append(dict(**issue, native_present=base.read(issue['path']) is not None))
        return dict(models=len(models), character_models=18, assets=len(entries),
                    unsupported=retained, customization_keys_preserved=True,
                    archive_hashes={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in archives})
    finally:
        base.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives', nargs='+', type=Path)
    parser.add_argument('--installed', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.archives, args.installed)
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print(f'Validated {report["models"]} models, {report["assets"]} assets, all legacy customization keys')
