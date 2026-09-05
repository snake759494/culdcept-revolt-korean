#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""업데이트 실행코드 **안에 들어 있는 시나리오 데이터**를 한글화한다.

왜 필요한가
-----------
v1.2 업데이트는 시나리오 섹션의 **수정본을 실행코드 안에 압축해 싣고** 있고, 게임은
DAT 이 아니라 그쪽을 읽는다. 그래서 `CULDCEPT.DAT` 의 해당 섹션을 아무리 번역해도
화면은 원문 그대로다("실력을보여라" 퀘스트 대사 — 이슈 #27/#28/#34/#35).

그 섹션을 0 으로 지워도 화면이 안 변하고, 넣은 한글이 게임 메모리에 안 올라오고,
파일 전체를 모든 코덱으로 재귀 해제해 뒤져도 원문 사본이 안 나오던 이유가 이것이다.

무엇을 하나
-----------
실행코드에서 압축 블롭을 찾아, DAT 의 어느 섹션과 같은 것인지 앞머리로 맞춰 본다.
같은 섹션이면 그 섹션에 쓰던 번역(dialogue_ko.json)을 **그대로** 적용한다.
업데이트에서 문구가 바뀐 이벤트는 원문이 달라지므로 **건드리지 않는다**.

실행코드는 크기를 못 바꾸므로, 다시 압축한 결과가 원래 블롭보다 **작거나 같아야**
한다(남는 자리는 옛 바이트가 남지만 해제기가 길이를 보고 멈추므로 무해하다).

쓰는 법
-------
    python apply_update_scenario.py --dat 원본/CULDCEPT.DAT --code code.bin \
        --out code.bin [--texts dialogue_ko.json]

`--code` 에는 apply_update_code.py 가 만든 한글 실행코드를 준다(카드 DB 가 이미
한글인 것). 이 도구는 거기에 시나리오까지 얹는다.
"""
from __future__ import annotations

import argparse
import json
import sys

from culdcept import cardtext, font as fontmod, huffman, pagepad, scen, wansung
from culdcept.dat import Dat

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FONT_ENTRY = 1054
CONTAINERS = range(1946, 1959)
MIN_BLOB = 4096


def compressed_length(data: bytes, offset: int, plain: bytes) -> int:
    """블롭이 실제로 차지하는 바이트 수(이분 탐색)."""
    lo, hi = 1, len(data) - offset
    while lo < hi:
        mid = (lo + hi) // 2
        try:
            ok = huffman.decompress(data[offset:offset + mid]) == plain
        except Exception:                               # noqa: BLE001
            ok = False
        if ok:
            hi = mid
        else:
            lo = mid + 1
    return lo


def dat_sections(dat: Dat):
    """{앞머리 32바이트: (이름, 해제된 섹션)} — 실행코드 블롭과 맞춰 보기 위한 지문."""
    out = {}
    for index in CONTAINERS:
        try:
            entry = dat.entry(index)
            sections = scen.parse_sections(entry) or []
        except Exception:                               # noqa: BLE001
            continue
        for k, (off, ln) in enumerate(sections):
            if not ln or entry[off] not in (0x08, 0x0C):
                continue
            try:
                dec = huffman.decompress(entry[off:off + ln])
            except Exception:                           # noqa: BLE001
                continue
            if len(dec) >= MIN_BLOB:
                out.setdefault(bytes(dec[:32]), ("e%d_s%d" % (index, k), dec))
    return out


def translate(blob: bytes, dat_dec: bytes, pages_by_event: dict, syll2code, report):
    """블롭의 이벤트를 번역으로 바꾼다 — **DAT 쪽과 바이트가 같은 이벤트만**.

    업데이트에서 문구가 바뀐 이벤트는 우리가 번역한 원문과 다르므로 손대지 않는다.
    """
    ts_b, events_b = scen.find_text_region(blob)
    ts_d, events_d = scen.find_text_region(dat_dec)
    if ts_b is None or ts_d is None or len(events_b) != len(events_d):
        return None, 0, 0
    region, done, skipped = bytearray(), 0, 0
    for ei, ev in enumerate(events_b):
        pages_ko = pages_by_event.get(str(ei))
        if pages_ko is None or ev != events_d[ei]:
            region += ev + b"\x00"
            if pages_ko is not None:
                skipped += 1
            continue
        opages = ev.split(b"\x07")
        toks = [cardtext.tokenize(p)[1] for p in opages]
        for pi, opage in enumerate(opages):
            view = pages_ko[pi] if pi < len(pages_ko) else ""
            if view:
                enc = cardtext.encode(view, toks[pi], syll2code)
                if len(enc) > len(opage):
                    enc = enc[:len(opage)]
                    report.append("  ! 이벤트 %d 페이지 %d 가 길어 잘림" % (ei, pi))
                # 실행코드는 크기를 못 바꾼다. 반각 공백 채움이 같은 바이트를
                # **더 잘 압축**되게 하므로(같은 바이트가 이어진다) 먼저 그걸 쓰고,
                # 그래서 대화창을 넘칠 때만 전각·재줄바꿈으로 바꾼다.
                cheap = enc + b" " * (len(opage) - len(enc))
                region += cheap if pagepad.visual_lines(cheap) <= pagepad.ROWS                     else pagepad.fit(enc, opage)[0]
            else:
                region += opage
            if pi < len(opages) - 1:
                region += b"\x07"
        region += b"\x00"
        done += 1
    out = blob[:ts_b] + bytes(region)
    if len(out) != len(blob):
        return None, 0, 0
    return out, done, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description="업데이트 실행코드 안의 시나리오 한글화")
    ap.add_argument("--dat", required=True, help="본인의 **원본** CULDCEPT.DAT")
    ap.add_argument("--code", required=True, help="입력 실행코드(카드 DB 가 한글인 것)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--texts", default="dialogue_ko.json")
    args = ap.parse_args()

    dat = Dat(open(args.dat, "rb").read())
    syll2code = wansung.build_fixed_map(
        fontmod.parse_cmap(huffman.decompress(dat.entry(FONT_ENTRY))))
    texts = json.load(open(args.texts, encoding="utf-8"))
    sigs = dat_sections(dat)
    print("DAT 시나리오 섹션 지문 %d개" % len(sigs))

    code = bytearray(open(args.code, "rb").read())
    report, patched, i = [], 0, 0
    seen = set()
    while i < len(code) - 8:
        if code[i] not in (0x08, 0x0C):
            i += 1
            continue
        try:
            blob = huffman.decompress(bytes(code[i:]))
        except Exception:                               # noqa: BLE001
            i += 1
            continue
        if len(blob) < MIN_BLOB or bytes(blob[:32]) not in sigs:
            i += 1
            continue
        name, dat_dec = sigs[bytes(blob[:32])]
        if name in seen:
            i += 1
            continue
        seen.add(name)
        room = compressed_length(bytes(code), i, blob)
        pad = 0
        while pad < 16 and i + room + pad < len(code) and code[i + room + pad] == 0:
            pad += 1
        room += pad          # 블롭 뒤 정렬용 0 바이트까지가 실제로 쓸 수 있는 자리
        new, done, skipped = translate(blob, dat_dec, texts.get(name, {}), syll2code, report)
        if new is None:
            print("  %s +%d: 구조가 맞지 않아 건너뜀" % (name, i))
            i += room
            continue
        packed = None
        for typ in (code[i], 0x0C, 0x08):
            try:
                cand = huffman.compress_real(new, typ, effort=3)
            except Exception:                           # noqa: BLE001
                continue
            if huffman.decompress(cand) == new and (packed is None or len(cand) < len(packed)):
                packed = cand
        if packed is None or len(packed) > room:
            print("  %s +%d: 다시 압축한 결과 %s > 자리 %d — 넣지 못함"
                  % (name, i, len(packed) if packed else "실패", room))
            i += room
            continue
        code[i:i + len(packed)] = packed
        patched += 1
        print("  %s +%d: 이벤트 %d개 번역(원문이 바뀐 %d개는 그대로), %d/%d바이트"
              % (name, i, done, skipped, len(packed), room))
        i += room
    for line in report[:20]:
        print(line)
    open(args.out, "wb").write(bytes(code))
    print("시나리오 블롭 %d개 한글화 -> %s" % (patched, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
