#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DLC 리소스의 텍스트를 한글로 바꿔 LayeredFS IPS 오버레이를 만든다.

DLC 리소스(.dla/.dlb/.dld/.dlj/.dlm/.dlq)는 헤더에 제목이, 암호화된 페이로드에
이름·설명이 들어 있다. 페이로드를 풀면 게임 자체 컨테이너이거나 널 종료 SJIS
문자열 모음이다. 자세한 포맷은 culdcept/dlcres.py 참고.

★ 파일을 고치면 헤더 0x00 의 CRC 를 반드시 다시 계산해야 한다. 이걸 빼먹으면 게임이
  리소스를 전부 거부해 **DLC 가 통째로 사라진 것처럼** 보인다(이슈 #19~#21).
  dlcres.replace_strings()/fix_crc() 가 처리한다.

쓰는 법::

    python apply_dlc_text.py <DLC content 폴더> --base-dat 패치본/CULDCEPT.DAT \
        --texts dlc_text_ko.json --output dlc_overlay

번역은 dlc_text_ko.json 에 "파일명@오프셋" -> 한국어 로 담는다(원문은 담지 않는다).
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

from culdcept import dlcres
from culdcept import font as fontmod
from culdcept import huffman, wansung

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TITLE_ID = "0004008c000f5700"
FONT_ENTRY = 1054
RESOURCE_EXT = (".dla", ".dlb", ".dld", ".dlj", ".dlm", ".dlq")
# Shift-JIS 에 없는 문자는 화면에 그릴 수 없으므로 대체한다.
CHAR_FIX = {"·": "・", "—": "―", "…": "…"}


def syllable_map(dat: Path) -> dict:
    data = dat.read_bytes()
    offset, size = struct.unpack_from("<II", data, FONT_ENTRY * 8)
    return wansung.build_fixed_map(fontmod.parse_cmap(huffman.decompress(data[offset:offset + size])))


def encode(text: str, syll2code: dict) -> bytes:
    out = bytearray()
    for ch in text:
        ch = CHAR_FIX.get(ch, ch)
        code = syll2code.get(ch)
        if code is not None:
            out += bytes([code >> 8, code & 0xFF])
            continue
        if ch == "\n":
            out.append(0x0A)
            continue
        out += ch.encode("cp932")
    return bytes(out)


def romfs_files(app: bytes):
    """평문 NCCH 의 RomFS 파일 목록 [(이름, 데이터오프셋, 크기)]."""
    if app[0x100:0x104] != b"NCCH":
        return []
    ro = struct.unpack_from("<I", app, 0x1B0)[0] * 0x200
    if not ro or app[ro:ro + 4] != b"IVFC":
        return []
    lvl3 = None
    for cand in (0x1000, 0x2000, 0x3000, 0x600, 0x60):
        if struct.unpack_from("<I", app, ro + cand)[0] == 0x28:
            lvl3 = ro + cand
            break
    if lvl3 is None:
        return []
    _, _, _, _, _, _, _, fmto, fmtl, fdo = struct.unpack_from("<10I", app, lvl3)
    out, p = [], 0
    while p < fmtl:
        base = lvl3 + fmto + p
        _, _, doff, dsize, _, namelen = struct.unpack_from("<IIQQII", app, base)
        name = app[base + 0x20:base + 0x20 + namelen].decode("utf-16-le", "replace")
        out.append((name, lvl3 + fdo + doff, dsize))
        p += 0x20 + ((namelen + 3) & ~3)
    return out


def make_ips(source: bytes, target: bytes) -> bytes:
    if len(source) != len(target):
        raise ValueError("IPS 는 길이가 같아야 합니다")
    patch = bytearray(b"PATCH")
    i = 0
    while i < len(source):
        if source[i] == target[i]:
            i += 1
            continue
        start = i
        while i < len(source) and source[i] != target[i]:
            i += 1
        while start < i:
            size = min(i - start, 0xFFFF)
            if start > 0xFFFFFF:
                raise ValueError("오프셋이 IPS 범위를 넘습니다")
            patch += start.to_bytes(3, "big") + size.to_bytes(2, "big") + target[start:start + size]
            start += size
    return bytes(patch + b"EOF")


def patch_resource(raw: bytes, name: str, texts: dict, syll2code: dict, report: list) -> bytes:
    edits = {}
    for offset, original in dlcres.enum_strings(raw):
        view = texts.get("%s@%d" % (name, offset))
        if view is None:
            continue
        encoded = encode(view, syll2code)
        if len(encoded) > len(original):
            report.append("  ! %s@%d 번역이 %d바이트로 자리(%d)를 넘어 건너뜀"
                          % (name, offset, len(encoded), len(original)))
            continue
        edits[offset] = encoded

    out = dlcres.replace_strings(raw, edits) if edits else raw

    title = texts.get("%s@title" % name)
    if title is not None:
        encoded = encode(title, syll2code)
        if len(encoded) > dlcres.TITLE_MAX:
            report.append("  ! %s 제목이 %d바이트로 26을 넘어 건너뜀" % (name, len(encoded)))
        else:
            buf = bytearray(out)
            buf[0x10:0x2B] = encoded + b"\0" * (0x2B - 0x10 - len(encoded))
            candidate = dlcres.fix_crc(bytes(buf))
            if dlcres.title_ok(candidate):
                out = candidate
            else:
                report.append("  ! %s 제목이 게임의 Shift-JIS 검사를 통과하지 못해 건너뜀" % name)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="DLC 리소스 텍스트 한글화")
    ap.add_argument("content", help="DLC content 폴더(.app 들이 있는 곳)")
    ap.add_argument("--base-dat", required=True, help="한글 폰트가 든 CULDCEPT.DAT")
    ap.add_argument("--texts", default="dlc_text_ko.json")
    ap.add_argument("--output", default="dlc_overlay")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    texts_path = Path(args.texts)
    if not texts_path.is_absolute() and not texts_path.is_file():
        texts_path = here / args.texts
    texts = {k: v for k, v in json.loads(texts_path.read_text(encoding="utf-8")).items()
             if not k.startswith("_")}
    syll2code = syllable_map(Path(args.base_dat))

    out_dir = Path(args.output) / TITLE_ID / "romfs_ext"
    out_dir.mkdir(parents=True, exist_ok=True)

    report, patched, skipped = [], 0, 0
    for app_path in sorted(Path(args.content).rglob("*.app")):
        app = app_path.read_bytes()
        for name, offset, size in romfs_files(app):
            if not name.lower().endswith(RESOURCE_EXT):
                continue
            raw = app[offset:offset + size]
            new = patch_resource(raw, name, texts, syll2code, report)
            if new == raw:
                skipped += 1
                continue
            if not dlcres.accepted(new):
                report.append("  ! %s 결과가 게임 검사를 통과하지 못해 제외" % name)
                continue
            (out_dir / (name + ".ips")).write_bytes(make_ips(raw, new))
            patched += 1

    for line in report:
        print(line)
    print("패치한 리소스 %d개 (변경 없음 %d개) -> %s" % (patched, skipped, out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
