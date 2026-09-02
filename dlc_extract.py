# -*- coding: utf-8 -*-
"""DLC `.app`(평문 NCCH) 안의 RomFS 파일을 꺼낸다.

`apply_dlc_korean.py` 는 이미 풀어놓은 DLC 리소스 폴더를 입력으로 받는다. 이 도구가
그 폴더를 만든다 — Azahar 의 가상 SD 에 설치된 DLC 콘텐츠(`.app` 109개)에서
`.dla/.dlb/.dld/.dlj/.dlm/.dlq` 와 카탈로그를 꺼내 한 폴더에 모은다.

    python dlc_extract.py --content "<...>/title/0004008c/000f5700/content/00000000" --out dlc_files

꺼낸 파일은 게임 데이터이므로 저장소에 커밋하지 않는다(.gitignore).
"""
import glob, os, struct, sys

import argparse

def romfs_files(app: bytes):
    if app[0x100:0x104] != b"NCCH":
        return
    ro = struct.unpack_from("<I", app, 0x1B0)[0] * 0x200
    if ro == 0: return
    if app[ro:ro+4] != b"IVFC": return
    lvl3 = ro + 0x1000
    if struct.unpack_from("<I", app, lvl3)[0] != 0x28:
        # 다른 정렬 시도
        for cand in (0x1000, 0x2000, 0x3000, 0x600, 0x60):
            if struct.unpack_from("<I", app, ro+cand)[0] == 0x28:
                lvl3 = ro + cand; break
        else:
            return
    (hdrlen, dhto, dhtl, dmto, dmtl, fhto, fhtl, fmto, fmtl, fdo) = struct.unpack_from("<10I", app, lvl3)
    # 파일 메타데이터 테이블 순회
    p = 0
    while p < fmtl:
        base = lvl3 + fmto + p
        parent, nextsib, doff, dsize, nexthash, namelen = struct.unpack_from("<IIQQII", app, base)
        name = app[base+0x20:base+0x20+namelen].decode("utf-16-le", "replace")
        start = lvl3 + fdo + doff
        yield name, app[start:start+dsize]
        p += 0x20 + ((namelen + 3) & ~3)

ap = argparse.ArgumentParser(description="DLC .app 에서 RomFS 파일 추출")
ap.add_argument("--content", required=True, help="content/00000000 폴더 경로")
ap.add_argument("--out", default="dlc_files", help="출력 폴더")
args = ap.parse_args()
D, OUT = args.content, args.out

os.makedirs(OUT, exist_ok=True)
n = 0
names = []
for f in sorted(glob.glob(D + "/*.app")):
    app = open(f, "rb").read()
    for name, data in romfs_files(app):
        safe = name.replace("/", "_")
        open(os.path.join(OUT, "%03d_%s" % (n, safe)), "wb").write(data)
        names.append((os.path.basename(f), name, len(data)))
        n += 1
print("추출 파일 %d개" % n)
from collections import Counter
print(Counter(os.path.splitext(nm)[1] for _, nm, _ in names).most_common())
for a, b, c in names[:15]:
    print("  %-16s %-40s %d" % (a, b, c))
