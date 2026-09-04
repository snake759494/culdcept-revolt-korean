#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**화면에 깨진 한글로 나올** 문자열을 찾는다.

한글은 이 게임 폰트의 **JIS 제1수준 한자 슬롯(0x889f~0x9872)** 을 빌려 쓴다. 그래서
번역이 안 된 채 남은 그 구간의 한자는 화면에 엉뚱한 한글로 그려진다.

    位 -> 겁      戦 -> 쟁      勝 -> 쐴      枚 -> 흡

일본어로 보이면 눈에 띄지만 이건 한글처럼 보여서 그냥 오타로 오해받는다(이슈 #29의
"4겁", "1쟁 1쐴"). 게다가 "쟁"으로 원문을 검색해도 안 나오니 찾기도 어렵다.

판별법: 번역된 문자열에는 그 자리에 **진짜 한글**이 들어가 있다. 그러니 패치본과
원본이 **완전히 같으면서** 그 구간 코드를 담고 있는 문자열이 곧 깨져 보일 후보다.

    python find_garbled.py <원본 CULDCEPT.DAT> <패치본 CULDCEPT.DAT> [엔트리...]

엔트리를 안 주면 카드DB/UI 엔트리(1190)만 본다. 원문 일본어는 저장소에 담지 않으며
전부 본인 파일에서 읽어 온다.
"""
import struct
import sys

from culdcept import huffman

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LO, HI = 0x889F, 0x9872          # 한글이 빌려 쓰는 슬롯
CTRL = set(range(0x01, 0x20))    # 게임 서식 제어(0x0b·0x0c·0x17·0x18 …)
UI_ENTRY = 1190


def entry(data, index):
    off, size = struct.unpack_from("<II", data, index * 8)
    return huffman.decompress(data[off:off + size])


def has_slot(bs):
    i = 0
    while i < len(bs) - 1:
        c = bs[i]
        if 0x81 <= c <= 0xFC:
            if LO <= ((c << 8) | bs[i + 1]) <= HI:
                return True
            i += 2
        else:
            i += 1
    return False


def is_text(bs):
    """진짜 문자열인지 — 숫자 필드·포인터 같은 이진 조각을 걸러낸다."""
    i = 0
    while i < len(bs):
        c = bs[i]
        if 0x81 <= c <= 0xFC and c != 0xA0:
            if i + 1 >= len(bs):
                return False
            t = bs[i + 1]
            if not (0x40 <= t <= 0xFC and t != 0x7F):
                return False
            i += 2
            continue
        if not (c in CTRL or 0x20 <= c <= 0x7E):
            return False
        i += 1
    return True


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    orig = open(sys.argv[1], "rb").read()
    built = open(sys.argv[2], "rb").read()
    indexes = [int(x) for x in sys.argv[3:]] or [UI_ENTRY]
    total = 0
    for index in indexes:
        b, o = entry(built, index), entry(orig, index)
        print("=== 엔트리 %d ===" % index)
        pos = 0
        while pos < len(b):
            end = b.find(b"\x00", pos)
            if end < 0:
                break
            s = b[pos:end]
            if len(s) >= 4 and s == o[pos:end] and has_slot(s) and is_text(s):
                print("%8d  %s" % (pos, s.decode("cp932", "replace")))
                total += 1
            pos = end + 1
    print("깨져 보일 문자열 %d개" % total)
    if total:
        print("cards_extra_ko.json 에 {\"오프셋\": {\"len\": 길이, \"ko\": \"한글\"}} 로 넣으면 된다.")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
