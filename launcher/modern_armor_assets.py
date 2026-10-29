"""Build zone-scoped modern class armor in patch-R, with independent display IDs.

The current built chapters use loot tiers 0 and 1. Later appearance tiers,
original DBC records, item stats, collection keys and drop rules are retained.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

import armor_upgrade
import blp
from bloodelf_assets import Dbc, dbc_name
import casc
from character_upgrade import listfile, required
from durotar_assets import Chain, dependencies
from modern_armor_patch import PROFILE, display_id
from photo_archive import build, read_stored
from race_armor_assets import SHARED_HELMETS
from race_catalog import PLAYABLE_IDS
from verify_character_upgrade import model as verify_model

REGIONS = armor_upgrade.REGIONS
SLOTS = ('head', 'shoulder', 'chest', 'belt', 'pant', 'boot', 'bracer', 'glove')
CLASSES = {1: 'warrior', 2: 'paladin', 3: 'hunter', 4: 'rogue', 5: 'priest',
           7: 'shaman', 8: 'mage', 9: 'warlock', 11: 'druid'}
FAMILIES = {
    1: ('plate_raidwarrior_r_01_red', 'plate_raidwarrior_s_01gold'),
    2: ('plate_raidpaladin_r_01original', 'plate_raidpaladin_s_01_gold'),
    3: ('mail_raidhunter_r_01_green', 'mail_raidhunter_s_01_normal'),
    4: ('leather_raidrogue_r_01_black', 'leather_raidrogue_s_01teal'),
    5: ('cloth_raidpriest_r_01_white', 'cloth_raidpriest_s_01_gold'),
    7: ('mail_raidshaman_r_01blue', 'mail_raidshaman_s_01white'),
    8: ('cloth_raidmage_r_01raid', 'cloth_raidmage_s_01_purple'),
    9: ('cloth_raidwarlock_r_01_green', 'cloth_raidwarlock_s_01_purple'),
    11: ('leather_raiddruid_r_01_green', 'leather_raiddruid_s_01_green'),
}
CODES = ('au', 'al', 'ha', 'tu', 'tl', 'lu', 'll', 'fo')
PAINT = {2: (0, 1, 3, 4), 3: (4, 5), 4: (5, 6), 5: (6, 7), 6: (1,), 7: (0, 1, 2)}
BASE_PREFIX = {1:'Hu',2:'Or',3:'Dw',4:'Ni',5:'Sc',6:'Ta',7:'Gn',8:'Tr',10:'Be'}


def object_texture(names, family, kind, side='l'):
    directory = 'head' if kind == 'helm' else 'shoulder'
    for stem in (kind+'_'+family, family):
        path = f'item/objectcomponents/{directory}/{stem}.blp'
        if path in names:
            return path
    wanted = ('raid'+family.split('raid',1)[1]).replace('_','')
    for path in names:
        if path.startswith(f'item/objectcomponents/{directory}/') and path.endswith('.blp'):
            stem = path.split('/')[-1][:-4]
            if kind == 'shoulder':
                if re.search(r'_[rs]_01_?[lr](?=[a-z])',stem):
                    if not re.search(r'_[rs]_01_?'+side+r'(?=[a-z])',stem):
                        continue
                    stem = re.sub(r'(_[rs]_01)_?[lr](?=[a-z])',r'\1',stem)
            for prefix in ('helm_', 'shoulder_'):
                stem = stem.removeprefix(prefix)
            core = 'raid'+stem.split('raid',1)[1] if 'raid' in stem else stem
            if core.replace('_','') == wanted:
                return path
    return None


def texture_path(names, family, region, piece, sex):
    prefix = f'item/texturecomponents/{REGIONS[region].lower()}/{family}_'
    pieces = (piece, 'robe', 'chest') if piece == 'pant' else (piece, 'glove') if piece == 'bracer' else (piece,)
    for part in pieces:
        for variant in (sex.lower(), 'u'):
            path = prefix+f'{part}_{CODES[region]}_{variant}.blp'
            if path in names:
                return path
    return None


def rebind_primary(data, name):
    """The first fixed material is the selected set's color, not its default recolor."""
    data = bytearray(data)
    count, offset = struct.unpack_from('<II', data, 0x5c)
    if count and struct.unpack_from('<I', data, offset)[0] == 0:
        text = name.encode('ascii')+b'\0'
        struct.pack_into('<II', data, offset+8, len(text), len(data))
        data += text
    return bytes(data)


def solid_clothing(image, underlay=None):
    """Supply the fabric hidden by retail-only chest geometry on the legacy rig."""
    width,height,pixels=image
    fallback=blp.resize(underlay or image,width,height)
    samples=[pixels[i:i+3] for i in range(0,len(pixels),4) if pixels[i+3]>200]
    color=bytes(round(sum(p[c] for p in samples)/len(samples)) for c in range(3)) if samples else b'\x40\x38\x30'
    base=bytearray(fallback[2])
    for i in range(0,len(base),4):
        if base[i+3]<200:base[i:i+3]=color
        base[i+3]=255
    result=(width,height,base)
    blp.paste(result,image,0,0,blend=True)
    return result


def omit_unsupported_effects(data):
    """Retail additive shader surfaces need secondary UVs; retain the solid armor."""
    data=bytearray(data)
    _,view=struct.unpack_from('<II',data,0x4c)
    count,offset=struct.unpack_from('<II',data,view+32)
    materials,mat=struct.unpack_from('<II',data,0x84)
    kept=[]
    for i in range(count):
        batch=data[offset+24*i:offset+24*(i+1)]
        material=struct.unpack_from('<H',batch,10)[0]
        if material>=materials:raise ValueError('Armor references an invalid material')
        blend=struct.unpack_from('<H',data,mat+material*4+2)[0]
        if blend<3:kept.append(batch)
    if not kept:raise ValueError('Armor has no supported solid surfaces')
    if len(kept)!=count:
        struct.pack_into('<II',data,view+32,len(kept),len(data))
        data+=b''.join(kept)
    return bytes(data),count-len(kept)


def prepare(retail, installed, names_path, output):
    storage, game = casc.Casc(retail), Chain(installed, exclude=('patch-R.MPQ',))
    entries, converted, texture_cache = {}, {}, {}
    report = dict(retail_build=storage.version, sets=[], unsupported=[], assets={}, effect_batches_omitted=0)
    names = listfile(names_path)
    profile = json.loads(PROFILE.read_text())
    race_catalog = json.loads(Path(__file__).with_name('native-races.json').read_text())
    prefixes = dict(BASE_PREFIX, **{})
    prefixes.update({int(k): v['prefix'] for k,v in race_catalog.items()})
    table = Dbc(game.read(dbc_name('ItemDisplayInfo')))
    original = {r[0]: r for r in table.rows()}

    def texture(source, destination, covered=False, underlay=None):
        cache_key=(source,covered,underlay)
        if cache_key not in texture_cache:
            raw = required(storage, names[source])
            image = blp.decode(raw, 0)
            if image[0] > 512 or image[1] > 512:
                ratio = min(512/image[0], 512/image[1])
                image = blp.resize(image, max(1, round(image[0]*ratio)), max(1, round(image[1]*ratio)))
            if covered:
                backing=blp.decode(required(storage,names[underlay]),0) if underlay else None
                image=solid_clothing(image,backing)
            texture_cache[cache_key] = blp.encode(image)
        entries[destination] = texture_cache[cache_key]
        return dict(source=source, file_id=names[source], sha256=hashlib.sha256(entries[destination]).hexdigest())

    def convert(source, destination, primary):
        fid = names[source]
        if fid not in converted:
            converted[fid] = armor_upgrade.convert(storage, fid, entries)
        result,omitted = omit_unsupported_effects(rebind_primary(converted[fid], primary))
        report['effect_batches_omitted']+=omitted
        verify_model(result, destination)
        entries[destination] = result
        return fid

    try:
        for native in profile['records']:
            cid = native['class_id']
            for tier, family in enumerate(FAMILIES[cid]):
                if not all(object_texture(names,family,k) for k in ('helm','shoulder')):
                    stem = re.match(r'.*_[rs]_01', family)[0]
                    alternatives = sorted({p.split('/')[-1].rsplit('_chest_',1)[0] for p in names
                                           if p.startswith('item/texturecomponents/torsouppertexture/'+stem)
                                           and re.search(r'_chest_tu_[mfu]\.blp$',p)})
                    family = next((f for f in alternatives if all(object_texture(names,f,k) for k in ('helm','shoulder'))),family)
                print(f'Modern armor: {CLASSES[cid]} tier {tier}: {family}', flush=True)
                stem = re.match(r'.*_[rs]_01', family)[0]
                label = f'ASRModern_{CLASSES[cid]}_{tier}'
                record = dict(class_id=cid, tier=tier, family=family, displays=[], helmets=[], textures=[])
                for slot in range(8):
                    did = display_id(cid, tier, slot)
                    if did in original:
                        raise ValueError(f'Modern display ID collision: {did}')
                    donor = native['original'][tier][slot] or native['original'][1][slot]
                    row = list(original[donor])
                    row[0] = did
                    # Each new display owns only its own slot's resources.
                    row[1:5] = [0]*4
                    row[14:22] = [0]*8
                    if slot == 0:
                        basename = 'Helm_'+label
                        row[1] = table.text(basename+'.mdx')
                        row[3] = table.text(label+'_Head')
                        source_tex = object_texture(names,family,'helm')
                        if source_tex is None:
                            raise ValueError(f'Missing matching helmet color: {source_tex}')
                        primary = 'Item\\ObjectComponents\\Head\\'+label+'_Head.blp'
                        texture(source_tex, primary)
                        for rid in PLAYABLE_IDS:
                            for sex in 'MF':
                                prefix = prefixes[rid]
                                dest = armor_upgrade.HEAD+f'{basename}_{prefix}{sex}.m2'
                                aliases = [prefix]
                                if rid in SHARED_HELMETS:
                                    aliases.append(SHARED_HELMETS[rid])
                                if rid == 31 and sex == 'F':
                                    aliases.append('Tr')
                                candidates = [f'item/objectcomponents/head/helm_{stem}_{p.lower()}{sep}{sex.lower()}.m2'
                                              for p in aliases for sep in ('', '_')]
                                source = next((p for p in candidates if p in names), None)
                                if rid == 52 or source is None:
                                    report['unsupported'].append(dict(class_id=cid,tier=tier,race=rid,sex=sex,path=dest,
                                                                      reason='No compatible humanoid helmet' if rid==52 else 'No matching rig variant'))
                                    continue
                                fid = convert(source, dest, primary)
                                record['helmets'].append(dict(race=rid,sex=sex,path=dest,source=source,file_id=fid))
                    elif slot == 1:
                        for side, column in (('l',1),('r',2)):
                            tex_source = object_texture(names,family,'shoulder',side)
                            if tex_source is None:
                                raise ValueError(f'Missing matching shoulder color: {family} {side}')
                            primary = 'Item\\ObjectComponents\\Shoulder\\'+label+'_Shoulder'+side.upper()+'.blp'
                            texture(tex_source, primary)
                            basename = side.upper()+'Shoulder_'+label
                            row[column] = table.text(basename+'.mdx')
                            row[column+2] = table.text(label+'_Shoulder'+side.upper())
                            candidates = [f'item/objectcomponents/shoulder/{side}shoulder_{stem}.m2',
                                          f'item/objectcomponents/shoulder/shoulder_{stem}_{side}.m2']
                            source = next((p for p in candidates if p in names),None)
                            if source is None:
                                raise ValueError(f'Missing shoulder: {source}')
                            convert(source, 'Item\\ObjectComponents\\Shoulder\\'+basename+'.m2', primary)
                    else:
                        for region in PAINT[slot]:
                            basename = f'{label}_{SLOTS[slot]}_{CODES[region]}'
                            found = 0
                            for sex in ('M','F'):
                                source = texture_path(names, family, region, SLOTS[slot], sex)
                                if not source:
                                    continue
                                destination = f'Item\\TextureComponents\\{REGIONS[region]}\\{basename}_{sex}.blp'
                                covered=slot==2 and region in (3,4)
                                backing=texture_path(names,family,4,'chest',sex) if covered and region==3 else None
                                record['textures'].append(dict(slot=slot,region=region,sex=sex,coverage_underlay=backing,
                                                               **texture(source,destination,covered,backing)))
                                found += 1
                            if found:
                                row[14+region] = table.text(basename)
                            if found != 2 and (slot,region) in ((2,3),(2,4),(4,5),(4,6),(5,7),(7,2)):
                                raise ValueError(f'Incomplete core armor material: {family} {SLOTS[slot]} {REGIONS[region]}')
                    table.add(row)
                    record['displays'].append(dict(slot=slot,id=did,original=donor))
                report['sets'].append(record)
        entries[dbc_name('ItemDisplayInfo')] = table.bytes()
        outfits=Dbc(game.read(dbc_name('CharStartOutfit')))
        inventory_slot={4:2,5:2,20:2,6:3,7:4,8:5,9:6,10:7}
        outfit_changes=0
        for index,raw in enumerate(outfits.records):
            row=bytearray(raw)
            cid=row[5]
            if cid not in CLASSES:
                continue
            for slot in range(12):
                inventory=struct.unpack_from('<i',row,104+4*slot)[0]
                if inventory in inventory_slot:
                    struct.pack_into('<I',row,56+4*slot,display_id(cid,0,inventory_slot[inventory]))
                    # A shirt's full modern chest material belongs to the chest
                    # visual slot; gameplay item IDs and ownership are untouched.
                    if inventory==4:
                        struct.pack_into('<I',row,104+4*slot,5)
                    outfit_changes+=1
            outfits.records[index]=bytes(row)
        entries[dbc_name('CharStartOutfit')]=outfits.bytes()
        report['starting_garments']=outfit_changes
        for path,data in list(entries.items()):
            for dependency in dependencies(path,data):
                if dependency not in entries and game.read(dependency) is None:
                    raise ValueError(f'Missing modern armor dependency: {dependency}')
        report['assets'] = {p:hashlib.sha256(data).hexdigest() for p,data in sorted(entries.items())}
        archive = build(entries)
        if read_stored(archive)[1:] != [v for _,v in sorted(entries.items())]:
            raise ValueError('Modern armor archive failed read-back')
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_bytes(archive)
        output.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
        profile['archive']=dict(name='patch-R.MPQ',sha256=hashlib.sha256(archive).hexdigest())
        PROFILE.write_text(json.dumps(profile,indent=2)+'\n')
        print(f'Built {output}: {len(report["sets"])} class sets, {len(entries)} assets',flush=True)
    finally:
        storage.close()
        game.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('retail',type=Path)
    parser.add_argument('--installed',type=Path,required=True)
    parser.add_argument('--listfile',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    prepare(args.retail,args.installed,args.listfile,args.out)
