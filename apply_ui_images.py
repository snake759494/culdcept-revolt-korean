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

from culdcept import dat as datmod, huffman, scen
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
    if lab.get("mode") == "ink":
        # 퀘스트 제목 배지: 금색 글자 + 어두운 외곽선이 회색 문장 위에 얹혀 있다.
        # 행 단위로 지우면 문장이 뭉개지므로 글자 픽셀만 골라 주변 중앙값으로 메운다.
        reg = img[y0:y1, x0:x1].astype(int)
        r, g, b_ = reg[..., 0], reg[..., 1], reg[..., 2]
        gold = (r > 140) & (r - b_ > 45)
        dark = reg.max(axis=2) < 70
        ink = gold | dark
        rest = reg[~ink]
        bg = (np.median(rest.reshape(-1, 3), axis=0) if rest.size else np.array([120, 120, 120])).astype(np.uint8)
        out = img[y0:y1, x0:x1]
        out[ink] = bg
        img[y0:y1, x0:x1] = out
        return
    if lab.get("mode") == "clear":
        # 투명 바탕 텍스처: 색을 0으로(알파는 patch_raw 가 지운다)
        img[y0:y1, x0:x1] = 0
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


def draw(pil, lab, ttf, mask=None):
    """한글 렌더. outline 이 있으면 외곽선을 두르고, mask 를 주면 같은 모양을 흰색으로 그린다(알파용)."""
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
    sw = 1 if lab.get("outline") else 0
    ImageDraw.Draw(pil).text((x, y), lab["text"], fill=tuple(lab["color"]), font=f,
                             stroke_width=sw, stroke_fill=tuple(lab.get("outline") or (0, 0, 0)))
    if mask is not None:
        ImageDraw.Draw(mask).text((x, y), lab["text"], fill=255, font=f, stroke_width=sw, stroke_fill=255)


# ── ETC1 이 아닌 형식: 8x8 타일 + 모튼 순서, 픽셀 단위 ─────────────────────
def _morton(x, y):
    i = 0
    for b in range(3):
        i |= ((x >> b) & 1) << (2 * b)
        i |= ((y >> b) & 1) << (2 * b + 1)
    return i


_MORTON = [[_morton(x, y) for x in range(8)] for y in range(8)]
RAW_BPP = {"rgba5551": 2, "rgb565": 2, "la44": 1, "rgba8": 4}


def raw_decode(data, ts, w, h, fmt):
    """(h,w,4) RGBA 로 푼다."""
    bpp = RAW_BPP[fmt]
    buf = data[ts:ts + w * h * bpp]
    px = np.zeros((h, w, 4), np.uint8)
    tpr = w // 8
    for ty in range(h // 8):
        for tx in range(tpr):
            base = (ty * tpr + tx) * 64
            for y in range(8):
                for x in range(8):
                    i = (base + _MORTON[y][x]) * bpp
                    if fmt == "rgba8":
                        a, b, g, r = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
                    elif fmt == "la44":
                        v = buf[i]
                        l, a = (v >> 4) * 17, (v & 15) * 17
                        r = g = b = l
                    else:
                        v = buf[i] | (buf[i + 1] << 8)
                        if fmt == "rgba5551":
                            r, g, b, a = (v >> 11) * 255 // 31, ((v >> 6) & 31) * 255 // 31, ((v >> 1) & 31) * 255 // 31, (v & 1) * 255
                        else:
                            r, g, b, a = (v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31, 255
                    px[ty * 8 + y, tx * 8 + x] = (r, g, b, a)
    return px


def raw_encode(px, fmt):
    h, w = px.shape[:2]
    bpp = RAW_BPP[fmt]
    out = bytearray(w * h * bpp)
    tpr = w // 8
    for ty in range(h // 8):
        for tx in range(tpr):
            base = (ty * tpr + tx) * 64
            for y in range(8):
                for x in range(8):
                    r, g, b, a = (int(v) for v in px[ty * 8 + y, tx * 8 + x])
                    i = (base + _MORTON[y][x]) * bpp
                    if fmt == "rgba8":
                        out[i:i + 4] = bytes((a, b, g, r))
                    elif fmt == "la44":
                        l = (r + g + b) // 3
                        out[i] = ((l * 15 // 255) << 4) | (a * 15 // 255)
                    elif fmt == "rgba5551":
                        v = ((r * 31 // 255) << 11) | ((g * 31 // 255) << 6) | ((b * 31 // 255) << 1) | (1 if a >= 128 else 0)
                        out[i], out[i + 1] = v & 0xFF, v >> 8
                    else:
                        v = ((r * 31 // 255) << 11) | ((g * 63 // 255) << 5) | (b * 31 // 255)
                        out[i], out[i + 1] = v & 0xFF, v >> 8
    return bytes(out)


def patch_raw(data, atlas, ttf):
    """픽셀 형식 텍스처: RGB 를 지우고 그린 뒤 알파는 새 글자 밝기로(투명 바탕) 또는 그대로."""
    ts, w, h, fmt = atlas["ts"], atlas["w"], atlas["h"], atlas["fmt"]
    px = raw_decode(data, ts, w, h, fmt)
    img = px[..., :3].copy()
    for lab in atlas["labels"]:
        erase(img, lab)
    alpha = px[..., 3].copy()
    mask = Image.new("L", (w, h), 0)
    pil = Image.fromarray(img)
    for lab in atlas["labels"]:
        if lab.get("alpha"):
            x0, y0, x1, y1 = lab["erase"]
            alpha[y0:y1, x0:x1] = 0
        draw(pil, lab, ttf, mask)
    new = np.array(pil)
    m = np.array(mask)
    for lab in atlas["labels"]:
        if lab.get("alpha"):
            x0, y0, x1, y1 = lab["erase"]
            alpha[y0:y1, x0:x1] = np.maximum(alpha[y0:y1, x0:x1], m[y0:y1, x0:x1])
    merged = np.dstack([new, alpha])
    enc = raw_encode(merged, fmt)
    out = bytearray(data)
    changed = sum(1 for i in range(0, len(enc), 64) if bytes(out[ts + i:ts + i + 64]) != enc[i:i + 64])
    out[ts:ts + len(enc)] = enc
    return bytes(out), changed


def patch_atlas(data, atlas, ttf):
    """엔트리 데이터(압축해제본)에 한글 반영 → (새 데이터, 재인코딩 블록수)."""
    ts, w, h, fmt = atlas["ts"], atlas["w"], atlas["h"], atlas["fmt"]
    blk = 16 if fmt == "etc1a4" else 8
    coff = 8 if fmt == "etc1a4" else 0
    tpr = w // 8
    if atlas.get("alpha_only"):
        return patch_alpha_only(data, atlas, ttf)
    if atlas["fmt"] in RAW_BPP:
        return patch_raw(data, atlas, ttf)
    orig = decode_rgb(data, ts, w, h, fmt)
    img = orig.copy()
    for lab in atlas["labels"]:
        erase(img, lab)
    pil = Image.fromarray(img)
    mask = Image.new("L", (w, h), 0)
    for lab in atlas["labels"]:
        draw(pil, lab, ttf, mask)
    new = np.array(pil)
    m = np.array(mask)

    out = bytearray(data)
    changed = 0
    # 알파: 투명 바탕에 글자만 있는 텍스처(배너·목록 제목)는 **글자 모양이 알파에**
    # 들어 있다. 색만 바꾸면 게임은 옛 일본어 모양대로 오려서 보여 준다. 그래서
    # 라벨 영역의 알파를 새 글자 밝기로 다시 만든다(alpha: true 인 라벨만).
    alpha_new = None
    if fmt == "etc1a4" and any(lab.get("alpha") for lab in atlas["labels"]):
        alpha_new = decode_alpha(data, ts, w, h)
        for lab in atlas["labels"]:
            if not lab.get("alpha"):
                continue
            x0, y0, x1, y1 = lab["erase"]
            if lab["alpha"] == "mask":          # 어두운 글자: 밝기 대신 글자 모양(커버리지)을 알파로
                alpha_new[y0:y1, x0:x1] = m[y0:y1, x0:x1]
                continue
            lum = new[y0:y1, x0:x1].astype(int).max(axis=2)
            alpha_new[y0:y1, x0:x1] = np.clip(lum, 0, 255).astype(np.uint8)
    for by in range(h // 4):
        for bx in range(w // 4):
            ob = orig[by * 4:by * 4 + 4, bx * 4:bx * 4 + 4]
            nb = new[by * 4:by * 4 + 4, bx * 4:bx * 4 + 4]
            o = block_off(ts, bx, by, tpr, blk)
            if alpha_new is not None:
                ablk = encode_alpha(alpha_new[by * 4:by * 4 + 4, bx * 4:bx * 4 + 4])
                if bytes(out[o:o + 8]) != ablk:
                    out[o:o + 8] = ablk
                    changed += 1
            if (ob == nb).all():
                continue                                  # 안 바뀐 블록은 원본 바이트 유지
            out[o + coff:o + coff + 8] = encode_block(nb)
            changed += 1
    return bytes(out), changed


def patch_alpha_only(data, atlas, ttf):
    """색은 그대로 두고 **알파에만** 글자를 다시 그린다(글자 모양이 알파에 있는 텍스처)."""
    ts, w, h = atlas["ts"], atlas["w"], atlas["h"]
    tpr = w // 8
    A = decode_alpha(data, ts, w, h)
    canvas = np.zeros((h, w, 3), np.uint8)
    canvas[..., 0] = A                      # 기존 알파를 밝기로 놓고 그 위에 그린다
    canvas[..., 1] = A
    canvas[..., 2] = A
    for lab in atlas["labels"]:
        x0, y0, x1, y1 = lab["erase"]
        canvas[y0:y1, x0:x1] = 0
    pil = Image.fromarray(canvas)
    for lab in atlas["labels"]:
        lab2 = dict(lab)
        lab2["color"] = [255, 255, 255]
        draw(pil, lab2, ttf)
    newA = np.array(pil)[..., 0]
    out = bytearray(data)
    changed = 0
    for by in range(h // 4):
        for bx in range(w // 4):
            o = block_off(ts, bx, by, tpr, 16)
            blk = encode_alpha(newA[by * 4:by * 4 + 4, bx * 4:bx * 4 + 4])
            if bytes(out[o:o + 8]) != blk:
                out[o:o + 8] = blk
                changed += 1
    return bytes(out), changed


def decode_alpha(data, ts, w, h):
    """ETC1A4 의 A4 알파(블록 앞 8바이트, 니블 = 열 우선)를 (h,w) 로."""
    tpr = w // 8
    A = np.zeros((h, w), np.uint8)
    for by in range(h // 4):
        for bx in range(w // 4):
            o = block_off(ts, bx, by, tpr, 16)
            blk = data[o:o + 8]
            for i in range(16):
                nib = (blk[i // 2] >> (4 * (i % 2))) & 0xF
                A[by * 4 + i % 4, bx * 4 + i // 4] = nib * 17
    return A


def encode_alpha(a4):
    """(4,4) 알파 -> A4 블록 8바이트(decode_alpha 의 역)."""
    out = bytearray(8)
    for i in range(16):
        nib = int(a4[i % 4, i // 4]) * 15 // 255
        out[i // 2] |= nib << (4 * (i % 2))
    return bytes(out)


def _load_blob(d, ent, sec):
    """엔트리(또는 컨테이너 섹션)의 압축해제본과, 되쓰기에 필요한 정보를 돌려준다."""
    off = struct.unpack_from("<I", d, ent * 8)[0]
    size = struct.unpack_from("<I", d, ent * 8 + 4)[0]
    entry = bytes(d[off:off + size])
    if sec is None:
        typ = entry[0]
        if typ not in (0x08, 0x0c):
            raise SystemExit(f"엔트리 {ent} 타입 0x{typ:02x} 는 지원하지 않습니다(0x08/0x0c 만).")
        return huffman.decompress(entry), (entry, typ, None)
    # 시나리오 컨테이너(1946~1958)의 섹션 s0 에 퀘스트 제목 그림이 들어 있다.
    secs = scen.parse_sections(entry)
    so, sl = secs[sec]
    part = entry[so:so + sl]
    typ = part[0]
    if typ not in (0x08, 0x0c):
        raise SystemExit(f"엔트리 {ent} 섹션 {sec} 타입 0x{typ:02x} 는 지원하지 않습니다.")
    return huffman.decompress(part), (entry, typ, sec)


def _store_blob(d, ent, patched, info):
    entry, typ, sec = info
    enc = huffman.pack_smallest(patched, typ)
    assert huffman.decompress(enc) == patched, "재압축 왕복 검증 실패"
    if sec is None:
        datmod.write_entry(d, ent, enc)
        return
    cont = scen.rebuild_container(entry, sec, enc)
    # 컨테이너가 원래 자리에 안 들어가면 손대지 않은 섹션까지 다시 눌러 넣는다
    # (밀려나면 게임이 옛 자리를 읽는 일이 있다 — docs/RULES.md §7).
    size = struct.unpack_from("<I", d, ent * 8 + 4)[0]
    if len(cont) > size:
        secs = scen.parse_sections(cont)
        for k, (o, l) in enumerate(secs):
            if len(cont) <= size:
                break
            if not l or cont[o] not in (0x08, 0x0c) or k == sec:
                continue
            try:
                dec = huffman.decompress(cont[o:o + l])
                cand = huffman.pack_smallest(dec, cont[o])
            except Exception:                              # noqa: BLE001
                continue
            if len(cand) < l:
                cont = scen.rebuild_container(cont, k, cand)
                secs = scen.parse_sections(cont)
    datmod.write_entry(d, ent, cont)


def main(in_dat, out_dat, ttf, spec_path=None, dump_dir=None):
    spec = json.load(open(spec_path or os.path.join(HERE, "ui_images_ko.json"), encoding="utf-8"))
    ttf = find_font(ttf)
    d = bytearray(open(in_dat, "rb").read())
    total = 0
    for atlas in spec["atlases"]:
        ent, sec = atlas["entry"], atlas.get("sec")
        raw, info = _load_blob(d, ent, sec)
        patched, changed = patch_atlas(raw, atlas, ttf)
        if dump_dir:
            os.makedirs(dump_dir, exist_ok=True)
            if atlas.get("alpha_only"):
                A = decode_alpha(patched, atlas["ts"], atlas["w"], atlas["h"])
                rgb = np.dstack([A, A, A])
            elif atlas["fmt"] in RAW_BPP:
                p4 = raw_decode(patched, atlas["ts"], atlas["w"], atlas["h"], atlas["fmt"])
                rgb = (p4[..., :3].astype(int) * p4[..., 3:4] // 255).astype(np.uint8)
            else:
                rgb = decode_rgb(patched, atlas["ts"], atlas["w"], atlas["h"], atlas["fmt"])
            Image.fromarray(rgb).save(os.path.join(dump_dir, "%s.png" % atlas["name"]))
        _store_blob(d, ent, patched, info)
        total += changed
        tag = f"{ent}.s{sec}" if sec is not None else f"{ent}"
        print(f"  {atlas['name']:16s} 엔트리 {tag:8s} 라벨 {len(atlas['labels']):2d}개  "
              f"재인코딩 {changed:5d}블록")
    open(out_dat, "wb").write(d)
    print(f"UI 이미지 {len(spec['atlases'])}종 / 총 {total}블록 주입 -> {out_dat}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="UI 버튼 아틀라스 한글화")
    ap.add_argument("in_dat")
    ap.add_argument("out_dat")
    ap.add_argument("--font", default=DEFAULT_TTF)
    ap.add_argument("--spec", default=None, help="기본: ui_images_ko.json")
    ap.add_argument("--dump", default=None, metavar="폴더",
                    help="한글을 그려 넣은 텍스처를 PNG 로도 남긴다(눈으로 확인용)")
    a = ap.parse_args()
    main(a.in_dat, a.out_dat, a.font, a.spec, a.dump)
