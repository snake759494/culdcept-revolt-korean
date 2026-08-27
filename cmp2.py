import struct, os, json
import numpy as np
from PIL import Image
from culdcept import huffman
from apply_ui_images import decode_rgb
def ent(p,e):
    d=open(p,'rb').read()
    o=struct.unpack_from('<I',d,e*8)[0]; s=struct.unpack_from('<I',d,e*8+4)[0]
    return huffman.decompress(d[o:o+s])
AZ=os.environ["APPDATA"]+"/Azahar"; SP=os.path.dirname(os.getcwd())
spec=json.load(open("ui_images_ko.json",encoding="utf-8"))
a=[x for x in spec["atlases"] if x["name"]=="main_menu"][0]
O=decode_rgb(ent(AZ+"/dump/romfs/00040000000F5700/CULDCEPT.DAT",a["entry"]),a["ts"],a["w"],a["h"],a["fmt"])
N=decode_rgb(ent(SP+"/ui_test.DAT",a["entry"]),a["ts"],a["w"],a["h"],a["fmt"])
Z=3
c=Image.new("RGB",(a["w"]*Z*2+16,a["h"]*Z),(50,50,60))
c.paste(Image.fromarray(O).resize((a["w"]*Z,a["h"]*Z),Image.NEAREST),(0,0))
c.paste(Image.fromarray(N).resize((a["w"]*Z,a["h"]*Z),Image.NEAREST),(a["w"]*Z+16,0))
c.crop((0,0,c.width,150*Z)).save(SP+"/menu_top.png")
c.crop((0,220*Z,c.width,408*Z)).save(SP+"/menu_bot.png")
print("saved")
# 결과 잉크 중심 확인
S=np.array(N).astype(int).sum(axis=2)
print("\n한글 잉크 중심 (원본 중심과 비교)")
orig_c=[16,72,95,127,151,183,239,269,299,329,359,389,389]
for i,l in enumerate(a["labels"]):
    x0,y0,x1,y1=l["erase"]
    ys,xs=[],[]
    for y in range(y0,y1):
        row=S[y]; lit=np.where(row>560)[0]
        if len(lit)==0: continue
        ia,ib=max(lit.min()+2,x0),min(lit.max()-2,x1)
        if ib<=ia: continue
        dk=np.where(row[ia:ib]<340)[0]
        if len(dk): xs+=list(dk+ia); ys.append(y)
    if not ys: print(f"  {i:2d} {l['text']:>8s} 잉크없음"); continue
    cy=(min(ys)+max(ys))//2
    print(f"  {i:2d} {l['text']:>8s} 중심 y{cy:3d} (원본 {orig_c[i]:3d}, Δ{cy-orig_c[i]:+2d})  h{max(ys)-min(ys)+1:2d} x{min(xs)}-{max(xs)}")
