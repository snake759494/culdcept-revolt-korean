#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""화면에 보이는 **깨진 한글**을 원문 문자로 되돌려 읽는다(진단용).

완성형 방식은 한글 글리프를 JIS 제1수준 한자 자리에 넣는다. 그래서 아직 번역되지
않은 원문 한자가 화면에 나오면, 그 자리에 배정된 **한글 글리프**가 대신 그려진다.
제보 스크린샷에서 그렇게 보이는 글자를 이 도구에 넣으면 원래 어떤 글자였는지 나온다.

    python unmap.py 핼최 삐 켈꿈
    핼최 -> 配置
    삐   -> 止

원문이 나온다는 것은 곧 **그 화면이 아직 원문 데이터를 읽고 있다**는 증거다. 이슈 #17
에서 카드 화면이 패치 전 데이터를 쓰고 있다는 것을 이 방법으로 확인했다.

폰트 CMAP 이 필요하므로 CULDCEPT.DAT 한 개를 인자나 환경변수로 준다(원본·패치본
어느 쪽이든 같은 결과가 나온다).

    python unmap.py --dat "<경로>\CULDCEPT.DAT" 핼최
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

from culdcept import font as fontmod
from culdcept import huffman, wansung

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FONT_ENTRY = 1054


def _entry(path: Path, index: int) -> bytes:
    with open(path, "rb") as handle:
        handle.seek(index * 8)
        offset, size = struct.unpack("<II", handle.read(8))
        handle.seek(offset)
        return handle.read(size)


def unmap(text: str, syll2code: dict) -> str:
    out = []
    for ch in text:
        code = syll2code.get(ch)
        if code is None:
            out.append(ch)
            continue
        raw = bytes([code >> 8, code & 0xFF])
        try:
            out.append(raw.decode("cp932"))
        except UnicodeDecodeError:
            out.append("<%04X>" % code)
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="깨진 한글 -> 원문 문자 역매핑")
    ap.add_argument("--dat", help="CULDCEPT.DAT 경로 (기본: 설치된 한글패치)")
    ap.add_argument("text", nargs="+", help="화면에서 읽은 글자")
    args = ap.parse_args()

    dat = Path(args.dat) if args.dat else (
        Path(os.environ.get("APPDATA", "")) / "Azahar" / "load" / "mods"
        / "00040000000F5700" / "romfs" / "CULDCEPT.DAT")
    if not dat.is_file():
        print(f"CULDCEPT.DAT 을 찾지 못했습니다: {dat}", file=sys.stderr)
        return 2
    syll2code = wansung.build_fixed_map(fontmod.parse_cmap(huffman.decompress(_entry(dat, FONT_ENTRY))))
    for text in args.text:
        print("%-12s -> %s" % (text, unmap(text, syll2code)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
