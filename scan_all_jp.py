# -*- coding: utf-8 -*-
"""패치본에서 아직 원문 그대로인 '깨끗한 일본어 텍스트'를 전 엔트리에서 찾는다."""
import struct, os, re
from culdcept import huffman, scen
AZ=os.environ["APPDATA"]+"/Azahar"; SP=os.path.dirname(os.getcwd())
O=open(AZ+"/dump/romfs/00040000000F5700/CULDCEPT.DAT",'rb').read()
N=open(SP+"/v21.DAT",'rb').read()
n=struct.unpack('<I',O[:4])[0]//8
def blobs(d,e):
    o=struct.unpack_from('<I',d,e*8)[0]; s=struct.unpack_from('<I',d,e*8+4)[0]
    if s<4: return []
    b=d[o:o+s]; res=[]
    t=b[0]
    try:
        if t in (0x08,0x0c): res.append(("",huffman.decompress(b)))
        elif t in (0x0d,0x8d): return []
        else:
            secs=scen.parse_sections(b)
            if secs:
                for k,(so,sl) in enumerate(secs):
                    if not sl: continue
                    sub=b[so:so+sl]
                    try:
                        res.append((f".s{k}", huffman.decompress(sub) if sub[0] in (0x08,0x0c) else sub))
                    except Exception: pass
            else: res.append(("",b))
    except Exception: return []
    return res
def clean_text(s):
    """제어문자 없이 SJIS 로 온전히 디코드되고 일본어 2자 이상"""
    if not (4<=len(s)<=48): return None
    try: t=s.decode("shift_jis")
    except Exception: return None
    if any(ord(c)<0x20 for c in t): return None
    jp=sum(1 for c in t if '\u3040'<=c<='\u30ff' or '\u4e00'<=c<='\u9fff')
    return t if jp>=2 else None
found={}
for e in range(n):
    ba=blobs(O,e); bb=blobs(N,e)
    if not ba or len(ba)!=len(bb): continue
    for (lbl,a),(l2,b) in zip(ba,bb):
        if len(a)!=len(b): continue
        pos=0
        for seg in a.split(b'\x00'):
            t=clean_text(seg)
            if t and b[pos:pos+len(seg)]==seg:
                found.setdefault(t,[]).append(f"e{e}{lbl}@{pos}")
            pos+=len(seg)+1
print(f"미번역 '깨끗한 텍스트' 고유 {len(found)}개")
with open(SP+"/untranslated_all.txt","w",encoding="utf-8") as f:
    for t,locs in sorted(found.items(), key=lambda x:-len(x[0])):
        f.write(f"{len(t):3d} {locs[0]:>18s} (x{len(locs)})  {t}\n")
print("→ untranslated_all.txt")
