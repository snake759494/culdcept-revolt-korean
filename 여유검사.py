#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""번역이 **자리에 들어가는지** 빌드 전에 전수로 재 본다.

왜 필요한가
-----------
페이지마다 쓸 수 있는 바이트 수가 원문 길이로 고정돼 있다. 번역이 그보다 길면
빌더(`apply_korean_full.py`)가 **뒤에서부터 공백을 지워** 자리를 맞춘다. 그래서
번역 파일에는 `조금…… 강하게 해 볼게.` 라고 적혀 있어도 화면에는
`조금……강하게해볼게.` 로 낱말이 들러붙어 나온다.

빌드는 한 시간이 걸리므로, 같은 계산만 따로 떼어 **몇 분 안에** 어디가 몇 바이트
모자란지 알려 준다. 번역을 고칠 때마다 이걸 돌려 보면 된다.

    python 여유검사.py <원본 CULDCEPT.DAT> [--json 결과.json] [--top 30]

한 이벤트 안에서는 페이지끼리 바이트를 빌려 준다(빌더와 같은 규칙). 그래도
모자란 곳만 보고한다.
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from culdcept import cardtext, font as fontmod, huffman, scen, wansung   # noqa: E402
from culdcept.dat import Dat                                            # noqa: E402

FONT_ENTRY, UI_ENTRY = 1054, 1190
PAGE_SEP = bytes([0x07])          # 페이지 구분자
CONTAINERS = range(1946, 1959)


def event_budgets(opages, needs):
    """한 이벤트 안에서 페이지끼리 바이트를 빌려 준다(빌더와 같은 규칙)."""
    budgets = [len(page) for page in opages]
    for i in range(len(budgets)):
        want = needs[i] - budgets[i]
        for j in range(len(budgets)):
            if want <= 0:
                break
            if j == i:
                continue
            can = budgets[j] - needs[j]
            if can > 0:
                move = min(can, want)
                budgets[j] -= move
                budgets[i] += move
                want -= move
    return budgets


def load(name):
    path = os.path.join(_HERE, name)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def decompressed(entry):
    try:
        return huffman.decompress(entry)
    except Exception:                                   # noqa: BLE001
        return None


def spread_budgets(orig_lens, needs):
    """섹션(끝 영역) 전체에서 페이지끼리 바이트를 빌려 준다(빌더와 같은 규칙)."""
    buds = list(orig_lens)
    donors = [j for j in range(len(buds)) if buds[j] > needs[j]]
    di = 0
    for i in range(len(buds)):
        want = needs[i] - buds[i]
        while want > 0 and di < len(donors):
            j = donors[di]
            can = buds[j] - needs[j]
            if can <= 0:
                di += 1
                continue
            move = min(can, want)
            buds[j] -= move
            buds[i] += move
            want -= move
            if buds[j] <= needs[j]:
                di += 1
    return buds


def scan_events(events, pages_by_event, syll2code, label, out):
    """끝 영역 전체를 한 덩어리로 보고 자리가 모자란 페이지를 모은다."""
    flat = []
    for ei, ev in enumerate(events):
        kp = pages_by_event.get(str(ei))
        for pi, op in enumerate(ev.split(PAGE_SEP)):
            view = kp[pi] if (kp is not None and pi < len(kp) and kp[pi] != "") else None
            flat.append((ei, pi, op, view, cardtext.tokenize(op)[1]))
    needs = [len(cardtext.encode(v, t, syll2code)) if v is not None else len(op)
             for _e, _p, op, v, t in flat]
    buds = spread_budgets([len(op) for _e, _p, op, _v, _t in flat], needs)
    for n, (ei, pi, op, view, _t) in enumerate(flat):
        if view is not None and needs[n] > buds[n]:
            out.append({"어디": "%s e%d p%d" % (label, ei, pi),
                        "모자람": needs[n] - buds[n],
                        "본문": view})



def scan_missed(dec, mm, syll2code, label, out):
    """오프셋 기준 중간 세그먼트."""
    for off_s, pages in mm.items():
        off = int(off_s)
        end = dec.find(b"\x00", off)
        if end < 0:
            continue
        opages = dec[off:end].split(b"\x07")
        toks = [cardtext.tokenize(op)[1] for op in opages]
        needs = [len(cardtext.encode(pages[pi], toks[pi], syll2code))
                 if pi < len(pages) and pages[pi] != "" else len(opages[pi])
                 for pi in range(len(opages))]
        buds = event_budgets(opages, needs)
        for pi in range(len(opages)):
            if pi < len(pages) and pages[pi] and needs[pi] > buds[pi]:
                out.append({"어디": "%s +%s p%d" % (label, off_s, pi),
                            "모자람": needs[pi] - buds[pi],
                            "본문": pages[pi]})


def main():
    ap = argparse.ArgumentParser(description="번역이 자리에 들어가는지 전수 검사")
    ap.add_argument("dat", help="본인의 **원본** CULDCEPT.DAT")
    ap.add_argument("--json", default=None, metavar="파일", help="결과를 JSON 으로 저장")
    ap.add_argument("--top", type=int, default=25, help="화면에 몇 개까지 보일지")
    args = ap.parse_args()

    dat = Dat(open(args.dat, "rb").read())
    syll2code = wansung.build_fixed_map(
        fontmod.parse_cmap(huffman.decompress(dat.entry(FONT_ENTRY))))
    dialogue, block, missed = load("dialogue_ko.json"), load("block_ko.json"), load("missed_ko.json")
    out = []

    for idx in CONTAINERS:
        try:
            ent = dat.entry(idx)
            secs = scen.parse_sections(ent) or []
        except Exception:                               # noqa: BLE001
            continue
        for k, (off, ln) in enumerate(secs):
            if not ln or ent[off] not in (0x08, 0x0C):
                continue
            dec = decompressed(ent[off:off + ln])
            if dec is None:
                continue
            scan_missed(dec, missed.get("%d.s%d" % (idx, k), {}), syll2code,
                        "missed %d.s%d" % (idx, k), out)
            ts, events = scen.find_text_region(dec)
            if ts is None:
                continue
            scan_events(events, dialogue.get("e%d_s%d" % (idx, k), {}), syll2code,
                        "e%d_s%d" % (idx, k), out)

    keys = set(block) | {k for k in missed if "." not in k and int(k) != UI_ENTRY}
    for entry_s in sorted(keys, key=int):
        idx = int(entry_s)
        ent = dat.entry(idx)
        if not ent or ent[0] not in (0x08, 0x0C):
            continue
        dec = decompressed(ent)
        if dec is None:
            continue
        scan_missed(dec, missed.get(entry_s, {}), syll2code, "missed %s" % entry_s, out)
        ts, events = scen.find_text_region(dec)
        if ts is None:
            continue
        scan_events(events, block.get(entry_s, {}), syll2code, "block %s" % entry_s, out)

    out.sort(key=lambda row: -row["모자람"])
    print("자리가 모자란 페이지 %d곳 (합계 %d바이트)"
          % (len(out), sum(row["모자람"] for row in out)))
    for row in out[:args.top]:
        print("  %3d바이트 모자람  %-26s %s"
              % (row["모자람"], row["어디"], row["본문"].replace("\n", " / ")[:48]))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(out, handle, ensure_ascii=False, indent=1)
        print("전체 목록 -> %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
