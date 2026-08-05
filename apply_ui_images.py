#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI 버튼 아틀라스(ETC1 / ETC1A4) 한글화 — 게임 파일(DAT)에 직접 주입.

대상(ui_images_ko.json):
  * 타이틀/맵 세로 메뉴 (엔트리 711, 128×408, ETC1)
  * 덱 편집 카드 필터   (엔트리 608, 256×176, ETC1A4)
  * 배틀/맵 커맨드 버튼 (엔트리 962,  64×696, ETC1A4)

나레이션(apply_narration.py)과 달리 **code.bin 이 필요 없다** — 세 엔트리 모두
huffman(0x08/0x0c) 이라 이 저장소의 툴만으로 완전히 재현된다.

동작:
  1. 엔트리를 huffman 해제하고 텍스처 영역을 RGB 로 디코드(culdcept.etc1).
  2. 원문 잉크를 지운다.
       - row_pct : 행마다 배경색(퍼센타일)을 구해 편차 큰 픽셀만 그 색으로 치환.
                   버튼의 세로 그라디언트를 보존한다. clean_x 를 주면 그 x 구간을
                   배경 표본으로 삼는다(라벨이 버튼 폭을 꽉 채운 경우에 필요).
       - white_only : 어두운 버튼 위 밝은 글자만 배경색으로 치환.
  3. 한글을 렌더해 그린다(각 영역 중앙정렬, align 으로 좌/우 정렬 가능).
  4. **바뀐 4×4 블록만** ETC1 재인코딩(알파는 원본 유지) → 0x08 로 재압축해
     파일 끝에 append 하고 오프셋 테이블을 갱신한다.

사용:
    python apply_ui_images.py <입력.DAT> <출력.DAT> [--font <TTF>]

폰트: fonts/README.md 참고(*.ttf 는 저장소에 넣지 않는다).
포맷 상세: docs/FORMAT.md §9.
"""
import argparse
import json
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from culdcept import huffman
from culdcept.etc1 import decode_all_blocks, encode_block

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TTF = os.environ.get("KR_FONT", os.path.join(HERE, "fonts", "NanumSquareNeo-cBd.ttf"))
_m = ImageDraw.Draw(Image.new("L", (8, 8)))


def find_font(path):
    """지정 TTF 가 없으면 시스템 한글 폰트로 대체(fonts/README.md 정책과 동일)."""
    if path and os.path.exists(path):
        return path
    for cand in (r"C:\Windows\Fonts\malgunbd.ttf", r"C:\Windows\Fonts\malgun.ttf",
                 "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
                 "/System/Library/Fonts/AppleSDGothicNeo.ttc"):
        if os.path.exists(cand):
            print(f"  ! 지정 폰트 없음 → 대체 폰트 사용: {cand}")
            return cand
    raise SystemExit("한글 TTF 를 찾을 수 없습니다. --font 로 지정하세요(fonts/README.md).")


def block_off(ts, bx, by, tpr, blk):
    """4×4 블록 (bx,by) 의 시작 오프셋.

    8×8 픽셀 타일 row-major, 타일 안 4개 블록은 2×2 row-major.
    blk = 블록 바이트수(ETC1A4=16, ETC1=8). 색 블록은 ETC1A4 면 +8, ETC1 이면 +0.
    """
    return ts + ((by // 2) * tpr + (bx // 2)) * (blk * 4) + ((bx % 2) + (by % 2) * 2) * blk


def decode_rgb(data, ts, w, h, fmt):
    """텍스처 영역을 (h,w,3) RGB 로 디코드."""
    blk = 16 if fmt == "etc1a4" else 8
    coff = 8 if fmt == "etc1a4" else 0
    tpr = w // 8
    dec = decode_all_blocks(data)
    rgb = np.zeros((h, w, 3), np.uint8)
    for by in range(h // 4):
        for bx in range(w // 4):
            o = block_off(ts, bx, by, tpr, blk) + coff
            rgb[by * 4:by * 4 + 4, bx * 4:bx * 4 + 4] = dec[o // 8]
    return rgb


def erase(img, lab):
    """원문 잉크 지우기(제자리 수정)."""
    x0, y0, x1, y1 = lab["erase"]
    if lab.get("mode") == "white_only":
        reg = img[y0:y1, x0:x1]
        white = (reg > 115).all(axis=2)
        dark = reg[~white]
        bg = (np.median(dark.reshape(-1, 3), axis=0).astype(np.uint8)
              if dark.size else np.array([30, 30, 40], np.uint8))
        reg[white] = bg
        img[y0:y1, x0:x1] = reg
        return
    cx0, cx1 = lab.get("clean_x", [x0, x1])
    if lab.get("mode") == "row_fill":
        # 행 전체를 배경색(clean_x 구간의 중앙값)으로 덮는다. 라벨이 버튼 폭을
        # 가득 채워 "깨끗한 배경 픽셀"이 영역 안에 없을 때 필요(잔상 방지).
        for yy in range(y0, y1):
            bg = np.median(img[yy, cx0:cx1].reshape(-1, 3), axis=0).astype(np.uint8)
            img[yy, x0:x1] = bg
        return
    # row_pct: 행별 배경 퍼센타일 → 편차 큰 픽셀만 치환(그라디언트/무늬 보존). 2패스.
    for _ in range(2):
        for yy in range(y0, y1):
            row = img[yy, x0:x1].astype(np.float32)
            bg = np.percentile(img[yy, cx0:cx1].astype(np.float32), 85, axis=0)
            dev = np.abs(row - bg).max(axis=1)
            row[dev > 28] = bg
            img[yy, x0:x1] = row.astype(np.uint8)


def draw(pil, lab, ttf):
    """한글 렌더."""
    x0, y0, x1, y1 = lab.get("draw", lab["erase"])
    f = ImageFont.truetype(ttf, lab["size"])
    bb = _m.textbbox((0, 0), lab["text"], font=f)
    w = bb[2] - bb[0]
    h = bb[3] - bb[1]
    align = lab.get("align", "c")
    if align == "r":
        x = x1 - w - bb[0] - 4
    elif align == "l":
        x = x0 + 6 - bb[0]
    else:
        x = (x0 + x1) // 2 - w // 2 - bb[0]
    y = (y0 + y1) // 2 - h // 2 - bb[1]
    ImageDraw.Draw(pil).text((x, y), lab["text"], fill=tuple(lab["color"]), font=f)


def patch_atlas(data, atlas, ttf):
    """엔트리 데이터(압축해제본)에 한글 반영 → (새 데이터, 재인코딩 블록수)."""
    ts, w, h, fmt = atlas["ts"], atlas["w"], atlas["h"], atlas["fmt"]
    blk = 16 if fmt == "etc1a4" else 8
    coff = 8 if fmt == "etc1a4" else 0
    tpr = w // 8
    orig = decode_rgb(data, ts, w, h, fmt)
    img = orig.copy()
    for lab in atlas["labels"]:
        erase(img, lab)
    pil = Image.fromarray(img)
    for lab in atlas["labels"]:
        draw(pil, lab, ttf)
    new = np.array(pil)

    out = bytearray(data)
    changed = 0
    for by in range(h // 4):
        for bx in range(w // 4):
            ob = orig[by * 4:by * 4 + 4, bx * 4:bx * 4 + 4]
            nb = new[by * 4:by * 4 + 4, bx * 4:bx * 4 + 4]
            if (ob == nb).all():
                continue                                  # 안 바뀐 블록은 원본 바이트 유지
            o = block_off(ts, bx, by, tpr, blk) + coff
            out[o:o + 8] = encode_block(nb)               # 색 블록만 교체(알파 보존)
            changed += 1
    return bytes(out), changed


def main(in_dat, out_dat, ttf, spec_path=None):
    spec = json.load(open(spec_path or os.path.join(HERE, "ui_images_ko.json"), encoding="utf-8"))
    ttf = find_font(ttf)
    d = bytearray(open(in_dat, "rb").read())
    total = 0
    for atlas in spec["atlases"]:
        ent = atlas["entry"]
        off = struct.unpack_from("<I", d, ent * 8)[0]
        size = struct.unpack_from("<I", d, ent * 8 + 4)[0]
        typ = struct.unpack("<I", d[off:off + 4])[0] & 0xff
        if typ not in (0x08, 0x0c):
            raise SystemExit(f"엔트리 {ent} 타입 0x{typ:02x} 는 지원하지 않습니다(0x08/0x0c 만).")
        raw = huffman.decompress(bytes(d[off:off + size]))
        patched, changed = patch_atlas(raw, atlas, ttf)
        enc = huffman.compress(patched, 0x08)             # 0x08 = 무압축 리터럴
        assert huffman.decompress(enc) == patched, "재압축 왕복 검증 실패"
        if len(d) % 16:
            d += b"\x00" * (16 - (len(d) % 16))           # 16바이트 정렬
        new_off = len(d)
        d += enc
        struct.pack_into("<I", d, ent * 8, new_off)
        struct.pack_into("<I", d, ent * 8 + 4, len(enc))
        total += changed
        print(f"  {atlas['name']:16s} 엔트리 {ent:4d}  라벨 {len(atlas['labels']):2d}개  "
              f"재인코딩 {changed:5d}블록")
    open(out_dat, "wb").write(d)
    print(f"UI 이미지 {len(spec['atlases'])}종 / 총 {total}블록 주입 -> {out_dat}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="UI 버튼 아틀라스 한글화")
    ap.add_argument("in_dat")
    ap.add_argument("out_dat")
    ap.add_argument("--font", default=DEFAULT_TTF)
    ap.add_argument("--spec", default=None, help="기본: ui_images_ko.json")
    a = ap.parse_args()
    main(a.in_dat, a.out_dat, a.font, a.spec)
