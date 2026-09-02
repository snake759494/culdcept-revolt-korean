#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""실행 중인 게임이 **정말로** 한글 패치를 읽고 있는지 확인한다.

파일 검사(verify_install.py)는 디스크에 무엇이 있는지만 본다. 그런데 설치는
제대로 했는데 화면에는 옛날 텍스트가 나오는 제보가 반복됐다(이슈 #17). 그런
경우 남는 질문은 하나다 — **게임이 지금 어느 CULDCEPT.DAT 을 읽고 있는가?**

이 도구는 실행 중인 Azahar 프로세스의 메모리를 읽어, 게임이 로드해 둔 카드
데이터베이스가 한글인지 원문인지 직접 확인한다. 읽기만 하며 아무것도 바꾸지
않는다. 윈도우 전용.

    1) Azahar 로 게임을 켜고 아무 화면에나 들어간다 (타이틀 화면도 됨)
    2) 게임을 켜 둔 채로 이 스크립트를 실행한다

        python check_running_game.py

카드 이름·능력 문자열을 완성형 한글 코드로 만들어 찾기 때문에, 게임 원문을
저장소에 담지 않아도 판정할 수 있다.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import struct
import subprocess
import sys
from pathlib import Path

from culdcept import font as fontmod
from culdcept import huffman, wansung

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_TID = "00040000000F5700"
FONT_ENTRY, CARD_ENTRY = 1054, 1190
# 한글 쪽 표본은 번역문에서, 원문 쪽 표본은 가나(번역해도 그대로 남지 않는 조합)에서
# 고른다. 카드 능력문의 「セプターを止まらせる」는 한글판에는 존재할 수 없다.
KO_SAMPLES = ["올드 윌로우", "방어형", "크리처"]
JP_SAMPLES = ["オールドウィロウ", "セプターを止まらせる", "クリーチャー"]

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
ULPTR = ctypes.c_ulonglong


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ULPTR), ("AllocationBase", ULPTR),
                ("AllocationProtect", wt.DWORD), ("__align", wt.DWORD),
                ("RegionSize", ULPTR), ("State", wt.DWORD),
                ("Protect", wt.DWORD), ("Type", wt.DWORD), ("__pad", wt.DWORD)]


k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.VirtualQueryEx.restype = ctypes.c_size_t
k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
k32.ReadProcessMemory.restype = wt.BOOL
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


def _entry(path: Path, index: int) -> bytes:
    with open(path, "rb") as handle:
        handle.seek(index * 8)
        offset, size = struct.unpack("<II", handle.read(8))
        handle.seek(offset)
        return handle.read(size)


def _syllable_map(dat: Path) -> dict:
    return wansung.build_fixed_map(fontmod.parse_cmap(huffman.decompress(_entry(dat, FONT_ENTRY))))


def _encode(text: str, syll2code: dict) -> bytes:
    out = b""
    for ch in text:
        code = syll2code.get(ch)
        out += bytes([code >> 8, code & 0xFF]) if code else ch.encode("cp932")
    return out


def _azahar_pids() -> list[int]:
    pids = []
    for image in ("azahar.exe", "citra-qt.exe", "lime3ds.exe"):
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            if line.startswith('"') and image.split(".")[0] in line.lower():
                try:
                    pids.append(int(line.split('","')[1]))
                except (IndexError, ValueError):
                    pass
    return pids


def _scan(pid: int, patterns: list[tuple[str, bytes]]) -> dict:
    handle = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return {}
    counts = {name: 0 for name, _ in patterns}
    mbi = MBI()
    address = 0
    while address < 0x7FFF_FFFF_FFFF:
        if not k32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            break
        base, size = int(mbi.BaseAddress), int(mbi.RegionSize)
        readable = mbi.State == MEM_COMMIT and not (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD))
        if readable and 0 < size < (1 << 31):
            buffer = (ctypes.c_char * size)()
            got = ctypes.c_size_t(0)
            if k32.ReadProcessMemory(handle, ctypes.c_void_p(base), buffer, size, ctypes.byref(got)) and got.value:
                data = bytes(buffer[:got.value])
                for name, pattern in patterns:
                    counts[name] += data.count(pattern)
        if size == 0:
            break
        address = base + size
    k32.CloseHandle(handle)
    return counts


def main() -> int:
    if os.name != "nt":
        print("윈도우 전용 도구입니다.")
        return 2
    user_dir = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path(
        os.environ.get("APPDATA", "")) / "Azahar"
    dat = user_dir / "load" / "mods" / BASE_TID / "romfs" / "CULDCEPT.DAT"
    if not dat.is_file():
        print(f"한글패치 CULDCEPT.DAT 을 찾지 못했습니다: {dat}")
        return 2

    syll2code = _syllable_map(dat)
    patterns = [(f"한글 {text}", _encode(text, syll2code)) for text in KO_SAMPLES]
    patterns += [(f"원문 {text}", text.encode("cp932")) for text in JP_SAMPLES]

    pids = _azahar_pids()
    if not pids:
        print("실행 중인 에뮬레이터를 찾지 못했습니다. 게임을 켠 상태로 다시 실행하세요.")
        return 2

    total = {name: 0 for name, _ in patterns}
    for pid in pids:
        print(f"프로세스 {pid} 검사 중… (수십 초 걸릴 수 있습니다)")
        for name, value in _scan(pid, patterns).items():
            total[name] += value

    print()
    for name, _ in patterns:
        print(f"  {name:<28} {total[name]}건")
    print()

    ko = sum(total[f"한글 {text}"] for text in KO_SAMPLES)
    jp = sum(total[f"원문 {text}"] for text in JP_SAMPLES)
    if ko and not jp:
        print("결과: 게임이 한글 카드 DB 를 읽고 있습니다. 패치가 제대로 적용된 상태입니다.")
        return 0
    if jp and not ko:
        print("결과: 게임이 ★원문 카드 DB★ 를 읽고 있습니다.")
        print("      설치한 폴더와 게임이 실제로 쓰는 폴더가 다르거나, 세이브 스테이트를")
        print("      불러왔거나, 게임 쪽 CULDCEPT.DAT 이 구버전입니다.")
        print("      verify_install.cmd 의 '다른 에뮬레이터 폴더' / '세이브 스테이트' 항목을 보세요.")
        return 1
    if ko and jp:
        print("결과: 한글과 원문이 섞여 있습니다. 세이브 스테이트를 불러왔을 때 나타나는 상태입니다.")
        print("      Azahar 를 끄고 스테이트 없이 게임을 새로 시작한 뒤 다시 검사하세요.")
        return 1
    print("결과: 카드 DB 가 아직 메모리에 없습니다. 게임을 조금 진행한 뒤 다시 실행하세요.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
