#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""본인의 3DS 롬(.3ds/.cci)에서 `code.bin` 을 추출한다.

0x0d/0x8d(커스텀 LZMA) 엔트리를 풀려면 게임 실행코드가 필요하다
(`culdcept/lzma0d.py` 가 이 코드를 에뮬레이션한다). 저작권상 code.bin 은
배포하지 않으므로 각자 본인 롬에서 뽑아야 한다.

    python extract_code.py "Culdcept Revolt (Japan).3ds" code.bin

복호화된 롬이어야 한다(암호화된 롬은 먼저 복호화 필요).
"""
import argparse
import struct
import sys

from tools_blz import decompress as blz_decompress


def extract(rom_path, out_path):
    f = open(rom_path, "rb")
    f.seek(0x100)
    if f.read(4) != b"NCSD":
        sys.exit("NCSD 헤더가 아닙니다(.3ds/.cci 가 맞는지 확인).")
    f.seek(0x120)
    po = struct.unpack("<I", f.read(4))[0] * 0x200      # 파티션 0 = 실행 파티션
    f.seek(po + 0x100)
    if f.read(4) != b"NCCH":
        sys.exit("NCCH 헤더가 아닙니다.")
    f.seek(po + 0x188)
    flags = f.read(8)
    if not (flags[7] & 0x04):
        sys.exit("암호화된 롬입니다. 복호화된 덤프가 필요합니다.")
    f.seek(po + 0x200)
    exh = f.read(1024)
    compressed = bool(exh[0xD] & 1)                     # .code BLZ 압축 여부
    f.seek(po + 0x1A0)
    eo, es, _ = struct.unpack("<III", f.read(12))
    exefs = po + eo * 0x200
    f.seek(exefs)
    hdr = f.read(0x200)
    code = None
    for i in range(10):
        nm, off, sz = struct.unpack_from("<8sII", hdr, i * 16)
        if nm.rstrip(b"\x00") == b".code":
            f.seek(exefs + 0x200 + off)
            code = f.read(sz)
            break
    f.close()
    if code is None:
        sys.exit("ExeFS 에서 .code 를 찾지 못했습니다.")
    if compressed:
        code = blz_decompress(code)
    open(out_path, "wb").write(code)
    print(f"code.bin 추출 완료: {len(code):,} 바이트 -> {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="3DS 롬에서 code.bin 추출")
    ap.add_argument("rom")
    ap.add_argument("out", nargs="?", default="code.bin")
    a = ap.parse_args()
    extract(a.rom, a.out)
