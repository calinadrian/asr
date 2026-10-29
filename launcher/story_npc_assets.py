"""Isolate story NPC character models from the upgraded playable races.

Merge into patch-Z.MPQ, the final mounted one-character patch, retaining all
existing zone photos. Only the built story humanoid display rows are redirected;
all playable-race models and every unrelated DBC row are preserved.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from bloodelf_assets import Dbc
from durotar_assets import Chain,canonical,dependencies
from photo_archive import build,read_stored

ARCHIVE='patch-Z.MPQ'


def selected_displays():
    """Every added story NPC, including Durotar and the retitled Elwynn bosses."""
    from story_chapters import ZONES, ELWYNN_BOSSES
    from durotar_patch import ENEMIES, BOSSES
    selected={d for zone in ZONES.values() for _,d in zone['enemies']+zone['bosses']}
    selected.update(d for _,d in ENEMIES+BOSSES)
    selected.update(d for _,_,d in ELWYNN_BOSSES)
    return selected


def prepare(source,installed):
    vanilla=Chain(source);game=Chain(installed,exclude=(ARCHIVE,))
    try:
        blobs=read_stored((Path(installed)/ARCHIVE).read_bytes())
        entries=dict(zip(blobs[0].decode('ascii').splitlines(),blobs[1:],strict=True))
        displays=Dbc(game.read(r'DBFilesClient\CreatureDisplayInfo.dbc'))
        models=Dbc(game.read(r'DBFilesClient\CreatureModelData.dbc'))
        old_models={r[0]:r for r in models.rows()}
        vanilla_models={r[0]:r for r in Dbc(vanilla.read(r'DBFilesClient\CreatureModelData.dbc')).rows()}
        original=displays.rows()
        selected=selected_displays()
        aliases={};changed={};pending=[]
        for index,row in enumerate(original):
            if row[0] not in selected or not row[3]:continue
            model=old_models[row[1]];path=canonical(models.string(model[2]))
            if not path.lower().startswith('character\\'):continue
            if path not in aliases:
                label=path.split('\\')[-1]
                alias='Creature\\ASRStoryNPC\\'+label
                data=vanilla.read(path)
                if data is None:raise ValueError(f'Missing vanilla NPC model: {path}')
                entries[alias]=data
                # Embedded static textures still resolve against original names.
                pending.extend(dependencies(path,data))
                clone=list(vanilla_models[row[1]]);clone[0]=models.next_id();clone[2]=alias[:-3]+'.mdx'
                models.add(clone);aliases[path]=(clone[0],alias)
            updated=list(row);updated[1]=aliases[path][0]
            displays.records[index]=struct.pack(f'<{displays.size//4}I',*updated)
            changed[str(row[0])]=dict(original_model=row[1],model=updated[1],path=aliases[path][1])
        checked=set()
        while pending:
            name=canonical(pending.pop())
            if name.lower() in checked:continue
            checked.add(name.lower());data=game.read(name)
            if data is None:
                data=vanilla.read(name)
                if data is None:raise ValueError(f'Missing NPC dependency: {name}')
                entries[name]=data
            pending.extend(dependencies(name,data))
        entries[r'DBFilesClient\CreatureDisplayInfo.dbc']=displays.bytes()
        entries[r'DBFilesClient\CreatureModelData.dbc']=models.bytes()
        archive=build(entries)
        assert read_stored(archive)[1:]==[v for _,v in sorted(entries.items())]
        return archive,dict(displays=changed,models={k:v[1] for k,v in aliases.items()},entries=len(entries),sha256=hashlib.sha256(archive).hexdigest())
    finally:vanilla.close();game.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--installed',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    archive,report=prepare(a.source,a.installed);a.out.write_bytes(archive);a.out.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
