#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""게임 업데이트(ver 1.2)의 실행코드 안에 있는 **카드 데이터베이스**를 한글화한다.

왜 필요한가
-----------
컬드셉트 리볼트의 v1.2 업데이트(타이틀 `0004000E000F5700`)에는 RomFS 가 없고
`.code` 하나만 들어 있다. 그런데 이 실행코드 안에 **카드 이름·능력·설명·플레이버가
통째로 들어 있다** — `CULDCEPT.DAT` 엔트리 1190 의 s0 섹션과 같은 자리다.

업데이트를 설치하면 게임은 카드 텍스트를 DAT 이 아니라 이 실행코드에서 읽는다.
그래서 `CULDCEPT.DAT` 만 한글화하면

    메뉴·UI(엔트리 1190 의 s2/s3)  → 한글
    카드 이름·능력(업데이트 코드)   → 원문 그대로

이 되어, 카드만 일본어로 보인다(이슈 #17). 업데이트를 깔지 않은 사람은 멀쩡한데
깐 사람만 카드가 원문인 이유가 이것이다.

무엇을 하나
-----------
번역문은 이미 `cards_ko.json` 에 있다. 업데이트 코드의 카드 문자열 1,943개 중
1,927개(96.9%)가 본편 DAT 의 문자열과 **바이트까지 동일**하므로, 본인 파일에서
원문 → 한글 대응표를 만들어 그대로 재사용한다. v1.2 에서 문구가 바뀐 몇 개는
`update_extra_ko.json` 이 원문 해시로 채운다.

DAT 과 같은 규칙을 지킨다 — **제자리 교체, 원문 바이트 길이 이하, 남는 자리는
공백(0x20)**. 널로 채우면 레코드 필드가 밀려 카드 설명이 통째로 비어 버린다.

쓰는 법
-------
    python apply_update_code.py --dat 원본/CULDCEPT.DAT \
        --update "<Azahar>/sdmc/.../title/0004000e/000f5700/content/00000001.app" \
        --out code.bin

`--update` 에는 업데이트 `.app`(평문 NCCH) 또는 이미 꺼낸 `.code` 를 준다.
결과 `code.bin` 은 `load/mods/<타이틀ID>/exefs/code.bin` 에 두면 된다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import tools_blz
from culdcept import cardtext
from culdcept import font as fontmod
from culdcept import huffman, wansung

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FONT_ENTRY, CARD_ENTRY = 1054, 1190
PAD = 0x20
# 엔트리 1190 을 풀면 나오는 5섹션 컨테이너의 s0(카드 DB). 업데이트 코드에도
# 같은 길이로 통째로 들어 있다.
S0_OFFSET, S0_LENGTH = 0x28, 153786


def _entry(dat: bytes, index: int) -> bytes:
    offset, size = struct.unpack_from("<II", dat, index * 8)
    return dat[offset:offset + size]


def extract_code(path: Path) -> bytes:
    """업데이트 `.app`(NCCH) 또는 `.code` 에서 압축 해제된 실행코드를 얻는다."""
    blob = path.read_bytes()
    if blob[0x100:0x104] == b"NCCH":
        exefs = struct.unpack_from("<I", blob, 0x1A0)[0] * 0x200
        if not exefs:
            raise ValueError("업데이트 NCCH 에 ExeFS 가 없습니다.")
        name = blob[exefs:exefs + 8].rstrip(b"\0")
        if name != b".code":
            raise ValueError(f"ExeFS 첫 섹션이 .code 가 아닙니다: {name!r}")
        offset, size = struct.unpack_from("<II", blob, exefs + 8)
        blob = blob[exefs + 0x200 + offset: exefs + 0x200 + offset + size]
    return tools_blz.decompress(blob)


def build_translation(dat: bytes, cards_ko: dict) -> tuple[dict, dict]:
    """본인 DAT 에서 {원문 바이트: 한글 뷰} 대응표와 음절→코드 표를 만든다."""
    syll2code = wansung.build_fixed_map(fontmod.parse_cmap(huffman.decompress(_entry(dat, FONT_ENTRY))))
    ui = huffman.decompress(_entry(dat, CARD_ENTRY))
    raw2ko = {}
    for index, raw in enumerate(cardtext.enum_unique(ui)):
        view = cards_ko.get(str(index))
        if view is not None:
            raw2ko[raw] = view
    return raw2ko, syll2code


def find_card_db(code: bytes, dat: bytes) -> int:
    """실행코드 안에서 카드 DB 가 시작하는 위치를 찾는다.

    본인 DAT 의 s0 앞부분을 그대로 찾는다. v1.2 는 카드 수치를 손봤지만 이 앞부분은
    그대로라 128바이트 앵커면 충분하다. 혹시 어긋나면 뒤쪽 앵커로 다시 시도한다.
    """
    s0 = huffman.decompress(_entry(dat, CARD_ENTRY))[S0_OFFSET:S0_OFFSET + S0_LENGTH]
    for probe_at in (0, 0x400, 0x1000, 0x4000):
        anchor = s0[probe_at:probe_at + 128]
        if len(anchor) < 128:
            break
        found = code.find(anchor)
        if found >= 0:
            return found - probe_at
    return -1


def _pad_fill(view: str, tokens, syll2code: dict, encoded: bytes, target: int) -> bytes:
    """남는 자리를 **공백**으로 채운다(널 금지). 제어코드로 끝나면 그 앞에 채운다."""
    need = target - len(encoded)
    if need <= 0:
        return encoded
    cut = None
    for i in range(max(0, len(view) - 12), len(view)):
        if view[i] == chr(10) and not any("가" <= c <= "힣" for c in view[i:]):
            cut = i
            break
    if cut is not None:
        padded = cardtext.encode(view[:cut] + " " * need + view[cut:], tokens, syll2code)
        if len(padded) == target:
            return padded
    return encoded + bytes([PAD]) * need


def _truncate(data: bytes, limit: int) -> bytes:
    if len(data) <= limit:
        return data
    out = bytearray()
    i = 0
    while i < len(data):
        step = 3 if data[i] == 0x03 else (2 if 0x81 <= data[i] <= 0xFC and i + 1 < len(data) else 1)
        if len(out) + step > limit:
            break
        out += data[i:i + step]
        i += step
    return bytes(out)


def patch(code: bytes, start: int, raw2ko: dict, extra: dict, syll2code: dict) -> tuple[bytes, dict]:
    out = bytearray(code)
    stats = {"번역": 0, "추가번역": 0, "미일치": 0}
    region = code[start:start + S0_LENGTH]
    cursor = 0
    for index in range(len(region)):
        if region[index] != 0:
            continue
        raw = bytes(region[cursor:index])
        cursor = index + 1
        if len(raw) < 2:
            continue
        view = raw2ko.get(raw)
        key = "추가번역" if view is None else "번역"
        if view is None:
            view = extra.get(hashlib.sha1(raw).hexdigest())
            if view is None:
                continue
        _, tokens = cardtext.tokenize(raw)
        encoded = _truncate(cardtext.encode(view, tokens, syll2code), len(raw))
        body = _pad_fill(view, tokens, syll2code, encoded, len(raw))
        if len(body) != len(raw):                    # 길이가 어긋나면 건드리지 않는다
            continue
        out[start + index - len(raw): start + index] = body
        stats[key] += 1
    return bytes(out), stats


def make_ips_patch(source: bytes, target: bytes) -> bytes:
    """길이가 같은 두 바이트열의 최소 IPS 패치. 바뀐 바이트(=번역문)만 담긴다."""
    if len(source) != len(target):
        raise ValueError("IPS 는 길이가 같아야 합니다")
    patch = bytearray(b"PATCH")
    i = 0
    while i < len(source):
        if source[i] == target[i]:
            i += 1
            continue
        start = i
        while i < len(source) and source[i] != target[i]:
            i += 1
        while start < i:
            size = min(i - start, 0xFFFF)
            if start > 0xFFFFFF:
                raise ValueError(f"IPS 로 담기에 오프셋이 큽니다: 0x{start:x}")
            patch += start.to_bytes(3, "big") + size.to_bytes(2, "big") + target[start:start + size]
            start += size
    return bytes(patch + b"EOF")


def apply_ips_patch(source: bytes, patch: bytes) -> bytes:
    """IPS 를 적용한다(RLE 레코드 포함). install_patch.py 가 함께 쓴다."""
    if patch[:5] != b"PATCH":
        raise ValueError("IPS 파일이 아닙니다")
    out = bytearray(source)
    pos = 5
    while pos + 3 <= len(patch):
        if patch[pos:pos + 3] == b"EOF":
            break
        offset = int.from_bytes(patch[pos:pos + 3], "big")
        size = int.from_bytes(patch[pos + 3:pos + 5], "big")
        pos += 5
        if size:
            out[offset:offset + size] = patch[pos:pos + size]
            pos += size
        else:                                   # RLE
            run = int.from_bytes(patch[pos:pos + 2], "big")
            out[offset:offset + run] = bytes([patch[pos + 2]]) * run
            pos += 3
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="업데이트 실행코드의 카드 DB 한글화")
    ap.add_argument("--dat", required=True, help="본인의 **원본** CULDCEPT.DAT")
    ap.add_argument("--update", required=True, help="업데이트 .app 또는 .code")
    ap.add_argument("--out", default="code.bin", help="출력 code.bin")
    ap.add_argument("--ips", help="원본 실행코드 -> 한글 실행코드 IPS 패치도 함께 저장")
    ap.add_argument("--cards", default="cards_ko.json")
    ap.add_argument("--extra", default="update_extra_ko.json")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    dat = Path(args.dat).read_bytes()
    cards_ko = json.loads(Path(args.cards).read_text(encoding="utf-8"))
    extra_path = Path(args.extra)
    if not extra_path.is_absolute():
        extra_path = here / extra_path
    extra = json.loads(extra_path.read_text(encoding="utf-8")) if extra_path.is_file() else {}
    extra = {k: v for k, v in extra.items() if not k.startswith("_")}

    code = extract_code(Path(args.update))
    print(f"실행코드 {len(code):,}바이트")

    raw2ko, syll2code = build_translation(dat, cards_ko)
    print(f"번역 대응표 {len(raw2ko):,}개")

    start = find_card_db(code, dat)
    if start < 0:
        print("실행코드에서 카드 DB 를 찾지 못했습니다. 업데이트 버전이 다를 수 있습니다.")
        return 1
    print(f"카드 DB 위치 0x{start:x} ~ 0x{start + S0_LENGTH:x}")

    patched, stats = patch(code, start, raw2ko, extra, syll2code)
    if len(patched) != len(code):
        print("길이가 달라졌습니다 — 중단합니다.")
        return 1
    Path(args.out).write_bytes(patched)
    print(f"교체: 기존 번역 {stats['번역']:,}개 / 추가 번역 {stats['추가번역']}개")
    print(f"저장: {args.out} ({len(patched):,}바이트)")
    if args.ips:
        ips = make_ips_patch(code, patched)
        Path(args.ips).write_bytes(ips)
        print(f"IPS: {args.ips} ({len(ips):,}바이트)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
