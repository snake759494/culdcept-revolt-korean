#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""자리를 옮긴 엔트리를 **원래 자리로 되돌린다**.

왜 중요한가: 엔트리가 원래 크기에 안 들어가 파일 끝으로 밀리면, 헤더는 새 자리를
가리키는데도 게임이 **옛 자리를 읽어** 원문을 그대로 보여 주는 일이 있다(이슈 #27,
그리고 #28의 "한 퀘스트 전체 대사 미번역" = 엔트리 1947). 그래서 조금 커졌다고
뒤로 밀지 말고, 손대지 않은 부분까지 다시 눌러 원래 크기 안에 넣는다.

두 가지를 더 해 본다.
  * 코덱을 **0x0c 로 바꿔** 본다. 0x0c 는 참조 창이 0x10 이라 0x08(0x0d)보다
    대개 더 작게 나온다. 게임은 첫 바이트로 코덱을 고르므로 바꿔 써도 된다.
  * 컨테이너 안 섹션을 하나씩, 그리고 엔트리 전체를 각각 눌러 본다.

    python refit_entries.py <원본DAT> <입력DAT> <출력DAT>
"""
import struct
import sys

sys.path.insert(0, ".")
from culdcept import huffman, scen                      # noqa: E402
from culdcept.dat import Dat                            # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def best_pack(raw, budget=None):
    """같은 내용을 가장 작게 담는 0x08/0x0c 블롭. 못 줄이면 None."""
    try:
        plain = huffman.decompress(raw)
    except Exception:                                   # noqa: BLE001
        return None
    best = None
    for typ in (0x0C, 0x08):
        try:
            cand = huffman.compress_real(plain, typ, effort=3, budget=budget)
        except Exception:                               # noqa: BLE001
            continue
        if huffman.decompress(cand) != plain:
            continue
        if best is None or len(cand) < len(best):
            best = cand
    return best


def shrink(entry, budget):
    """엔트리를 `budget` 바이트 안에 넣어 본다."""
    if len(entry) <= budget:
        return entry
    if entry and entry[0] in (0x08, 0x0C):              # 통째로 압축된 엔트리
        cand = best_pack(entry, budget)
        return cand if cand is not None and len(cand) < len(entry) else entry
    try:
        secs = scen.parse_sections(entry)
    except Exception:                                   # noqa: BLE001
        secs = None
    if not secs:
        return entry
    for k, (off, length) in enumerate(secs):
        if not length or entry[off] not in (0x08, 0x0C):
            continue
        blob = entry[off:off + length]
        cand = best_pack(blob)
        if cand is not None and len(cand) < len(blob):
            entry = scen.rebuild_container(entry, k, cand)
        if len(entry) <= budget:
            break
    return entry


def main():
    orig_path, in_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    o = Dat(open(orig_path, "rb").read())
    d = Dat(open(in_path, "rb").read())
    moved = [i for i in range(min(o.count, d.count)) if o.table[i][0] != d.table[i][0]]
    print("자리를 옮긴 엔트리 %d개" % len(moved))
    fixed, failed, worst = 0, [], 0
    for i in moved:
        ooff, osize = o.table[i]
        cur = shrink(d.entry(i), osize)
        if len(cur) <= osize:
            d.data[ooff:ooff + len(cur)] = cur
            if len(cur) < osize:
                d.data[ooff + len(cur):ooff + osize] = bytes(osize - len(cur))
            noff, nsize = d.table[i]
            d.data[noff:noff + nsize] = bytes(nsize)     # 밀려 있던 사본 제거
            d.table[i] = (ooff, len(cur))
            struct.pack_into("<II", d.data, i * 8, ooff, len(cur))
            fixed += 1
        else:
            failed.append((len(cur) - osize, i, len(cur), osize))
            worst = max(worst, len(cur) - osize)
    print("제자리 복귀 %d개 / 못 넣은 것 %d개 (최대 초과 %+d바이트)"
          % (fixed, len(failed), worst))
    for over, i, now, was in sorted(failed, reverse=True)[:20]:
        print("  ! e%d %d > %d (%+d)" % (i, now, was, over))
    open(out_path, "wb").write(d.build())
    print("저장 %s" % out_path)


if __name__ == "__main__":
    main()
