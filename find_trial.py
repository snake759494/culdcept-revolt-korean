import struct, os
from culdcept import huffman, scen
AZ=os.environ["APPDATA"]+"/Azahar"
d=open(AZ+"/dump/romfs/00040000000F5700/CULDCEPT.DAT",'rb').read()
n=struct.unpack('<I',d[:4])[0]//8
pats=[s.encode("shift_jis") for s in ["の試練","徘徊","コロシアム","チャレンジ"]]
for e in range(n):
    o=struct.unpack_from('<I',d,e*8)[0]; s=struct.unpack_from('<I',d,e*8+4)[0]
    if s<4: continue
    b=d[o:o+s]; t=b[0]
    blobs=[]
    try:
        if t in (0x08,0x0c): blobs=[("",huffman.decompress(b))]
        elif t in (0x0d,0x8d): continue
        else:
            secs=scen.parse_sections(b)
            if secs:
                for k,(so,sl) in enumerate(secs):
                    if not sl: continue
                    sub=b[so:so+sl]
                    try: blobs.append((f".s{k}", huffman.decompress(sub) if sub[0] in (0x08,0x0c) else sub))
                    except Exception: pass
            else: blobs=[("",b)]
    except Exception: continue
    for lbl,bl in blobs:
        hit=[(p.decode('shift_jis'), bl.count(p)) for p in pats if p in bl]
        if hit: print(f"e{e}{lbl} (t=0x{t:02x}, {len(bl):,}B): {hit}")
