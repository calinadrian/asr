"""Refresh the supported native game's AddOns rows after manager mutations.

Own bridge source is native-addon-refresh.asm; JSON contains its assembled bytes
and relative fixups. Two sections keep executable code and mutable data separate.
Original exception entries are retained and extended with bridge unwind metadata.
Unknown code layouts fail closed before any output is written.
"""
import hashlib
import json
from pathlib import Path
import struct

CODE_SECTION = b'.asrrfx\0'
DATA_SECTION = b'.asrrfd\0'
MARKER = b'ASR addon list refresh v1\0'.ljust(32, b'\0')
HOOK = 0x4b650
ORIGINAL = bytes.fromhex('898504010000')
FUNCTIONS = (
    (0x21d0, 0x21d5, '9e7be3fb6c18ca37e46296e718ca0a401b9fc49a5dba0966351feb6940014d61'),
    (0x4d510, 0x4dd8e, 'b28e9dccea0390278bcf477f647ff9e1d8bf208de70d18859ec516d3dbfbd382'),
    (0x3a220, 0x3ad7f, 'dd0dc23cc54fe1f97dcdac1e4e52f753a65a015945bf093da102761725618c4b'),
    (0x4b5e0, 0x4cbfe, '50f508c9a45c0d8c0b172ffddf49bbbc8421f3e1c440bea8d7ac526aa9665681'),
    (0x827b00, 0x827cc5, 'b33ab84f5aaf91c007ad4abda6c37605bbdd3fb1a5a9ff6ee2fe4011e0626a00'),
    (0x1401e0, 0x1402a4, 'b3d718a48dee4e2430f52766b739b05af18d51b2b446d08c88d647e43cc880c0'),
)
IMPORTS = {0x61548d8: b'GetModuleFileNameW', 0x61547f8: b'GetCurrentProcessId',
           0x6154180: b'GetFileAttributesW', 0x6154158: b'DeleteFileW'}
# Other supported builds (0.124.0): the same functions at their addresses, and where the bridge's
# calls and imports, assembled against the layout above, land in them.
PORTS = (
    (0x2d2040, (
        (0x21d0, 0x21d5, '2d7fd77103db6b8f7cc07f57184a71f20368ea2b9027254fed1b583214ff7995'),
        (0x2d3f00, 0x2d477e, 'ab140e51e8a016b25bf9b78a5e5e78d38ada49df484ce64d274be156a40626aa'),
        (0x2c0040, 0x2c0b9f, 'eee5acdd9c48220d353c61147bfa67f125c2e0eb4224ba275db75acde7b9f648'),
        (0x2d1fd0, 0x2d35ee, '8604958cf717dac83a0883f6e48d154eabe0c15d03203125adddb68c5c6daa07'),
        (0x796b90, 0x796d36, '48462ef78e3902ad197b2082a0a5db2769d5e134949038c2c4739e96f8ffc588'),
        (0x96980, 0x96a44, 'f0e272a59bc02c5267666939b09166f0fed5c290c54cc5370abddc708d1657e7'),
    ), {0x61b58d8: b'GetModuleFileNameW', 0x61b57f8: b'GetCurrentProcessId',
        0x61b5180: b'GetFileAttributesW', 0x61b5158: b'DeleteFileW'},
     {0x61548d8: 0x61b58d8, 0x61547f8: 0x61b57f8, 0x6154180: 0x61b5180, 0x6154158: 0x61b5158,
      0x827b00: 0x796b90, 0x1401e0: 0x96980}),
)


def apply(source):
    data = bytearray(source)
    pe = struct.unpack_from('<I', data, 60)[0]; optional = pe+24
    if data[pe:pe+4] != b'PE\0\0' or struct.unpack_from('<H', data, optional)[0] != 0x20b:
        raise ValueError('Expected native x64 game')
    count = struct.unpack_from('<H', data, pe+6)[0]
    table = optional+struct.unpack_from('<H',data,pe+20)[0]
    sections = []
    for n in range(count):
        at=table+n*40
        virtual,va,size,raw=struct.unpack_from('<IIII',data,at+8)
        sections.append((bytes(data[at:at+8]),va,raw,size,virtual))
    def offset(rva):
        for _,va,raw,size,_ in sections:
            if va <= rva < va+size: return raw+rva-va
        raise ValueError('Unsupported native refresh address')
    def read(rva,size): return bytes(data[offset(rva):offset(rva)+size])
    align=lambda x,a:(x+a-1)//a*a
    sa,fa=struct.unpack_from('<II',data,optional+32)
    for n, section in enumerate(sections):
        if section[0] in (CODE_SECTION, DATA_SECTION):
            expected = 0x60000020 if section[0] == CODE_SECTION else 0xc0000040
            if struct.unpack_from('<I', data, table+n*40+36)[0] != expected:
                raise ValueError('Native refresh section protections changed')
    existing=[s for s in sections if s[0] in (CODE_SECTION,DATA_SECTION)]
    if existing and (len(existing)!=2 or {s[0] for s in existing}!={CODE_SECTION,DATA_SECTION}):
        raise ValueError('Incomplete native refresh sections')
    if existing:
        cs=next(s for s in existing if s[0]==CODE_SECTION)
        ds=next(s for s in existing if s[0]==DATA_SECTION)
        _,cva,craw,csize,cvirtual=cs
        if read(cva,32)!=MARKER: raise ValueError('Unknown native refresh section')
        old_exception,old_size=struct.unpack_from('<II',data,craw+32)
    else:
        old_exception,old_size=struct.unpack_from('<II',data,optional+136)
        cva=align(max(v+max(s,z) for _,v,_,s,z in sections),sa)
    if old_size%12 or not old_size: raise ValueError('Invalid native exception table')
    # Validate exact functions, including the original instruction displaced by our call.
    def check(hook,functions,imports):
        replacement=b'\xe8'+struct.pack('<i',cva+64-hook-5)+b'\x90'
        if read(hook,6)!=(replacement if existing else ORIGINAL): raise ValueError('Unsupported native refresh hook')
        for start,end,digest in functions:
            body=bytearray(read(start,end-start))
            if start<=hook<end: body[hook-start:hook-start+6]=ORIGINAL
            if hashlib.sha256(body).hexdigest()!=digest: raise ValueError('Unsupported native refresh function')
        for iat,name in imports.items():
            thunk=struct.unpack('<Q',read(iat,8))[0]
            if read(thunk+2,len(name)+1)!=name+b'\0': raise ValueError('Unsupported native refresh imports')
        return replacement
    failure=None
    for hook,functions,imports,targets in ((HOOK,FUNCTIONS,IMPORTS,{}),)+PORTS:
        try:
            replacement=check(hook,functions,imports); break
        except ValueError as error:
            failure=failure or error
    else:
        raise failure
    profile=json.loads(Path(__file__).with_name('native-addon-refresh.json').read_text())
    code=bytearray.fromhex(profile['code']); unwind=bytes.fromhex(profile['unwind'])
    uw=align(64+len(code),4); pdata=align(uw+len(unwind),4)
    length=pdata+old_size+12
    dva=align(cva+length,sa)
    for f in profile['fixups']:
        target=f['target']+dva if f['kind']=='data' else targets.get(f['target'],f['target'])
        struct.pack_into('<i',code,f['offset'],target-(cva+64+f['end']))
    payload=bytearray(length)
    payload[:32]=MARKER
    struct.pack_into('<IIII',payload,32,old_exception,old_size,dva,len(code))
    payload[64:64+len(code)]=code
    payload[uw:uw+len(unwind)]=unwind
    payload[pdata:pdata+old_size]=read(old_exception,old_size)
    struct.pack_into('<III',payload,pdata+old_size,cva+64,cva+64+len(code),cva+uw)
    mutable=bytearray(0x800)
    prefix='.asr-addons-refresh-'.encode('utf-16-le')
    mutable[0x500:0x500+len(prefix)]=prefix
    if existing:
        if cs[4]!=length or ds[1]!=dva or ds[4]!=len(mutable) or read(cva,length)!=payload or read(dva,len(mutable))!=mutable:
            raise ValueError('Native refresh sections were modified')
        if struct.unpack_from('<II',data,optional+136)!=(cva+pdata,old_size+12): raise ValueError('Native refresh unwind table changed')
        return bytes(data)
    header=table+count*40
    if header+80>min(s[2] for s in sections) or any(data[header:header+80]): raise ValueError('No native refresh section header space')
    raw=align(len(data),fa)
    for n,(name,va,content,flags) in enumerate(((CODE_SECTION,cva,payload,0x60000020),(DATA_SECTION,dva,mutable,0xc0000040))):
        size=align(len(content),fa)
        data.extend(b'\0'*(raw+size-len(data)));data[raw:raw+len(content)]=content
        struct.pack_into('<8sIIIIIIHHI',data,header+n*40,name,len(content),va,size,raw,0,0,0,0,flags)
        field=optional+(4 if n==0 else 8)
        struct.pack_into('<I',data,field,struct.unpack_from('<I',data,field)[0]+size)
        raw+=size
    struct.pack_into('<H',data,pe+6,count+2)
    struct.pack_into('<I',data,optional+56,align(dva+len(mutable),sa))
    struct.pack_into('<II',data,optional+136,cva+pdata,old_size+12)
    struct.pack_into('<I',data,optional+64,0)
    data[offset(hook):offset(hook)+6]=replacement
    return bytes(data)
