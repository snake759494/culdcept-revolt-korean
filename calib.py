# -*- coding: utf-8 -*-
"""원본 라벨의 글자 잉크 bbox 를 정밀 측정(버튼 테두리 제외)."""
import struct, os, json
import numpy as np
from culdcept import huffman
from apply_ui_images import decode_rgb
def ent(p,e):
    d=open(p,'rb').read()
    o=struct.unpack_from('<I',d,e*8)[0]; s=struct.unpack_from('<I',d,e*8+4)[0]
    return huffman.decompress(d[o:o+s])
AZ=os.environ["APPDATA"]+"/Azahar"
spec=json.load(open("ui_images_ko.json",encoding="utf-8"))
a=[x for x in spec["atlases"] if x["name"]=="main_menu"][0]
O=decode_rgb(ent(AZ+"/dump/romfs/00040000000F5700/CULDCEPT.DAT",a["entry"]),a["ts"],a["w"],a["h"],a["fmt"]).astype(int)
S=O.sum(axis=2)
H,W=S.shape
# 버튼 테두리: 각 행에서 '밝은' 구간을 버튼 내부로 본다
print("라벨별 원본 글자 잉크 (버튼 내부에서만)")
for i,l in enumerate(a["labels"]):
    x0,y0,x1,y1=l["erase"]
    ys,xs=[],[]
    for y in range(y0,y1):
        row=S[y]
        lit=np.where(row>560)[0]
        if len(lit)==0: continue
        # 내부를 밝은 구간의 최소~최대에서 2px 안쪽으로
        ia,ib=lit.min()+2, lit.max()-2
        ia,ib=max(ia,x0),min(ib,x1)
        if ib<=ia: continue
        seg=row[ia:ib]
        d=np.where(seg<340)[0]
        if len(d):
            xs += list(d+ia); ys.append(y)
    if not xs:
        print(f"  {i:2d} {l['text']:>8s}  잉크없음"); continue
    print(f"  {i:2d} {l['text']:>8s} 잉크 x{min(xs):3d}-{max(xs):3d} y{min(ys):3d}-{max(ys):3d}"
          f"  (w{max(xs)-min(xs)+1:3d} h{max(ys)-min(ys)+1:2d})  중심 x{(min(xs)+max(xs))//2:3d} y{(min(ys)+max(ys))//2:3d}")
