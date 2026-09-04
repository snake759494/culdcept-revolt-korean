#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""화면에 지금 떠 있는 **그 장면**의 한글 대사가 게임 메모리에 올라와 있는지 본다.

`check_running_game.py` 는 카드 DB 만 본다. 그래서 "카드는 한글인데 이 대사만
원문"인 상태를 구분하지 못했다(이슈 #26/#27).

이 도구는 문제의 대사가 들어 있는 자리(**엔트리 1947 / 섹션 3**)에서 한국어
문장을 직접 읽어 와, 실행 중인 게임 메모리에서 그 바이트열을 찾는다.

  * 찾으면  -> 게임이 우리 파일을 읽고 있다. 화면의 원문은 다른 데서 온 것이다.
  * 못 찾으면 -> 게임이 그 섹션을 우리 파일에서 읽지 않고 있다.

쓰는 법

  1) 문제의 장면(예: "실력을보여라" 첫 대사)을 화면에 띄운 채로 둔다
  2) 게임을 켜 둔 채 이 스크립트를 실행한다

        python check_scene.py

원문(일본어)은 담지 않는다 — 비교 대상은 전부 본인 파일에서 읽어 온다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from check_running_game import _azahar_pids, _scan, _syllable_map     # noqa: E402
from culdcept import huffman, scen                                    # noqa: E402
from culdcept.dat import Dat                                          # noqa: E402

BASE_TITLE_ID = "00040000000F5700"
SCENE_ENTRY = 1947          # 2장 — "실력을보여라" 등이 들어 있는 시나리오 컨테이너
SCENE_SECTIONS = (3, 5)     # s3 = 문제의 장면, s5 = 비교용(정상 보고된 장면)
PROBE_PER_SECTION = 6       # 섹션마다 확인할 문장 수


def _find_dat(user_dir: Path) -> Path | None:
    path = user_dir / "load" / "mods" / BASE_TITLE_ID / "romfs" / "CULDCEPT.DAT"
    return path if path.is_file() else None


def _korean_runs(section: bytes, syll2code: dict, want: int):
    """섹션에서 한글 코드가 연속으로 이어지는 구간을 길이 순으로 뽑는다."""
    codes = {c for c in syll2code.values()}
    runs, start, i = [], None, 0
    n = len(section)
    while i < n - 1:
        c = (section[i] << 8) | section[i + 1]
        if c in codes:
            if start is None:
                start = i
            i += 2
            continue
        if start is not None and i - start >= 12:
            runs.append(bytes(section[start:i]))
        start = None
        i += 1
    runs.sort(key=len, reverse=True)
    return runs[:want]


def main() -> int:
    user_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path.home() / "AppData" / "Roaming" / "Azahar"
    dat_path = _find_dat(user_dir)
    if dat_path is None:
        print(f"본편 CULDCEPT.DAT 을 찾지 못했습니다: {user_dir}")
        return 2
    pids = _azahar_pids()
    if not pids:
        print("실행 중인 Azahar 가 없습니다. 게임을 켜 둔 채로 다시 실행하세요.")
        return 2

    syll2code = _syllable_map(dat_path)
    data = Dat(open(dat_path, "rb").read())
    entry = data.entry(SCENE_ENTRY)
    sections = scen.parse_sections(entry)

    patterns, labels = [], {}
    for k in SCENE_SECTIONS:
        if sections is None or k >= len(sections):
            continue
        off, length = sections[k]
        try:
            dec = huffman.decompress(entry[off:off + length])
        except Exception as exc:                       # noqa: BLE001
            print(f"  s{k} 해제 실패: {exc}")
            continue
        runs = _korean_runs(dec, syll2code, PROBE_PER_SECTION)
        for index, run in enumerate(runs):
            name = f"s{k}#{index}"
            patterns.append((name, run))
            labels[name] = k

    if not patterns:
        print("확인할 한글 문장을 찾지 못했습니다 — 패치가 안 된 DAT 일 수 있습니다.")
        return 1

    print(f"프로세스 {pids[0]} 검사 중… (수십 초 걸릴 수 있습니다)\n")
    hits = _scan(pids[0], patterns)

    found = {}
    for name, _pat in patterns:
        found.setdefault(labels[name], []).append(hits.get(name, 0))
    for k in sorted(found):
        got = sum(1 for n in found[k] if n)
        total = len(found[k])
        tag = "s3 = 문제의 장면" if k == 3 else "s5 = 비교용 장면"
        mark = "O" if got else "X"
        print(f"[{mark}] 엔트리 {SCENE_ENTRY} 섹션 {k} ({tag}): "
              f"한글 문장 {got}/{total} 개가 게임 메모리에 있음")

    s3 = found.get(3, [])
    if s3 and not any(s3):
        print("\n판정: 이 섹션의 한글이 메모리에 전혀 없습니다.")
        print("      게임이 이 장면을 패치된 파일에서 읽지 않고 있습니다.")
        print("      (스테이지 '중단' 데이터로 이어서 하고 있다면 그것부터 지우고")
        print("       처음부터 다시 시작해 보세요)")
    elif any(s3):
        print("\n판정: 한글 대사가 메모리에 올라와 있습니다.")
        print("      게임은 패치된 파일을 읽고 있습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
