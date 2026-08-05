#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""양피지 나레이션(가이드 텍스트) 이미지 한글화 — 게임 파일(DAT)에 직접 주입.

Culdcept Revolt 의 시작화면·튜토리얼·덱선택·배틀중단 나레이션은 폰트로 렌더하는
일반 텍스트가 아니라 **ETC1A4 텍스처**(256×64=1~2줄, 256×128=3~4줄)로,
시나리오 컨테이너(0x0d) 안에 헤더 없이 raw 픽셀로 저장돼 있다.

이 스크립트는 apply_korean_full.py 로 만든 텍스트 패치본 위에, narration_ko.json 의
한글을 해당 텍스처 위치에 렌더해 덮어쓴다(재압축 없이 0x08 무압축으로 append).

전제:
  - 입력 DAT = 텍스트 한글패치가 끝난 CULDCEPT.DAT (apply_korean_full.py 결과)
  - 0x0d(커스텀 LZMA) 엔트리 디코드가 필요 → 게임 code.bin + Unicorn 에뮬레이터
    (code.bin 은 저작권상 배포하지 않는다. 각자 롬에서 추출해 code.bin 으로 둘 것.)
  - 폰트: 나눔스퀘어 네오 Bold (fonts/README.md 참고, *.ttf 미배포)

텍스처 포맷 상세는 docs/FORMAT.md §7 참고.
"""
import struct, sys, os, json, numpy as np
from culdcept import huffman
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
TTF  = os.environ.get("KR_FONT", os.path.join(HERE, "fonts", "NanumSquareNeoBold.ttf"))
tpr  = 32
FLAT = bytes.fromhex("3333330000000000")   # 균일 진회색 ETC1 색 블록(#353535)
_m   = ImageDraw.Draw(Image.new("L", (8, 8)))


def off(TS, bx, by):
    """ETC1A4 4×4블록 (bx,by) 의 알파 8바이트 시작 오프셋. 8×8타일 row-major + 타일내 2×2 row-major."""
    return TS + ((by // 2) * tpr + (bx // 2)) * 64 + ((bx % 2) + (by % 2) * 2) * 16


def dec_alpha(b, TS, H):
    a = np.zeros((H, 256), np.uint8)
    for by in range(H // 4):
        for bx in range(64):
            o = off(TS, bx, by); ab = b[o:o + 8]; nibs = []
            for byte in ab: nibs += [byte & 0xf, byte >> 4]
            for i in range(16): a[by * 4 + i % 4, bx * 4 + i // 4] = nibs[i] * 17
    return a


def bands(a):
    rows = (a > 30).sum(axis=1) > 4; sp = []; inb = False; st = 0
    for y in range(a.shape[0]):
        if rows[y] and not inb: inb = True; st = y
        elif not rows[y] and inb: inb = False; sp.append((st, y - 1))
    if inb: sp.append((st, a.shape[0] - 1))
    m = []
    for s, e in sp:
        if m and s - m[-1][1] <= 3: m[-1] = (m[-1][0], e)
        else: m.append((s, e))
    return m


def fit(txt, maxw, mx=24):
    for s in range(mx, 9, -1):
        f = ImageFont.truetype(TTF, s); bx = _m.textbbox((0, 0), txt, font=f)
        if bx[2] - bx[0] <= maxw: return s, f, bx
    f = ImageFont.truetype(TTF, 10); return 10, f, _m.textbbox((0, 0), txt, font=f)


def inject(b, TS, lines, H):
    """텍스처(TS, 높이 H)에 한글 lines 를 렌더해 알파 교체. 색은 균일 진회색.
    * 각 줄을 원본 잉크 x-중심에 맞춰 배치(중앙원본→중앙, 좌측원본→좌측) → 게임 표시창 잘림 방지.
    * 한글 잉크가 있는 행까지만 덮어 하단에 겹쳐 저장된 다른 텍스처(예: 덱 속성 설명)를 보존.
    """
    a = dec_alpha(b, TS, H); bd = bands(a)
    cv = Image.new("L", (256, H), 0); dr = ImageDraw.Draw(cv)
    if len(bd) >= len(lines): use = bd[:len(lines)]
    else:
        top = bd[0][0] if bd else 6; bot = bd[-1][1] if bd else H - 6
        step = (bot - top) / max(1, len(lines))
        use = [(int(top + i * step), int(top + (i + 1) * step)) for i in range(len(lines))]
    for txt, (ys, ye) in zip(lines, use):
        yc = (ys + ye) // 2; s, f, bx = fit(txt, 150); w = bx[2] - bx[0]
        col = np.where(a[max(0, ys):ye + 1].sum(axis=0) > 30)[0]
        xc = (int(col.min()) + int(col.max())) // 2 if len(col) else 128
        x = max(4 - bx[0], min(xc - w // 2 - bx[0], 252 - w - bx[0]))
        y = yc - (bx[3] - bx[1]) / 2 - bx[1]
        dr.text((round(x), round(y)), txt, fill=255, font=f)
    a4 = (np.array(cv) // 17).astype(np.uint8); b = bytearray(b)
    krink = (a4 > 0)
    ymax = np.where(krink.sum(axis=1) > 0)[0].max() if krink.any() else H - 1
    by_limit = min(H // 4, (ymax // 4) + 1)
    for by in range(by_limit):
        for bx in range(64):
            o = off(TS, bx, by)
            nibs = [int(a4[by * 4 + (i % 4), bx * 4 + (i // 4)]) for i in range(16)]
            for j in range(8): b[o + j] = (nibs[2 * j]) | (nibs[2 * j + 1] << 4)
            b[o + 8:o + 16] = FLAT
    return bytes(b)


def main(in_dat, out_dat, decode_0d):
    """decode_0d(entry_bytes)->bytes : 0x0d 엔트리 디코더(게임 code.bin 필요, 별도 제공)."""
    narr = json.load(open(os.path.join(HERE, "narration_ko.json"), encoding="utf-8"))
    exclude = {(e, t) for e, t in narr.get("exclude_256x64", [])}
    from collections import defaultdict
    per_entry = defaultdict(lambda: {128: [], 64: []})
    for it in narr["256x128"]:
        per_entry[it["entry"]][128].append((it["offset"], it["lines"]))
    for it in narr["256x64"]:
        if (it["entry"], it["offset"]) in exclude: continue
        per_entry[it["entry"]][64].append((it["offset"], it["lines"]))

    d = bytearray(open(in_dat, "rb").read())
    n = struct.unpack("<I", d[:4])[0] // 8
    hdr = lambda i: (struct.unpack_from("<I", d, i * 8)[0], struct.unpack_from("<I", d, i * 8 + 4)[0])
    for ent, groups in per_entry.items():
        o, sz = hdr(ent)
        typ = struct.unpack("<I", d[o:o + 4])[0] & 0xff
        b = decode_0d(bytes(d[o:o + sz])) if typ in (0x0d, 0x8d) else \
            (huffman.decompress(bytes(d[o:o + sz])) if typ in (0x08, 0x0c) else bytes(d[o:o + sz]))
        # 텍스처 일부가 압축 해제 결과의 끝을 넘어가는 엔트리가 있다(1595/1596/1601).
        # 어차피 0x08 로 다시 써서 넣으므로, 필요한 만큼 0 으로 늘려두면 게임이 그
        # 크기 그대로 읽는다(릴리즈 빌드와 동일한 동작).
        need = max([ts + (128 // 4) * 64 * 16 for ts, _ in groups[128]] +
                   [ts + (64 // 4) * 64 * 16 for ts, _ in groups[64]] + [0])
        if need > len(b):
            b = b + b"\x00" * (need - len(b))
        for ts, lines in groups[128]: b = inject(b, ts, lines, 128)   # 3~4줄 먼저
        for ts, lines in groups[64]:  b = inject(b, ts, lines, 64)    # 1~2줄 나중
        enc = huffman.compress(b, 0x08)                                 # 0x0d→0x08 무압축 우회
        if len(d) % 16: d += b"\x00" * (16 - (len(d) % 16))
        new_off = len(d); d += enc
        struct.pack_into("<I", d, ent * 8, new_off)
        struct.pack_into("<I", d, ent * 8 + 4, len(enc))
    open(out_dat, "wb").write(d)
    print(f"나레이션 {sum(len(v[64]) + len(v[128]) for v in per_entry.values())}종 주입 -> {out_dat}")


if __name__ == "__main__":
    print(__doc__)
    print("사용: 0x0d 디코더(code.bin 기반)를 지정해 main(in_dat, out_dat, decode_0d) 호출.")
