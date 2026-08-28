#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""내 CULDCEPT.DAT 에 한글패치가 제대로 들어갔는지 항목별로 검사한다.

    python verify_patch.py "<게임이 읽는 CULDCEPT.DAT 경로>"

"분명히 패치했는데 화면이 그대로"일 때, **게임이 실제로 읽는 파일**을 이걸로
검사하면 어디까지 적용됐는지 바로 보인다. LayeredFS 를 쓴다면 반드시
`load/mods/00040000000F5700/romfs/CULDCEPT.DAT` 를 검사할 것.

한글 판정 방식: 이 패치는 한글 음절을 **JIS 제1수준 한자 코드(0x889F~0x9872)** 에
배정해 넣는다(완성형 방식, docs/FORMAT.md §6). 따라서 특정 위치의 바이트가 그
범위의 2바이트 코드로 이루어져 있으면 한글로 바뀐 것이다. 이 방식이라 저장소에
일본어 원문을 두지 않고도 검사할 수 있다.

단, **원문이 한자인 자리는 판정에 쓸 수 없다** — 원문 한자도 같은 코드 범위라
구분이 안 되기 때문이다. 그래서 검사 지점은 **원문이 가타카나(선두 0x83)** 인
문자열만 고른다. 가타카나는 한글 배정 범위와 겹치지 않아 확실히 갈린다.
"""
import argparse
import os
import struct
import sys

from culdcept import huffman

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# (엔트리, 압축해제 후 오프셋, 길이) — 원본 기준 위치. 전부 원문이 가타카나인 자리.
PROBE_CARD_NAME = (1190, 84608, 16)      # 어떤 방어구 카드의 이름
PROBE_CARD_NAME2 = (1190, 103135, 12)    # 어떤 무기 카드의 이름
PROBE_UI_LABEL = (1190, 183653, 6)       # 덱 편집 좌측 탭 라벨
# 확인 메시지: 원문은 제어코드 '/'(0x2F) 로 끝난다.
# 끝 바이트가 0x00 이면 v1.9+ 수정본, 0x20 이면 v1.8 이하(예/아니오 밀림 버그).
CONFIRM_MSGS = [(1190, 211679, 31), (1190, 211711, 29)]
UI_ATLASES = [("타이틀/맵 메뉴", 711), ("카드 필터", 608), ("배틀 커맨드", 962)]
NARRATION_ENTRIES = [1594, 1595, 1596, 1599, 1601]


def is_hangul_bytes(b):
    """완성형 배정 범위(0x889F~0x9872)의 2바이트 코드로만 이루어졌는지."""
    if len(b) < 2:
        return False
    n = 0
    i = 0
    while i + 1 < len(b):
        c = (b[i] << 8) | b[i + 1]
        if 0x889F <= c <= 0x9872:
            n += 1
            i += 2
        elif b[i] in (0x20, 0x00):        # 공백/널 패딩
            i += 1
        else:
            return False
    return n > 0


def entry(d, e):
    off = struct.unpack_from("<I", d, e * 8)[0]
    size = struct.unpack_from("<I", d, e * 8 + 4)[0]
    return off, size, d[off] if size else None


def main(path):
    d = open(path, "rb").read()
    n = struct.unpack("<I", d[:4])[0] // 8
    print(f"파일: {path}")
    print(f"크기: {len(d):,} 바이트 / 엔트리 {n}개\n")

    ok = fail = 0

    def report(name, good, detail=""):
        nonlocal ok, fail
        print(f"  [{'O' if good else 'X'}] {name}{('  — ' + detail) if detail else ''}")
        if good:
            ok += 1
        else:
            fail += 1

    # ── 텍스트(카드 DB) ─────────────────────────────
    print("■ 텍스트 (엔트리 1190)")
    e, off, size = PROBE_CARD_NAME
    o, s, _ = entry(d, e)
    ui = huffman.decompress(d[o:o + s])
    report("카드 이름 한글화", is_hangul_bytes(ui[off:off + size]))
    e2, off2, size2 = PROBE_CARD_NAME2
    report("카드 이름 한글화 (2)", is_hangul_bytes(ui[off2:off2 + size2]))
    e3, off3, size3 = PROBE_UI_LABEL
    report("덱 편집 라벨 한글화", is_hangul_bytes(ui[off3:off3 + size3]))
    tails = [ui[o2 + l - 1] for _, o2, l in CONFIRM_MSGS]
    # 원문은 제어코드 "/"(0x2F) 로 끝난다. 번역문이 짧을 때 그 **뒤에** 뭔가를
    # 채우면(공백이든 널이든) 화면에 한 줄이 더 생겨 예/아니오 버튼이 밀린다.
    # 올바른 패치는 제어코드 앞쪽을 채워 원문처럼 0x2F 로 끝난다.
    if all(t == 0x2F for t in tails):
        report("확인 메시지 끝처리 (예/아니오 밀림)", True, "제어코드로 끝남 — 정상")
    elif all(t == 0x20 for t in tails):
        report("확인 메시지 끝처리 (예/아니오 밀림)", False,
               "뒤에 공백이 붙음(v1.8 이하) — 버튼이 화면 밖으로 밀림")
    else:
        report("확인 메시지 끝처리 (예/아니오 밀림)", False,
               "뒤에 널이 붙음(v1.9~v2.0) — 버튼 밀림 + 카드 설명이 비어 보임")

    # ── UI 버튼 이미지 ──────────────────────────────
    print("\n■ UI 버튼 이미지 (v1.8 이상)")
    for label, ent in UI_ATLASES:
        _, _, typ = entry(d, ent)
        report(f"{label} (엔트리 {ent})", typ == 0x08,
               "" if typ == 0x08 else f"타입 0x{typ:02x} — 미적용")

    # ── 나레이션 ───────────────────────────────────
    print("\n■ 양피지 나레이션 (v1.7 이상)")
    done = sum(1 for ent in NARRATION_ENTRIES if entry(d, ent)[2] == 0x08)
    report(f"나레이션 텍스처 {done}/{len(NARRATION_ENTRIES)}", done == len(NARRATION_ENTRIES),
           "" if done == len(NARRATION_ENTRIES) else "미적용 — 전체 패치 xdelta 를 쓰세요")

    print(f"\n결과: 통과 {ok} / 실패 {fail}")
    if fail:
        print("\n실패 항목이 있으면 확인할 것:")
        print("  1) 지금 검사한 파일이 **게임이 실제로 읽는 파일**이 맞는지")
        print("     (LayeredFS: load/mods/00040000000F5700/romfs/CULDCEPT.DAT)")
        print("  2) 에뮬레이터 로그에 'LayeredFS replacement file in use for /CULDCEPT.DAT' 가 뜨는지")
        print("  3) 실기라면 이 파일로 RomFS 를 다시 빌드했는지")
        print("  4) xdelta 를 적용한 원본이 일본판(Rev 2) 인지")
    else:
        print("모든 항목 적용 완료.")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CULDCEPT.DAT 한글패치 적용 상태 검사")
    ap.add_argument("dat", help="검사할 CULDCEPT.DAT")
    a = ap.parse_args()
    if not os.path.exists(a.dat):
        sys.exit(f"파일이 없습니다: {a.dat}")
    sys.exit(main(a.dat))
