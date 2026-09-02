#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DLC 시나리오(.dlq)·맵(.dlm)의 **압축 섹션 안** 텍스트를 한글로 바꾼다.

리소스 페이로드를 복호화하면 `(offset, length)` 섹션 컨테이너가 나오고, 각 섹션은
게임 코덱(0x08/0x0c)으로 압축돼 있다. 시나리오 대사와 에피소드 제목이 여기 있다.

★ 제약: 섹션 사이에 여유가 1바이트도 없고 파일 크기도 바꿀 수 없다(헤더 0x04 =
  크기이고 CRC 대상). 그래서 재압축 결과가 **원본 섹션 크기 이하**여야 한다.
  huffman.compress_real(..., budget=원본크기) 가 이를 보장하고, 남는 자리는 0으로
  채워 섹션 길이를 그대로 유지한다(디코더는 해제크기 varint 로 끝을 판단한다).

대사는 **페이지 단위 길이 보존**으로 넣는다. 게임이 페이지(0x07)와 이벤트(0x00)의
바이트 위치를 그대로 참조하므로, 각 페이지를 원본 페이지 길이에 맞춰 공백으로
채운다. 번역하지 않은 이벤트는 원본 바이트를 그대로 복사한다.

쓰는 법::

    python apply_dlc_dialogue.py <DLC content 폴더> --base-dat 패치본/CULDCEPT.DAT \
        --texts dlc_dialogue_ko.json --output dlc_overlay --from-overlay dlc_overlay
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

from apply_dlc_text import RESOURCE_EXT, encode, make_ips, romfs_files, syllable_map
from culdcept import dlcres, huffman, scen

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TITLE_ID = "0004008c000f5700"
PAGE, EVENT, PAD = 0x07, 0x00, 0x20
PAGE_MARK = "▼"


def rebuild_events(section, text_start, edits, syll2code, report, label):
    """번역한 이벤트만 페이지 길이를 지켜 교체하고, 나머지는 원본을 그대로 둔다."""
    region = section[text_start:]
    events = region.split(bytes([EVENT]))
    # 마지막 조각이 비어 있으면 영역이 NUL 로 끝난다는 뜻이다 — 이벤트마다 NUL 하나씩.
    # 비어 있지 않으면 마지막 이벤트에는 종료 NUL 이 없다.
    ends_with_nul = bool(events) and events[-1] == b""
    if ends_with_nul:
        events = events[:-1]
    out = bytearray(section[:text_start])

    def terminator(index):
        last = index == len(events) - 1
        return b"" if (last and not ends_with_nul) else bytes([EVENT])

    for index, original in enumerate(events):
        view = edits.get(index)
        if view is None:
            out += original + terminator(index)
            continue
        opages = original.split(bytes([PAGE]))
        kpages = view.split(PAGE_MARK)
        if len(opages) != len(kpages):
            report.append("  ! %s 이벤트 %d 페이지 수 불일치(%d != %d) — 원본 유지"
                          % (label, index, len(kpages), len(opages)))
            out += original + terminator(index)
            continue
        rebuilt = bytearray()
        too_long = False
        for page_index, opage in enumerate(opages):
            enc = encode(kpages[page_index], syll2code)
            if len(enc) > len(opage):
                too_long = True
                break
            rebuilt += enc + bytes([PAD]) * (len(opage) - len(enc))
            if page_index < len(opages) - 1:
                rebuilt += bytes([PAGE])
        if too_long:
            report.append("  ! %s 이벤트 %d 번역이 원본 페이지보다 길어 원본 유지" % (label, index))
            out += original + terminator(index)
            continue
        out += rebuilt + terminator(index)
    if len(out) != len(section):
        raise ValueError("섹션 길이 보존 실패: %d != %d" % (len(out), len(section)))
    return bytes(out)


def rebuild_offsets(section, edits, syll2code, report, label):
    """오프셋으로 지정된 널 종료 문자열을 제자리 교체(공백 패딩)."""
    out = bytearray(section)
    for offset, view in edits.items():
        end = out.index(0, offset)
        room = end - offset
        enc = encode(view, syll2code)
        if len(enc) > room:
            report.append("  ! %s 0x%x 번역이 %d바이트로 자리(%d)를 넘어 건너뜀"
                          % (label, offset, len(enc), room))
            continue
        out[offset:end] = enc + bytes([PAD]) * (room - len(enc))
    return bytes(out)


def patch_resource(raw, name, texts, syll2code, report):
    """섹션을 다시 압축해 컨테이너를 재배치한다.

    번역문(완성형 코드)은 원문 일본어보다 압축이 잘 안 되어 섹션이 커진다. 대신
    손대지 않은 섹션은 우리 압축기가 원본보다 작게 만들어 주므로, **컨테이너
    전체를 다시 배치해** 그 여유를 번역한 섹션에 넘겨준다. 섹션의 (offset,length)
    테이블은 컨테이너 헤더에 그대로 적혀 있으므로 다시 써 주면 된다. 총합이
    원래 페이로드 크기 안에 들어가기만 하면 파일 크기는 그대로다.
    """
    plain = bytearray(dlcres.decrypt(raw))
    size = struct.unpack_from("<I", plain, 4)[0]
    start = dlcres.payload_off(plain)
    container = bytes(plain[start:size])
    sections = scen.parse_sections(container)
    if not sections:
        return raw

    header_size = struct.unpack_from("<I", container, 0)[0]
    available = len(container) - header_size

    blobs, changed = [], False
    for index, (offset, length) in enumerate(sections):
        if not length:
            blobs.append(b"")
            continue
        blob = container[offset:offset + length]
        prefix = "%s.s%d." % (name, index)
        mine = {k[len(prefix):]: v for k, v in texts.items() if k.startswith(prefix)}
        if not mine or blob[0] not in (0x08, 0x0C):
            blobs.append(blob)
            continue

        section = huffman.decompress(blob)
        label = "%s s%d" % (name, index)
        events = {int(k[1:]): v for k, v in mine.items() if k.startswith("e")}
        offsets = {int(k[1:]): v for k, v in mine.items() if k.startswith("o")}
        if events:
            text_start, _ = scen.find_text_region(section)
            if text_start is None:
                report.append("  ! %s 텍스트 영역을 찾지 못해 건너뜀" % label)
                blobs.append(blob)
                continue
            section = rebuild_events(section, text_start, events, syll2code, report, label)
        if offsets:
            section = rebuild_offsets(section, offsets, syll2code, report, label)

        packed = huffman.compress_real(section, blob[0], effort=3)
        if huffman.decompress(packed) != section:
            report.append("  ! %s 재압축 왕복 불일치 — 원본 유지" % label)
            blobs.append(blob)
            continue
        blobs.append(packed)
        changed = True

    if not changed:
        return raw

    # 손대지 않은 섹션도 다시 압축해 여유를 만든다.
    total = sum((len(b) + 3) & ~3 for b in blobs)
    if total > available:
        for index, blob in enumerate(blobs):
            if not blob or blob[0] not in (0x08, 0x0C):
                continue
            prefix = "%s.s%d." % (name, index)
            if any(k.startswith(prefix) for k in texts):
                continue
            try:
                candidate = huffman.compress_real(huffman.decompress(blob), blob[0], effort=3)
            except Exception:                          # noqa: BLE001
                continue
            if len(candidate) < len(blob):
                blobs[index] = candidate
        total = sum((len(b) + 3) & ~3 for b in blobs)

    if total > available:
        report.append("  ! %s 재배치해도 %d바이트 모자라 건너뜀 (가용 %d, 필요 %d)"
                      % (name, total - available, available, total))
        return raw

    rebuilt = bytearray(container[:header_size])
    cursor = header_size
    for index, blob in enumerate(blobs):
        if not blob:
            struct.pack_into("<II", rebuilt, index * 8, 0, 0)
            continue
        struct.pack_into("<II", rebuilt, index * 8, cursor, len(blob))
        rebuilt += blob
        pad = ((len(blob) + 3) & ~3) - len(blob)
        rebuilt += bytes(pad)
        cursor += len(blob) + pad
    rebuilt += bytes(len(container) - len(rebuilt))

    plain[start:size] = rebuilt
    return dlcres.fix_crc(dlcres.encrypt(bytes(plain)))


def main() -> int:
    ap = argparse.ArgumentParser(description="DLC 시나리오 대사 한글화")
    ap.add_argument("content", help="DLC content 폴더")
    ap.add_argument("--base-dat", required=True)
    ap.add_argument("--texts", default="dlc_dialogue_ko.json")
    ap.add_argument("--output", default="dlc_overlay")
    ap.add_argument("--from-overlay", help="이미 만든 오버레이 위에 덧입힐 때 그 폴더")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    texts_path = Path(args.texts)
    if not texts_path.is_absolute() and not texts_path.is_file():
        texts_path = here / args.texts
    texts = {k: v for k, v in json.loads(texts_path.read_text(encoding="utf-8")).items()
             if not k.startswith("_")}
    syll2code = syllable_map(Path(args.base_dat))

    out_dir = Path(args.output) / TITLE_ID / "romfs_ext"
    out_dir.mkdir(parents=True, exist_ok=True)
    prior = Path(args.from_overlay) / TITLE_ID / "romfs_ext" if args.from_overlay else None

    report, patched = [], 0
    for app_path in sorted(Path(args.content).rglob("*.app")):
        app = app_path.read_bytes()
        for name, offset, size in romfs_files(app):
            if not name.lower().endswith(RESOURCE_EXT):
                continue
            if not any(k.startswith(name + ".s") for k in texts):
                continue
            raw = app[offset:offset + size]
            base = raw
            if prior is not None and (prior / (name + ".ips")).is_file():
                from apply_update_code import apply_ips_patch
                base = apply_ips_patch(raw, (prior / (name + ".ips")).read_bytes())
            new = patch_resource(base, name, texts, syll2code, report)
            if new == base:
                continue
            if not dlcres.accepted(new):
                report.append("  ! %s 결과가 게임 검사를 통과하지 못해 제외" % name)
                continue
            (out_dir / (name + ".ips")).write_bytes(make_ips(raw, new))
            patched += 1

    for line in report:
        print(line)
    print("대사를 넣은 리소스 %d개 -> %s" % (patched, out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
