#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""화면에 나오는 **원문(일본어)이 어디서 오는지** 실행 중 메모리에서 추적한다.

배경: 패치본 파일 안에는 그 자리에 한글이 들어 있는데도 화면에는 원문이 나오는
장면이 있다(이슈 #27/#28/#35 — "실력을보여라" 퀘스트 대사, 브리드 드래곤 카드 이름).
파일 전체를 모든 코덱으로 재귀 해제해 뒤졌지만 원문 사본은 그 한 자리뿐이었다.
그러니 게임은 파일이 아닌 **다른 어딘가**에서 그 글자를 읽고 있다.

이 도구는 실행 중인 게임 메모리에서 그 원문 바이트를 찾아, 주변을 파일로 떠 준다.
그 조각을 보면 어떤 구조에서 온 것인지 알아낼 수 있다.

쓰는 법
  1) 문제의 화면(원문이 보이는 대사·카드 이름)을 띄워 둔 채로
  2) 이 스크립트를 실행한다

        python trace_source.py

  3) 만들어진 `원문추적.bin` 을 이슈에 첨부해 주세요.

원문(일본어)은 저장소에 담지 않는다 — 찾을 문자열은 **본인의 원본 DAT** 에서 읽는다.
뜬 조각에는 게임 데이터가 들어가므로 배포물에 포함하지 말고 제보용으로만 쓴다.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import sys
from pathlib import Path

from check_running_game import (MBI, PROCESS_QUERY_INFORMATION, PROCESS_VM_READ,
                                _azahar_pids)
from culdcept import huffman, scen
from culdcept.dat import Dat

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

BASE_TITLE_ID = "00040000000F5700"
# 찾을 자리: (엔트리, 섹션, 그 안의 오프셋, 길이, 설명)
TARGETS = (
    (1947, 3, 8844, 22, "퀘스트 대사"),
    (1190, None, 201592, 16, "카드 이름"),
)
DUMP = 8192


def _find_original(user_dir: Path) -> Path | None:
    """원본 DAT — 에뮬레이터 덤프 폴더에 있으면 그걸 쓴다."""
    cand = user_dir / "dump" / "romfs" / BASE_TITLE_ID / "CULDCEPT.DAT"
    return cand if cand.is_file() else None


def _needles(original: Path):
    """원본에서 찾을 바이트열을 뽑는다(원문은 저장소에 없다)."""
    data = Dat(original.read_bytes())
    out = []
    for index, section, offset, length, label in TARGETS:
        try:
            entry = data.entry(index)
            blob = entry
            if section is not None:
                secs = scen.parse_sections(entry) or []
                if section >= len(secs):
                    continue
                off, ln = secs[section]
                blob = entry[off:off + ln]
            if blob[:1] and blob[0] in (0x08, 0x0C):
                blob = huffman.decompress(blob)
            needle = bytes(blob[offset:offset + length])
        except Exception as exc:                        # noqa: BLE001
            print("  %s 준비 실패: %s" % (label, exc))
            continue
        if len(needle) == length:
            out.append((label, needle))
    return out


def _search(pid: int, needles, handle_out):
    handle = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        print("프로세스를 열지 못했습니다.")
        return 0
    mbi = MBI()
    address = found = 0
    while address < 0x7FFF_FFFF_FFFF:
        if not k32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi),
                                  ctypes.sizeof(mbi)):
            break
        base, size, state, prot = mbi.BaseAddress, mbi.RegionSize, mbi.State, mbi.Protect
        address = base + size
        if state != 0x1000 or prot in (0x01, 0x104) or size > (1 << 30):
            continue
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not (k32.ReadProcessMemory(handle, ctypes.c_void_p(base), buf, size,
                                      ctypes.byref(got)) and got.value):
            continue
        block = buf.raw[:got.value]
        for label, needle in needles:
            start = 0
            while True:
                i = block.find(needle, start)
                if i < 0:
                    break
                start = i + 1
                found += 1
                lo = max(0, i - DUMP // 2)
                hi = min(len(block), i + DUMP // 2)
                print("  찾음: %-10s 주소 0x%X (영역 0x%X + 0x%X)" % (label, base + i, base, size))
                handle_out.write(struct.pack("<QQQ", base + i, base, size))
                handle_out.write(struct.pack("<II", lo, hi - lo))
                handle_out.write(label.encode("utf-8").ljust(32, b"\0"))
                handle_out.write(block[lo:hi])
                if found >= 8:
                    k32.CloseHandle(handle)
                    return found
    k32.CloseHandle(handle)
    return found


def main() -> int:
    user_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path.home() / "AppData" / "Roaming" / "Azahar"
    original = _find_original(user_dir)
    if original is None:
        print("원본 CULDCEPT.DAT(에뮬레이터 dump 폴더)을 찾지 못했습니다:")
        print("  %s" % (user_dir / "dump" / "romfs" / BASE_TITLE_ID / "CULDCEPT.DAT"))
        print("Azahar 에서 한 번 romfs 를 덤프해 두면 됩니다.")
        return 2
    pids = _azahar_pids()
    if not pids:
        print("실행 중인 Azahar 가 없습니다. 문제의 화면을 띄운 채로 다시 실행하세요.")
        return 2
    needles = _needles(original)
    if not needles:
        print("찾을 바이트열을 준비하지 못했습니다.")
        return 1
    out_path = Path("원문추적.bin")
    print("프로세스 %d 검사 중… (수십 초 걸립니다)\n" % pids[0])
    with out_path.open("wb") as handle:
        handle.write(b"CULDTRACE1")
        count = _search(pids[0], needles, handle)
    if not count:
        print("\n원문 바이트열이 메모리에 없습니다.")
        print("문제의 화면(원문이 보이는 대사나 카드 이름)이 떠 있는 상태에서 실행해야 합니다.")
        out_path.unlink(missing_ok=True)
        return 1
    print("\n%d군데를 떴습니다 -> %s (%.0f KB)" % (count, out_path, out_path.stat().st_size / 1024))
    print("이 파일을 이슈에 첨부해 주세요. 원문이 어느 구조에서 오는지 알아낼 수 있습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
