#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""배포 전에 **규칙이 지켜졌는지** 빌드 결과에서 기계로 확인한다.

`docs/RULES.md` 의 규칙들을 그대로 검사한다. 같은 자리를 고쳤다가 다른 곳을
망가뜨린 일이 반복돼서 만든 것이다 — 고친 것이 다시 망가지면 여기서 걸린다.

    python 배포전검사.py <원본 CULDCEPT.DAT> <빌드한.DAT> [--code <빌드한 code.bin>]

하나라도 어긋나면 종료 코드 1 을 돌려준다.
"""
import argparse
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from culdcept import cardtext, huffman, scen                   # noqa: E402
from culdcept.dat import Dat                                   # noqa: E402
from apply_update_code import S0_LENGTH, card_name_ends, find_card_db   # noqa: E402

UI_ENTRY = 1190
NAME_TOKEN = b"{N}"
CONTROL_IN_NAME = bytes([0x08])


class Report:
    def __init__(self):
        self.fail = []

    def check(self, ok, title, detail=""):
        print("  [%s] %s%s" % ("O" if ok else "X", title, ("  — " + detail) if detail else ""))
        if not ok:
            self.fail.append(title)


def scenario_blobs(code):
    """실행코드가 싣고 있는 시나리오·전투대사 사본의 위치(docs/RULES.md §8)."""
    return (3333684, 3338152, 3342732, 3348324)


def card_region(blob):
    secs = scen.parse_sections(blob) or []
    if not secs:
        return 0, len(blob)
    off, ln = secs[0]
    return off, off + ln


def check_names(rep, region, tag):
    """규칙 1 — 카드 이름에 제어코드도 꼬리 공백도 없어야 한다."""
    ends = card_name_ends(region)
    bad_ctrl = bad_space = 0
    for end in ends:
        start = region.rfind(b"\x00", 0, end) + 1
        name = region[start:end]
        if CONTROL_IN_NAME in name:
            bad_ctrl += 1
        if name.endswith(b" "):
            bad_space += 1
    rep.check(bad_ctrl == 0, "%s 카드 이름에 제어코드 없음" % tag,
              "" if bad_ctrl == 0 else "%d개에 0x08 이 들어 있다 — 손패 목록이 깨진다" % bad_ctrl)
    rep.check(bad_space == 0, "%s 카드 이름 뒤 공백 없음" % tag,
              "" if bad_space == 0 else "%d개가 공백으로 끝난다 — 배너가 밀린다" % bad_space)
    return len(ends)


def main():
    ap = argparse.ArgumentParser(description="배포 전 규칙 검사")
    ap.add_argument("original", help="본인의 **원본** CULDCEPT.DAT")
    ap.add_argument("patched", help="빌드한 CULDCEPT.DAT")
    ap.add_argument("--code", default=None, help="빌드한 업데이트 실행코드 code.bin")
    ap.add_argument("--orig-code", default="update_code.bin", help="원본 업데이트 실행코드")
    args = ap.parse_args()

    rep = Report()
    oraw = open(args.original, "rb").read()
    praw = open(args.patched, "rb").read()
    o, p = Dat(oraw), Dat(praw)

    print("본편 CULDCEPT.DAT")
    # 규칙 7 — 제자리 / 옛 바이트
    moved, stale = [], []
    for i in range(min(o.count, p.count)):
        ooff, osize = o.table[i]
        if ooff != p.table[i][0]:          # 크기만 바뀐 건 제자리다
            moved.append(i)
            if any(praw[ooff:ooff + osize]):
                stale.append(i)
    rep.check(not stale, "옮겨진 엔트리의 옛 자리가 0 으로 지워짐",
              "" if not stale else "%d개에 옛 바이트가 남았다" % len(stale))
    print("      (옮겨진 엔트리 %d개)" % len(moved))

    oui = huffman.decompress(o.entry(UI_ENTRY))
    pui = huffman.decompress(p.entry(UI_ENTRY))
    # 규칙 3 — 널 개수
    os_, oe = card_region(oui)
    ps_, pe = card_region(pui)
    onul = oui[os_:oe].count(b"\x00")
    pnul = pui[ps_:pe].count(b"\x00")
    rep.check(onul == pnul, "카드 구간(s0) 널 개수 보존",
              "원본 %d / 빌드 %d" % (onul, pnul))
    rep.check(oe - os_ == pe - ps_, "카드 구간(s0) 길이 보존")
    n = check_names(rep, pui[ps_:pe], "본편")
    print("      (표시 이름 %d개)" % n)

    # 규칙 4 — 리터럴 {N}
    lit = 0
    for idx in list(range(1849, 1959)) + [UI_ENTRY]:
        try:
            ent = p.entry(idx)
        except Exception:                                      # noqa: BLE001
            continue
        if not ent:
            continue
        blobs = [ent]
        try:
            if ent[0] in (0x08, 0x0C):
                blobs.append(huffman.decompress(ent))
        except Exception:                                      # noqa: BLE001
            pass
        for b in list(blobs):
            try:
                secs = scen.parse_sections(b) or []
            except Exception:                                  # noqa: BLE001
                continue
            for off, ln in secs:
                if not ln or off + ln > len(b):
                    continue
                part = b[off:off + ln]
                try:
                    if part and part[0] in (0x08, 0x0C):
                        part = huffman.decompress(part)
                except Exception:                              # noqa: BLE001
                    pass
                blobs.append(part)
        lit += sum(b.count(NAME_TOKEN) for b in blobs)
    rep.check(lit == 0, "리터럴 {N} 없음",
              "" if lit == 0 else "%d곳에 글자 그대로 남았다" % lit)

    if args.code and os.path.exists(args.code):
        print("업데이트 실행코드")
        code = open(args.code, "rb").read()
        ocode = open(args.orig_code, "rb").read() if os.path.exists(args.orig_code) else None
        rep.check(ocode is None or len(code) == len(ocode), "실행코드 길이 보존")
        start = find_card_db(code, oraw)
        creg = code[start:start + S0_LENGTH]
        if ocode is not None:
            rep.check(creg.count(b"\x00") == ocode[start:start + S0_LENGTH].count(b"\x00"),
                      "실행코드 카드 DB 널 개수 보존")
        check_names(rep, creg, "실행코드")
        lit_code = code.count(NAME_TOKEN)
        for off in scenario_blobs(code):
            try:
                lit_code += huffman.decompress(code[off:]).count(NAME_TOKEN)
            except Exception:                                  # noqa: BLE001
                pass
        rep.check(lit_code == 0, "실행코드에 리터럴 {N} 없음",
                  "" if lit_code == 0 else "%d곳 — 압축된 시나리오 사본 안까지 본다" % lit_code)

    print()
    if rep.fail:
        print("결과: 실패 — %s" % ", ".join(rep.fail))
        return 1
    print("결과: 규칙 위반 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
