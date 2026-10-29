"""Replace only the first two armor appearances; preserve gear identity and rules."""
import json
from pathlib import Path
import struct
import hashlib

PROFILE = Path(__file__).with_name('native-modern-armor.json')


def display_id(class_id, tier, slot):
    return 60000+100*class_id+10*tier+slot


def validate_data(data):
    archive=json.loads(PROFILE.read_text())['archive']
    path=Path(data)/archive['name']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=archive['sha256']:
        raise ValueError('Build the matching modern class armor archive before the main executable')


def apply(image):
    profile=json.loads(PROFILE.read_text())
    for record in profile['records']:
        before = bytes.fromhex(record['before'])
        after = struct.pack('<16I', *(display_id(record['class_id'], tier, slot)
                                    for tier in range(2) for slot in range(8)))
        if image.read(record['rva'], len(before)) != before:
            raise ValueError('Unsupported native early-zone armor catalog')
        image.edit(record['rva'], after)
    # Keep the native packed-layout guard active, with the deliberately updated
    # Human Warrior outfit's exact display/inventory pairs as its fixture.
    for edit in profile['outfit_guards']+profile['starting_cache']:
        before=bytes.fromhex(edit['before'])
        if image.read(edit['rva'],len(before))!=before:
            raise ValueError('Unsupported native starting outfit guard')
        image.edit(edit['rva'],bytes.fromhex(edit['after']))
