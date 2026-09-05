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
import struct

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


def dat_sections(dat: Dat, block_indices=()):
    """{앞머리 32바이트: [(이름, 해제된 것), …]} — 실행코드 블롭과 맞춰 볼 지문.

    실행코드가 사본을 싣는 것은 시나리오 컨테이너만이 아니다. **전투 중 캐릭터
    대사**(낱개 엔트리 1869·1870 등)도 통째로 싣고 있어, 번역이 DAT 에 들어가
    있어도 업데이트를 깐 사람 화면에는 원문이 나온다.

    엔트리 1869 와 1870 은 앞머리 32바이트가 서로 같아서 지문 하나에 후보가 여럿
    걸린다. 그래서 값을 목록으로 두고, 부르는 쪽에서 실제로 맞춰 보고 고른다.
    """
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
                out.setdefault(bytes(dec[:32]), []).append(("e%d_s%d" % (index, k), dec))
    for index in block_indices:
        try:
            entry = dat.entry(index)
        except Exception:                               # noqa: BLE001
            continue
        if not entry or entry[0] not in (0x08, 0x0C):
            continue
        try:
            dec = huffman.decompress(entry)
        except Exception:                               # noqa: BLE001
            continue
        if len(dec) >= MIN_BLOB and scen.find_text_region(dec)[0] is not None:
            out.setdefault(bytes(dec[:32]), []).append((str(index), dec))
    return out


def _event_budgets(opages, needs):
    """한 이벤트 안에서 페이지끼리 바이트를 빌려 준다(본편 빌더와 같은 규칙)."""
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


def _pack_best(plain: bytes, prefer: int):
    """같은 내용을 두 코덱으로 눌러 **가장 작은 것**을 돌려준다. 실패하면 None."""
    best = None
    for typ in (prefer, 0x0C, 0x08):
        try:
            cand = huffman.compress_real(plain, typ, effort=3)
        except Exception:                               # noqa: BLE001
            continue
        if huffman.decompress(cand) == plain and (best is None or len(cand) < len(best)):
            best = cand
    return best



def translate(blob: bytes, dat_dec: bytes, pages_by_event: dict, syll2code, report,
              skip=()):
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
        if pages_ko is None or ev != events_d[ei] or ei in skip:
            region += ev + b"\x00"
            if pages_ko is not None:
                skipped += 1
            continue
        opages = ev.split(b"")
        toks = [cardtext.tokenize(p)[1] for p in opages]
        # 본편 빌더와 같이 **이벤트 안에서 페이지끼리 자리를 빌려 준다.** 이게 없어서
        # 번역이 자기 페이지보다 한두 바이트 길면 글자를 잘라 내고 있었다.
        needs = [len(cardtext.encode(pages_ko[pi], toks[pi], syll2code))
                 if pi < len(pages_ko) and pages_ko[pi] else len(opages[pi])
                 for pi in range(len(opages))]
        buds = _event_budgets(opages, needs)
        if any(needs[pi] > buds[pi] for pi in range(len(opages))):
            # 자리에 안 들어가는 페이지가 있으면 **그 이벤트는 통째로 원문으로 둔다.**
            # 바이트로 잘라 넣으면 문장이 중간에서 끊긴 채 화면에 나온다. 어차피
            # 자리가 모자라 이벤트를 골라 담는 상황이니, 이건 그냥 안 고르면 된다.
            region += ev + b"\x00"
            skipped += 1
            continue
        for pi, opage in enumerate(opages):
            view = pages_ko[pi] if pi < len(pages_ko) else ""
            if view:
                enc = cardtext.encode(view, toks[pi], syll2code)
                # 실행코드는 크기를 못 바꾼다. 반각 공백 채움이 같은 바이트를
                # **더 잘 압축**되게 하므로(같은 바이트가 이어진다) 먼저 그걸 쓰고,
                # 그래서 대화창을 넘칠 때만 전각·재줄바꿈으로 바꾼다.
                cheap = enc + b" " * (buds[pi] - len(enc))
                region += cheap if pagepad.visual_lines(cheap) <= pagepad.ROWS else pagepad.fit(enc, bytes(buds[pi]))[0]
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


BASE_VA = 0x100000            # exefs .code 가 올라가는 주소


def find_pointer(code, off):
    """블롭을 가리키는 포인터의 파일 위치. 딱 하나일 때만 돌려준다.

    실행코드는 블롭을 {번호, 주소} 표로 가리키고 **크기 필드는 없다**(블롭 머리에
    해제 크기가 들어 있고 압축 스트림이 스스로 끝난다). 그래서 포인터만 고치면
    붙어 있는 블롭들 사이에서 자리를 옮겨 줄 수 있다.
    """
    want = struct.pack("<I", off + BASE_VA)
    hits, at = [], code.find(want)
    while at >= 0:
        hits.append(at)
        at = code.find(want, at + 1)
    return hits[0] if len(hits) == 1 else None


def fit_to_room(blob, dat_dec, ko, syll2code, typ, room, report):
    """자리 안에 최대한 많은 이벤트를 담는다. (packed, plain, 번역수, 원문수)"""
    plain, done, skipped = translate(blob, dat_dec, ko, syll2code, report)
    if plain is None:
        return None, None, 0, 0
    packed = _pack_best(plain, typ)
    if packed is not None and len(packed) <= room:
        return packed, plain, done, skipped
    # 안 들어가면 **어떤 이벤트가 압축을 얼마나 키우는지 실제로 재서** 싼 것부터
    # 담는다. 예전에는 "번역이 원문보다 몇 바이트 늘었나"로 버릴 순서를 정했는데,
    # 페이지는 원문 길이로 잘리고 채워지므로 그 값은 늘 0 이하라 뜻이 없었다.
    _ts, events = scen.find_text_region(blob)
    every = {ei for ei in range(len(events)) if ko.get(str(ei))}
    junk = []
    base_plain, base_done, base_skipped = translate(blob, dat_dec, ko, syll2code, junk, every)
    base = _pack_best(base_plain, typ) if base_plain is not None else None
    if base is None or len(base) > room:
        return None, None, 0, 0
    costs = []
    for ei in sorted(every):
        one, _d, _s = translate(blob, dat_dec, ko, syll2code, junk, every - {ei})
        got = _pack_best(one, typ) if one is not None else None
        if got is not None:
            costs.append((len(got) - len(base), ei))
    costs.sort()
    keep = set()
    packed, plain, done, skipped = base, base_plain, base_done, base_skipped
    for _cost, ei in costs:
        one, done_t, skipped_t = translate(blob, dat_dec, ko, syll2code, junk,
                                           every - keep - {ei})
        got = _pack_best(one, typ) if one is not None else None
        if got is not None and len(got) <= room:
            keep.add(ei)
            packed, plain, done, skipped = got, one, done_t, skipped_t
    return packed, plain, done, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description="업데이트 실행코드 안의 시나리오 한글화")
    ap.add_argument("--dat", required=True, help="본인의 **원본** CULDCEPT.DAT")
    ap.add_argument("--code", required=True, help="입력 실행코드(카드 DB 가 한글인 것)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--texts", default="dialogue_ko.json")
    ap.add_argument("--blocks", default="block_ko.json",
                    help="전투 중 캐릭터 대사(낱개 엔트리) 번역")
    ap.add_argument("--repack", action="store_true",
                    help="붙어 있는 블롭 사이에서 자리를 옮긴다(포인터를 고친다). "
                         "지금은 넷 다 여유가 없어 서로 뺏기만 하므로 기본은 꺼 둔다 — "
                         "실행코드에 안전하게 쓸 수 있는 빈 자리를 찾은 뒤에 켤 것")
    args = ap.parse_args()

    dat = Dat(open(args.dat, "rb").read())
    syll2code = wansung.build_fixed_map(
        fontmod.parse_cmap(huffman.decompress(dat.entry(FONT_ENTRY))))
    texts = json.load(open(args.texts, encoding="utf-8"))
    blocks = json.load(open(args.blocks, encoding="utf-8"))
    texts = dict(texts)
    texts.update(blocks)                 # 키가 "e1947_s3" / "1869" 로 겹치지 않는다
    sigs = dat_sections(dat, sorted(int(k) for k in blocks))
    print("DAT 지문 %d개(시나리오 섹션 + 캐릭터 대사 엔트리)" % len(sigs))

    code = bytearray(open(args.code, "rb").read())
    report, seen, found, i = [], set(), [], 0
    sizes = {len(dec) for cands in sigs.values() for _n, dec in cands}
    sizes |= {n - 2 for n in sizes} | {n + 2 for n in sizes}
    while i < len(code) - 8:
        if code[i] not in (0x08, 0x0C):
            i += 1
            continue
        # 헤더의 **해제 크기**를 먼저 읽어 거른다. 이게 없으면 3MB 를 전부 풀어 보느라
        # 십수 분이 걸린다(그러다 프로세스가 죽기도 한다).
        try:
            declared, _ = huffman.parse_varint(bytes(code), i + 1)
        except Exception:                               # noqa: BLE001
            i += 1
            continue
        if declared not in sizes:
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
        # 앞머리가 같은 후보가 여럿일 수 있다(1869/1870). 실제로 맞춰 보고 고른다.
        best = None
        for cand_name, cand_dec in sigs[bytes(blob[:32])]:
            if cand_name in seen:
                continue
            trial, done_c, _s = translate(blob, cand_dec, texts.get(cand_name, {}),
                                          syll2code, [])
            if trial is not None and (best is None or done_c > best[2]):
                best = (cand_name, cand_dec, done_c)
        if best is None:
            i += 1
            continue
        name, dat_dec = best[0], best[1]
        seen.add(name)
        room = compressed_length(bytes(code), i, blob)
        pad = 0
        while pad < 16 and i + room + pad < len(code) and code[i + room + pad] == 0:
            pad += 1
        room += pad          # 블롭 뒤 정렬용 0 바이트까지가 실제로 쓸 수 있는 자리
        found.append({"off": i, "room": room, "name": name, "blob": blob,
                      "dat": dat_dec, "typ": code[i]})
        i += room

    # ── 붙어 있는 블롭끼리 자리를 나눈다 ────────────────────────────────
    groups, run = [], []
    for item in found:
        if run and run[-1]["off"] + run[-1]["room"] == item["off"]:
            run.append(item)
        else:
            if run:
                groups.append(run)
            run = [item]
    if run:
        groups.append(run)

    patched = 0
    for group in groups:
        pointers = [find_pointer(bytes(code), it["off"]) for it in group]
        total = sum(it["room"] for it in group)
        repacking = bool(args.repack) and len(group) >= 2 and all(p is not None for p in pointers)
        if not repacking:
            plan = [(it, it["room"]) for it in group]
        else:
            # 자리 재분배: 자기 자리에 이미 들어가는 블롭은 그대로 두고, 모자란
            # 것들끼리 남은 자리를 필요한 만큼 비례해 나눈다.
            fulls = []
            for it in group:
                p, _pl, _d, _s = fit_to_room(it["blob"], it["dat"], texts.get(it["name"], {}),
                                             syll2code, it["typ"], 1 << 30, [])
                fulls.append(len(p) if p else it["room"])
            need = sum(fulls)
            print("  붙어 있는 블롭 %d개 — 자리 %d, 전부 번역하면 %d (%+d)"
                  % (len(group), total, need, need - total))
            if need <= total:
                plan = [(it, f) for it, f in zip(group, fulls)]
            else:
                fixed = [f if f <= it["room"] else None for it, f in zip(group, fulls)]
                spare = total - sum(f for f in fixed if f is not None)
                hungry = sum(f for f, x in zip(fulls, fixed) if x is None)
                plan = []
                for it, f, x in zip(group, fulls, fixed):
                    plan.append((it, x if x is not None else max(64, spare * f // hungry)))
        cursor = group[0]["off"]
        for (it, room), ptr in zip(plan, pointers):
            at = cursor if repacking else it["off"]
            ko = texts.get(it["name"], {})
            packed, _plain, done, skipped = fit_to_room(it["blob"], it["dat"], ko, syll2code,
                                                        it["typ"], room, report)
            if packed is None or len(packed) > room:
                # 원문 그대로 둔다. 원문이 배정된 자리보다 크면 **자리를 옮기지 않는다** —
                # 그냥 쓰면 다음 블롭이나 그 뒤 데이터를 덮어쓴다.
                print("  %s: 자리 %d 에 넣지 못했다 — 원문 그대로 둔다" % (it["name"], room))
                if at != it["off"] or it["room"] > room:
                    print("     ! 자리를 옮기던 중이라 이 묶음의 재분배를 취소한다")
                    return 2
                packed = bytes(code[it["off"]:it["off"] + it["room"]])
                done = skipped = 0
            code[at:at + len(packed)] = packed
            if repacking and ptr is not None and at != it["off"]:
                struct.pack_into("<I", code, ptr, at + BASE_VA)
            _ts, events = scen.find_text_region(it["blob"])
            print("  %s +%d: 이벤트 %d/%d개 번역, %d/%d바이트%s"
                  % (it["name"], at, done, len(events), len(packed), room,
                     " (자리 옮김)" if at != it["off"] else ""))
            cursor = at + len(packed) if repacking else it["off"] + it["room"]
            patched += 1
        if repacking:
            tail = group[-1]["off"] + group[-1]["room"]
            if cursor < tail:
                code[cursor:tail] = bytes(tail - cursor)  # 남은 자리는 0 으로

    for line in report[:20]:
        print(line)
    open(args.out, "wb").write(bytes(code))
    print("시나리오 블롭 %d개 한글화 -> %s" % (patched, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
