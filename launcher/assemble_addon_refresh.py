"""Optional development rebuild: requires capstone and keystone-engine.

The checked-in bridge profile lets release builds use Python stdlib only.
"""
import re,json,struct
from pathlib import Path
import capstone
ROOT=Path(__file__).resolve().parent
src=(ROOT/'native-addon-refresh.asm').read_text()
lines=[l for l in src.splitlines() if l.split(';')[0].strip()]
asm='\n'.join(l.split(';')[0].strip() for l in lines)
import keystone
ks=keystone.Ks(keystone.KS_ARCH_X86,keystone.KS_MODE_64)
code=bytes(ks.asm(asm,addr=0x9000000)[0]); md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64);md.detail=True
ins=list(md.disasm(code,0x9000000)); lines=[l for l in lines if not l.split(';')[0].strip().endswith(':')]
assert len(lines)==len(ins),(len(lines),len(ins))
fix=[];unwind=[];prolog=0
for l,i in zip(lines,ins):
 m=re.search(r'@(data|rva|call) (0x[0-9a-f]+|[0-9]+)',l)
 if m:
  k,t=m.groups();off=i.imm_offset if k=='call' else i.disp_offset
  assert (i.imm_size if k=='call' else i.disp_size)==4
  fix.append(dict(offset=i.address-0x9000000+off,end=i.address-0x9000000+i.size,kind='rva' if k=='call' else k,target=int(t,0)))
 end=i.address-0x9000000+i.size
 if l.startswith('sub rsp'):unwind.append((end,bytes([end,1])+struct.pack('<H',0x138//8)))
 for reg,num,off in [('rbx',3,0x98),('rsi',6,0xa0),('rdi',7,0xa8)]:
  if l.split(';')[0].strip()==f'mov [rsp+0x{off:x}], {reg}':unwind.append((end,bytes([end,(num<<4)|4])+struct.pack('<H',off//8)))
 if l.startswith('movups [rsp+0x120]'):prolog=end
assert len(unwind)==4 and prolog<256
uw=bytes([1,prolog,8,0])+b''.join(v for _,v in sorted(unwind,reverse=True))
(ROOT/'native-addon-refresh.json').write_text(json.dumps(dict(code=code.hex(),fixups=fix,unwind=uw.hex()),indent=2)+'\n')
print('Assembled native addon refresh bridge:',len(code),'bytes')
