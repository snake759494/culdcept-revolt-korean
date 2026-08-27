# -*- coding: utf-8 -*-
"""컨테이너의 **압축 섹션** 안에서 아직 번역되지 않은 스테이지/노드 이름을 찾는다.

    python find_untranslated_nodes.py

스테이지 이름은 `#01 이름` 형태로 시나리오 컨테이너의 압축 섹션에 들어 있다.
비압축(raw) 섹션만 훑으면 놓치므로(이슈 #4) 압축을 풀어서 확인해야 한다.
찾은 항목은 `missed_ko.json` 에 `"<엔트리>.s<섹션>": {"<오프셋>": ["#01 번역"]}`
형태로 추가하면 된다. 번역문은 원문 바이트 길이 이하여야 한다(제자리 교체).
"""
import struct, os, json, re
from culdcept import huffman, scen
AZ=os.environ["APPDATA"]+"/Azahar"; SP=os.path.dirname(os.getcwd())
O=open(AZ+"/dump/romfs/00040000000F5700/CULDCEPT.DAT",'rb').read()
N=open(SP+"/v22.DAT",'rb').read()
n=struct.unpack('<I',O[:4])[0]//8
def ent(d,e):
    o=struct.unpack_from('<I',d,e*8)[0]; s=struct.unpack_from('<I',d,e*8+4)[0]
    return d[o:o+s]
def jp(s):
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
todo=[]
for e in range(n):
    ea=ent(O,e)
    if len(ea)<8: continue
    sa=scen.parse_sections(ea)
    if not sa: continue
    eb=ent(N,e); sb=scen.parse_sections(eb)
    if not sb or len(sa)!=len(sb): continue
    for k,(off,ln) in enumerate(sa):
        if not ln or off>=len(ea) or ea[off] not in (0x08,0x0c): continue
        try:
            A=huffman.decompress(ea[off:off+ln]); B=huffman.decompress(eb[sb[k][0]:sb[k][0]+sb[k][1]])
        except Exception: continue
        if len(A)!=len(B): continue
        pos=0
        for seg in A.split(b'\x00'):
            # '#NN 이름' 형태의 스테이지 노드명
            if 4<=len(seg)<=48 and seg[:1]==b'#' and jp(seg)>=1:
                if B[pos:pos+len(seg)]==seg:
                    todo.append((e,k,pos,seg))
            pos+=len(seg)+1
print(f"미번역 스테이지 노드명: {len(todo)}개")
with open(SP+"/nodes_todo.txt","w",encoding="utf-8") as f:
    for e,k,pos,seg in todo:
        f.write(f"{e}.s{k}\t{pos}\t{len(seg)}\t{seg.decode('shift_jis',errors='replace')}\n")
for e,k,pos,seg in todo[:60]:
    print(f"  {e}.s{k} @{pos:5d} {len(seg):3d}B  {seg.decode('shift_jis',errors='replace')}")
