# -*- coding: utf-8 -*-
"""tex_index.json 의 텍스처를 전부 PNG 로 풀고, 훑어보기용 접촉 인쇄를 만든다."""
import io
import json
import os
import sys

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image, ImageDraw
from culdcept import huffman, scen
from culdcept.dat import Dat
from apply_ui_images import decode_rgb

DAT = r"C:\Users\Jay\AppData\Roaming\Azahar\dump\romfs\00040000000F5700\CULDCEPT.DAT"
OUT = "_w/tex"
os.makedirs(OUT, exist_ok=True)


def blob_of(dat, entry, sec):
    e = dat.entry(entry)
    b = e
    try:
        if e[0] in (0x08, 0x0C):
            b = huffman.decompress(e)
    except Exception:                                   # noqa: BLE001
        pass
    if sec:
        k = int(sec[2:])
        o, l = scen.parse_sections(b)[k]
        p = b[o:o + l]
        try:
            if p and p[0] in (0x08, 0x0C):
                p = huffman.decompress(p)
        except Exception:                               # noqa: BLE001
            pass
        return p
    return b


def main():
    dat = Dat(open(DAT, "rb").read())
    index = json.load(io.open("_w/tex_index.json", encoding="utf-8"))
    cache = {}
    thumbs = []
    for n, t in enumerate(index):
        key = (t["entry"], t["sec"])
        if key not in cache:
            cache[key] = blob_of(dat, *key)
        b = cache[key]
        try:
            rgb = decode_rgb(b, t["ts"], t["w"], t["h"], t["fmt"])
        except Exception as err:                        # noqa: BLE001
            print("  e%d%s ts=%d 실패: %s" % (t["entry"], t["sec"], t["ts"], err))
            continue
        img = Image.fromarray(rgb[:t["ch"], :t["cw"]])
        name = "e%04d%s_%d_%dx%d.png" % (t["entry"], t["sec"].replace(".", "_"), t["ts"], t["cw"], t["ch"])
        img.save(os.path.join(OUT, name))
        t["file"] = name
        # 썸네일: 긴 변 160
        th = img.copy()
        th.thumbnail((160, 160))
        thumbs.append((t, th))
        if n % 100 == 0:
            print("  %d/%d" % (n, len(index)))
    io.open("_w/tex_index.json", "w", encoding="utf-8").write(json.dumps(index, indent=0))
    # 접촉 인쇄: 8열, 한 장에 48개
    per, cols, cell = 48, 8, 176
    for s in range(0, len(thumbs), per):
        chunk = thumbs[s:s + per]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cell, rows * (cell + 14)), (40, 40, 40))
        d = ImageDraw.Draw(sheet)
        for i, (t, th) in enumerate(chunk):
            x, y = (i % cols) * cell, (i // cols) * (cell + 14)
            sheet.paste(th, (x + (cell - th.width) // 2, y + (cell - th.height) // 2))
            d.text((x + 2, y + cell), "e%d%s %dx%d" % (t["entry"], t["sec"], t["cw"], t["ch"]), fill=(255, 255, 0))
        sheet.save("_w/sheet_%02d.png" % (s // per))
    print("PNG %d개, 접촉 인쇄 %d장" % (len(thumbs), (len(thumbs) + per - 1) // per))


if __name__ == "__main__":
    main()
