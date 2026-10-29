"""Render all 18 complete eight-piece outfits in isolated native Armory fixtures.

Appearance-only review: the equipment resolver is forced in each disposable
executable. Neither this hook nor the copied save is part of the main build.
"""
from pathlib import Path
import sys,struct,json,os,shutil,subprocess,argparse
sys.path.insert(0,str(Path(__file__).resolve().parent))
from starter_missions import Builder
from durotar_patch import Code
from modern_armor_patch import display_id
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--candidate',type=Path,required=True)
parser.add_argument('--save',type=Path,required=True,help='Read-only source save; each preview uses a disposable copy')
args=parser.parse_args()
root=args.candidate.resolve();source=(root/'ASR.exe').read_bytes();saved=args.save.resolve()
classes={1:'Warrior',2:'Paladin',3:'Hunter',4:'Rogue',5:'Priest',7:'Shaman',8:'Mage',9:'Warlock',11:'Druid'}
summary=[]
for cid,name in classes.items():
 for tier in (0,1):
  race,sex=(4,1) if cid in (3,11) else (6,0) if cid==7 else (1,1)
  image=Builder(source);site=0x5accb5d;before=bytes.fromhex('4889d34889ce')
  code=Code().raw('c64230'+bytes([cid]).hex()+'c64231'+bytes([race]).hex()+'c64232'+bytes([sex]).hex()).raw(before).jmp(site+6)
  image.hook(site,before,code)
  site=0x5aabbdf;before=bytes.fromhex('8b563c488d4c2420');code=Code()
  if image.read(site,8)!=before:raise ValueError('Unsupported preview equipment resolver')
  for slot,position in enumerate((0,2,4,5,6,7,8,9)):
   code.raw(bytes([0xc7,0x46,position*4])+struct.pack('<I',100000+cid*1000+slot*100+tier*10))
  code.raw(before).jmp(site+8);image.hook(site,before,code)
  case=root/'full-armory'/f'{cid}-{name}-{tier}';(case/'config').mkdir(parents=True,exist_ok=True);(case/'shots').mkdir(exist_ok=True);shutil.copyfile(saved,case/'characters.txt')
  exe=case/'fixture.exe';exe.write_bytes(image.finish())
  (case/'config/config.toml').write_text('[cvars]\ngxWindow="1"\ngxResolution="1280x720"\ngxMaximize="0"\nmenuScene="0"\n')
  env={k:v for k,v in os.environ.items() if not k.startswith('WOW_ROGUE_')};env.update(APPDATA=str(case/'appdata'),BENILLA_HOME=str(case/'config'),WOW_DATA=str(root/'Data'),WOW_ROGUE_SAVE=str(case/'characters.txt'),WOW_NOSOUND='1',WOW_ROGUE_UPDATE='0',WOW_ROGUE_PRESENCE='0',WOW_ROGUE_ARMORY='1',WOW_ROGUE_SHOTS=str(case/'shots'),WOW_ROGUE_SHOTS_EVERY='1',RUST_LOG='warn')
  si=subprocess.STARTUPINFO();si.dwFlags|=subprocess.STARTF_USESHOWWINDOW;si.wShowWindow=0
  with (case/'game.log').open('w') as log:
   proc=subprocess.Popen([str(exe)],cwd=root,env=env,stdout=log,stderr=log,startupinfo=si)
   try:proc.wait(timeout=6);exit_status=proc.returncode
   except subprocess.TimeoutExpired:exit_status=None;proc.terminate();proc.wait(timeout=10)
  candidates=[p for p in sorted((case/'shots').glob('*.png')) if len(p.read_bytes())>24 and struct.unpack_from('>II',p.read_bytes(),16)[0]>100]
  if candidates:shutil.copyfile(candidates[-1],case/'preview.png')
  item=dict(class_id=cid,name=name,tier=tier,race=race,sex=sex,items=[100000+cid*1000+slot*100+tier*10 for slot in range(8)],exit=exit_status,frames=len(candidates),preview=str(case/'preview.png'));summary.append(item);print(json.dumps(item),flush=True)
(root/'full-armory/summary.json').write_text(json.dumps(summary,indent=2))

