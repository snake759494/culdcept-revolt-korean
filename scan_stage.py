# -*- coding: utf-8 -*-
"""퀘스트/스테이지 이름 중 아직 원문(일본어)으로 남은 것을 전부 찾는다."""
import struct, os, json
from culdcept import huffman, scen
def entry(d,e):
    o=struct.unpack_from('<I',d,e*8)[0]; s=struct.unpack_from('<I',d,e*8+4)[0]
    return d[o:o+s]
AZ=os.environ["APPDATA"]+"/Azahar"; SP=os.path.dirname(os.getcwd())
O=open(AZ+"/dump/romfs/00040000000F5700/CULDCEPT.DAT",'rb').read()
N=open(SP+"/v21.DAT",'rb').read()
n=struct.unpack('<I',O[:4])[0]//8
def jp_count(s):
    c=0;i=0
    while i<len(s)-1:
        b=s[i]
        if 0x81<=b<=0xfc:
            try:
                o=ord(s[i:i+2].decode("shift_jis"))
                if (0x3040<=o<=0x30ff) or (0x4e00<=o<=0x9fff): c+=1
            except: pass
            i+=2
        else: i+=1
    return c
out=[]
for e in range(1940, 1975):
    try: ea, eb = entry(O,e), entry(N,e)
    except Exception: continue
    if not ea: continue
    sa=scen.parse_sections(ea); sb=scen.parse_sections(eb)
    if not sa or not sb or len(sa)!=len(sb): continue
    for k,(off,ln) in enumerate(sa):
        if not ln or off>=len(ea) or ea[off] in (0x08,0x0c,0x0d,0x8d): continue
        raw_a=ea[off:off+ln]; bo,bl=sb[k]; raw_b=eb[bo:bo+bl]
        # 세그먼트별로 원문 그대로 남은 것 찾기
        pos=0
        for seg in raw_a.split(b'\x00'):
            if len(seg)>=4 and jp_count(seg)>=2:
                same = raw_b[pos:pos+len(seg)]==seg
                if same:
                    out.append((e,k,pos,seg))
            pos+=len(seg)+1
print(f"미번역 스테이지/노드명 후보: {len(out)}개")
with open(SP+"/untranslated_stages.txt","w",encoding="utf-8") as f:
    for e,k,pos,seg in out:
        t=seg.decode('shift_jis',errors='replace')
        f.write(f"{e}.r{k}\t{pos}\t{len(seg)}\t{t}\n")
for e,k,pos,seg in out[:40]:
    print(f"  {e}.r{k} @{pos:4d} {len(seg):3d}B  {seg.decode('shift_jis',errors='replace')[:40]!r}")
