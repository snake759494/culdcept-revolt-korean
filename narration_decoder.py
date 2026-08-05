#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build.py --narration-decoder 용 어댑터.

0x0d/0x8d 엔트리를 푸는 데 필요한 게임 실행코드(code.bin)를 읽어
`decompress(entry_bytes) -> bytes` 를 제공한다.

code.bin 경로는 환경변수 CULDCEPT_CODE_BIN 또는 이 파일 옆의 code.bin.
추출 방법:  python extract_code.py "본인의 롬.3ds" code.bin
"""
import os

from culdcept.lzma0d import Decoder

_HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.environ.get("CULDCEPT_CODE_BIN", os.path.join(_HERE, "code.bin"))
if not os.path.exists(_PATH):
    raise SystemExit(
        f"code.bin 을 찾을 수 없습니다: {_PATH}\n"
        "  python extract_code.py \"본인의 롬.3ds\" code.bin  으로 추출하세요."
    )
_dec = Decoder(_PATH)


def decompress(entry_bytes: bytes) -> bytes:
    return _dec.decompress(entry_bytes)
