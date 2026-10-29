"""Audit every boss added by the story work against the mounted game assets."""
import argparse
import json
import math
import struct
from pathlib import Path
from durotar_assets import Chain,canonical,creature_assets,dbc,dependencies


def boss_catalog():
    import story_chapters as S
    from durotar_patch import BOSSES,BOSS_ID
    rows=[dict(zone=zone,name=name,display=display,creature=spec['boss_id']+i) for zone,spec in S.ZONES.items() for i,(name,display) in enumerate(spec['bosses'])]
    rows += [dict(zone='durotar',name=name,display=display,creature=BOSS_ID+i) for i,(name,display) in enumerate(BOSSES)]
    rows += [dict(zone='elwynn',name=name,display=display,creature=S.ELWYNN_BOSS_ID+slot) for slot,name,display in S.ELWYNN_BOSSES]
    return rows


def mesh_stats(data):
    if data[:8]!=b'MD20\0\1\0\0':raise ValueError('Not a native 1.12 model')
    def arr(at,stride):
        count,off=struct.unpack_from('<II',data,at)
        if count and (off<0x144 or off+count*stride>len(data)):raise ValueError('Truncated model array')
        return count,off
    vertices,vo=arr(0x44,48);bones,bo=arr(0x34,108);views,view=arr(0x4c,44)
    if not vertices or not 1<=views<=4:raise ValueError('Missing body geometry')
    for i in range(vertices):
        if not all(math.isfinite(v) for v in struct.unpack_from('<3f',data,vo+i*48)):raise ValueError('Invalid body vertex')
        for w,b in zip(data[vo+i*48+12:vo+i*48+16],data[vo+i*48+16:vo+i*48+20]):
            if w and b>=bones:raise ValueError('Missing body bone')
    triangles=0;geosets=[]
    for i in range(views):
        at=view+i*44;indices,lookup=arr(at,2);count,off=arr(at+8,2);parts,sub=arr(at+24,32)
        for j in range(count):
            if struct.unpack_from('<H',data,off+j*2)[0]>=indices:raise ValueError('Invalid body triangle')
        for j in range(parts):
            ident,_,first,n,start,length=struct.unpack_from('<6H',data,sub+j*32)
            if first+n>indices or start+length>count or length%3:raise ValueError('Invalid body submesh')
            if i==0:geosets.append(ident)
        if i==0:triangles=count//3
    if not triangles:raise ValueError('Body has no triangles')
    return dict(vertices=vertices,bones=bones,views=views,triangles=triangles,geosets=geosets)


def audit(installed,source):
    game,vanilla=Chain(installed),Chain(source)
    try:
        displays,ds=dbc(game.read(r'DBFilesClient\CreatureDisplayInfo.dbc'));models,ms=dbc(game.read(r'DBFilesClient\CreatureModelData.dbc'))
        vd,_=dbc(vanilla.read(r'DBFilesClient\CreatureDisplayInfo.dbc'));vm,vs=dbc(vanilla.read(r'DBFilesClient\CreatureModelData.dbc'))
        results=[];meshes={}
        for entry in boss_catalog():
            ident=entry['display'];r=displays[ident];path=canonical(ms[models[r[1]][2]:].split(b'\0')[0].decode())
            original=canonical(vs[vm[vd[ident][1]][2]:].split(b'\0')[0].decode())
            data=game.read(path)
            if data is None:raise ValueError(f'{entry["name"]}: missing model {path}')
            if data!=vanilla.read(original):raise ValueError(f'{entry["name"]}: model differs from its Classic NPC skin/geometry')
            if r[3] and path.lower().startswith('character\\'):raise ValueError(f'{entry["name"]}: still sharing a player body')
            if path not in meshes:meshes[path]=mesh_stats(data)
            pending=list(creature_assets(game,[ident]));checked=set()
            while pending:
                name=canonical(pending.pop())
                if name.lower() in checked:continue
                checked.add(name.lower());blob=game.read(name)
                if blob is None:raise ValueError(f'{entry["name"]}: missing body dependency {name}')
                pending.extend(dependencies(name,blob))
            results.append(dict(**entry,model=path,classic_model=original,npc_skin=bool(r[3]),isolated=path!=original,assets_checked=len(checked),**meshes[path]))
        return dict(bosses=len(results),unique_models=len(meshes),results=results,all_body_assets_valid=True)
    finally:game.close();vanilla.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('installed',type=Path);p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    report=audit(a.installed,a.source);a.out.write_text(json.dumps(report,indent=2)+'\n');print(f'Validated {report["bosses"]} bosses across {report["unique_models"]} complete native models')
