#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""패치본이 **원본의 널 구분 구조**를 그대로 유지하는지 검사한다.

    python check_structure.py <원본.DAT> <패치본.DAT>

왜 필요한가
-----------
게임은 카드 레코드([이름][능력치][영문명][플레이버])와 퀘스트 데이터
([제목][설명][노드명…])를 **널로 구분된 세그먼트 순서**로 읽는다. 번역문이
원문보다 짧다고 남는 자리를 널(0x00)로 채우면 **빈 세그먼트가 새로 생겨** 뒤
필드가 전부 밀린다. 화면에서는 설명문이 비어 보이거나 퀘스트가 깨진다(이슈 #3).

그래서 번역문은 반드시 **공백(0x20)** 으로 채워 널 개수를 원본과 똑같이 유지해야
한다. 이 스크립트는 그 불변식을 자동으로 확인한다 — 빌드 후 한 번 돌려보면
이런 회귀를 바로 잡을 수 있다.
"""
import argparse
import struct
import sys

from culdcept import huffman, scen

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CARD_ENTRY = 1190
QUEST_ENTRIES = range(1946, 1960)


def entry(d, e):
    off = struct.unpack_from("<I", d, e * 8)[0]
    size = struct.unpack_from("<I", d, e * 8 + 4)[0]
    return d[off:off + size]


def decoded(d, e):
    b = entry(d, e)
    if b and b[0] in (0x08, 0x0C):
        return huffman.decompress(b)
    return b


def main(orig_path, patched_path):
    o = open(orig_path, "rb").read()
    p = open(patched_path, "rb").read()
    fails = 0

    # ── 카드 DB ────────────────────────────────────────────────
    a, b = decoded(o, CARD_ENTRY), decoded(p, CARD_ENTRY)
    na, nb = a.count(b"\x00"), b.count(b"\x00")
    good = na == nb
    fails += 0 if good else 1
    print(f"[{'O' if good else 'X'}] 카드 DB(엔트리 {CARD_ENTRY}) 널 개수  원본 {na:,} / 패치본 {nb:,}")
    if not good:
        print(f"      → {nb - na:+,} 만큼 어긋남. 빈 세그먼트가 생겨 카드 설명이 비어 보인다.")

    # ── 퀘스트 등 비압축 섹션 ──────────────────────────────────
    for e in QUEST_ENTRIES:
        try:
            ea, eb = entry(o, e), entry(p, e)
        except Exception:
            continue
        sa, sb = scen.parse_sections(ea), scen.parse_sections(eb)
        if not sa or not sb or len(sa) != len(sb):
            continue
        for k, (off, ln) in enumerate(sa):
            if not ln or off >= len(ea) or ea[off] in (0x08, 0x0C, 0x0D, 0x8D):
                continue                       # 압축 섹션은 대상 아님
            bo, bl = sb[k]
            na = ea[off:off + ln].count(b"\x00")
            nb = eb[bo:bo + bl].count(b"\x00")
            if na != nb:
                fails += 1
                print(f"[X] 엔트리 {e} raw섹션 {k} 널 개수  원본 {na} / 패치본 {nb}"
                      f"  → 퀘스트 제목·설명·노드명이 밀린다")
    if fails == 0:
        print("[O] 비압축(raw) 섹션 널 개수 전부 일치")

    print(f"\n결과: {'구조 이상 없음' if fails == 0 else f'{fails}건 불일치 — 패딩을 공백(0x20)으로 고칠 것'}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="패치본의 널 구분 구조 검사")
    ap.add_argument("orig")
    ap.add_argument("patched")
    a = ap.parse_args()
    sys.exit(main(a.orig, a.patched))
