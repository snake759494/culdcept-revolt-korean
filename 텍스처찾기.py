# -*- coding: utf-8 -*-
"""DAT 전체에서 텍스처 헤더(20 00 00 80)를 찾아 목록을 만든다.

    python _w/texscan.py            -> _w/tex_index.json
"""
import io
import json
import struct
import sys

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from culdcept import huffman, scen
from culdcept.dat import Dat

MAGIC = bytes.fromhex("20000080")
DAT = r"C:\Users\Jay\AppData\Roaming\Azahar\dump\romfs\00040000000F5700\CULDCEPT.DAT"


def pad32(v):
    """폭은 2의 거듭제곱으로 채운다(96->128, 156->256, 222->256). 32의 배수가 아니다."""
    n = 8
    while n < v:
        n *= 2
    return n


def pad8(v):
    return (v + 7) // 8 * 8


def headers(blob):
    out = []
    i = blob.find(MAGIC)
    while i >= 0:
        if i + 32 <= len(blob):
            cw, ch = struct.unpack_from("<HH", blob, i + 4)
            f8 = blob[i + 8]
            fmt = {0x20: "etc1a4", 0x18: "etc1"}.get(f8)
            w, h = pad32(cw), pad8(ch)
            if fmt and 8 <= cw <= 1024 and 8 <= ch <= 2048:
                blk = 16 if fmt == "etc1a4" else 8
                size = (w // 4) * (h // 4) * blk
                if i + 32 + size <= len(blob):
                    out.append({"ts": i + 32, "cw": cw, "ch": ch, "w": w, "h": h,
                                "fmt": fmt, "size": size})
        i = blob.find(MAGIC, i + 4)
    return out


def main():
    dat = Dat(open(DAT, "rb").read())
    index = []
    for idx in range(dat.count):
        try:
            e = dat.entry(idx)
        except Exception:                                   # noqa: BLE001
            continue
        if not e:
            continue
        blobs = [("", e)]
        try:
            if e[0] in (0x08, 0x0C):
                blobs = [("", huffman.decompress(e))]
        except Exception:                                   # noqa: BLE001
            pass
        # 컨테이너 섹션도 본다
        for tag, b in list(blobs):
            try:
                secs = scen.parse_sections(b) or []
            except Exception:                               # noqa: BLE001
                secs = []
            for k, (o, l) in enumerate(secs):
                if not l or o + l > len(b):
                    continue
                p = b[o:o + l]
                try:
                    if p and p[0] in (0x08, 0x0C):
                        p = huffman.decompress(p)
                except Exception:                           # noqa: BLE001
                    pass
                blobs.append((".s%d" % k, p))
        for tag, b in blobs:
            for hdr in headers(b):
                hdr.update({"entry": idx, "sec": tag})
                index.append(hdr)
    io.open("_w/tex_index.json", "w", encoding="utf-8").write(json.dumps(index, indent=0))
    print("텍스처 %d개 (엔트리 %d개)" % (len(index), len({t["entry"] for t in index})))
    from collections import Counter
    print("형식:", Counter(t["fmt"] for t in index).most_common())
    print("큰 것 순:")
    for t in sorted(index, key=lambda t: -t["w"] * t["h"])[:8]:
        print("  e%d%s ts=%d %dx%d(%dx%d) %s" % (t["entry"], t["sec"], t["ts"], t["cw"], t["ch"], t["w"], t["h"], t["fmt"]))


if __name__ == "__main__":
    main()
