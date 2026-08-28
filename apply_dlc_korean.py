#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply the Korean DLC catalog overlay for Culdcept Revolt.

The supplied DLC is a set of plaintext NCCH containers.  The visible DLC
catalog is stored in ``ContentInfoArchive_JPN_ja.bin`` inside the first
container.  Each catalog entry has a fixed-size UTF-8 title and description
field, so the patch can be applied without rebuilding the NCCH or TMD.

Usage::

    python apply_dlc_korean.py path/to/DLC-000f5700 --output dlc-mod

The output is a LayeredFS tree rooted at ``load/mods/0004008c000f5700``.
Only the translated catalog file is written; no game or DLC content is
distributed by this repository.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path


TITLE_ID = "0004008c000f5700"
CATALOG_NAME = "ContentInfoArchive_JPN_ja.bin"
CATALOG_COUNT = 108
CATALOG_BASE = 0xC8
CATALOG_STRIDE = 0xC8
TITLE_OFFSET = 0x08
TITLE_SIZE = 0x40
DESCRIPTION_OFFSET = 0x48
DESCRIPTION_SIZE = 0x80


class DlcError(ValueError):
    """A malformed or unsupported DLC input."""


def u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise DlcError(f"u32 out of range at 0x{offset:x}")
    return struct.unpack_from("<I", data, offset)[0]


def u64(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 8 > len(data):
        raise DlcError(f"u64 out of range at 0x{offset:x}")
    return struct.unpack_from("<Q", data, offset)[0]


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def utf16_name(data: bytes, offset: int, byte_length: int) -> str:
    if byte_length % 2:
        raise DlcError(f"odd UTF-16 name length at 0x{offset:x}")
    end = offset + byte_length
    if end > len(data):
        raise DlcError(f"UTF-16 name out of range at 0x{offset:x}")
    return data[offset:end].decode("utf-16le")


def parse_romfs(app_path: Path) -> dict[str, tuple[int, int]]:
    """Return ``/path`` -> ``(absolute data offset, size)`` for an NCCH app."""

    data = app_path.read_bytes()
    if len(data) < 0x200 or data[0x100:0x104] != b"NCCH":
        raise DlcError(f"{app_path.name}: NCCH header not found")

    # The issue attachment uses the NCCH no-crypto flag.  Encrypted DLC apps
    # cannot be decoded from the attachment alone and must not be mistaken for
    # a bad RomFS parse.
    if not (data[0x18F] & 0x04):
        raise DlcError(f"{app_path.name}: encrypted NCCH (missing no-crypto flag)")

    romfs_offset = u32(data, 0x1B0) * 0x200
    romfs_size = u32(data, 0x1B4) * 0x200
    if romfs_offset + romfs_size > len(data) or romfs_size < 0x60:
        raise DlcError(f"{app_path.name}: invalid RomFS extent")

    ivfc = romfs_offset
    if data[ivfc:ivfc + 4] != b"IVFC":
        raise DlcError(f"{app_path.name}: IVFC header not found")
    master_hash_size = u32(data, ivfc + 0x08)
    block_log2 = u32(data, ivfc + 0x4C)
    if block_log2 < 9 or block_log2 > 20:
        raise DlcError(f"{app_path.name}: invalid RomFS block size")

    lv3_relative = align_up(0x60 + master_hash_size, 1 << block_log2)
    lv3 = ivfc + lv3_relative
    if lv3 + 0x2C > romfs_offset + romfs_size:
        raise DlcError(f"{app_path.name}: level-3 RomFS header out of range")
    if u32(data, lv3) != 0x28:
        raise DlcError(f"{app_path.name}: unexpected level-3 header size")

    # RomFS level 3 header.  The first fields are u32 offset/size pairs; the
    # file-data offset is a u64.  All offsets below are relative to lv3.
    dir_meta_offset = u32(data, lv3 + 0x0C)
    dir_meta_size = u32(data, lv3 + 0x10)
    file_meta_offset = u32(data, lv3 + 0x1C)
    file_meta_size = u32(data, lv3 + 0x20)
    file_data_offset = u64(data, lv3 + 0x24)

    dir_meta = data[lv3 + dir_meta_offset:lv3 + dir_meta_offset + dir_meta_size]
    file_meta = data[lv3 + file_meta_offset:lv3 + file_meta_offset + file_meta_size]
    if len(dir_meta) != dir_meta_size or len(file_meta) != file_meta_size:
        raise DlcError(f"{app_path.name}: RomFS metadata out of range")

    files: dict[str, tuple[int, int]] = {}
    seen_dirs: set[int] = set()
    seen_files: set[int] = set()

    def walk_dir(directory_offset: int, parent_path: str) -> None:
        if directory_offset in seen_dirs:
            raise DlcError(f"{app_path.name}: cyclic directory metadata")
        if directory_offset + 0x18 > len(dir_meta):
            raise DlcError(f"{app_path.name}: directory metadata out of range")
        seen_dirs.add(directory_offset)

        child = u32(dir_meta, directory_offset + 0x08)
        while child != 0xFFFFFFFF:
            if child + 0x18 > len(dir_meta):
                raise DlcError(f"{app_path.name}: child directory out of range")
            name_length = u32(dir_meta, child + 0x14)
            name = utf16_name(dir_meta, child + 0x18, name_length)
            child_path = f"{parent_path}/{name}"
            walk_dir(child, child_path)
            child = u32(dir_meta, child + 0x04)

        file_entry = u32(dir_meta, directory_offset + 0x0C)
        while file_entry != 0xFFFFFFFF:
            if file_entry in seen_files or file_entry + 0x20 > len(file_meta):
                raise DlcError(f"{app_path.name}: invalid or cyclic file metadata")
            seen_files.add(file_entry)
            name_length = u32(file_meta, file_entry + 0x1C)
            name = utf16_name(file_meta, file_entry + 0x20, name_length)
            relative_offset = u64(file_meta, file_entry + 0x08)
            size = u64(file_meta, file_entry + 0x10)
            absolute_offset = lv3 + file_data_offset + relative_offset
            if absolute_offset + size > romfs_offset + romfs_size:
                raise DlcError(f"{app_path.name}: file data out of range for {name}")
            files[f"{parent_path}/{name}"] = (absolute_offset, size)
            file_entry = u32(file_meta, file_entry + 0x04)

    walk_dir(0, "")
    return files


def find_catalog(input_path: Path) -> tuple[Path, bytes]:
    if input_path.is_file() and input_path.suffix.lower() == ".app":
        candidates = [input_path]
    elif input_path.is_dir():
        candidates = sorted(input_path.rglob("*.app"))
    else:
        raise DlcError(f"DLC folder or .app file not found: {input_path}")

    if not candidates:
        raise DlcError(f"no .app files found below: {input_path}")

    errors: list[str] = []
    for app_path in candidates:
        try:
            files = parse_romfs(app_path)
        except DlcError as exc:
            errors.append(str(exc))
            continue
        location = f"/{CATALOG_NAME}"
        if location in files:
            offset, size = files[location]
            data = app_path.read_bytes()[offset:offset + size]
            if len(data) != size:
                raise DlcError(f"{app_path.name}: catalog data truncated")
            return app_path, data

    detail = "; ".join(errors[:3])
    raise DlcError(
        f"{CATALOG_NAME} not found in plaintext RomFS (.app files checked: "
        f"{len(candidates)}{'; ' + detail if detail else ''})"
    )


def decode_field(data: bytes, offset: int, size: int) -> str:
    raw = data[offset:offset + size].split(b"\0", 1)[0]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DlcError(f"catalog field at 0x{offset:x} is not UTF-8") from exc


def load_translations(path: Path) -> dict[str, dict[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DlcError(f"cannot read translation map {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DlcError("translation map must be a JSON object keyed by record number")
    return payload


def patch_catalog(data: bytes, translations: dict[str, dict[str, str]]) -> tuple[bytes, list[str]]:
    if len(data) < 8 or u32(data, 0) != 1:
        raise DlcError("unexpected DLC catalog header")
    count = u32(data, 4)
    if count != CATALOG_COUNT:
        raise DlcError(f"unexpected DLC catalog record count: {count} (expected {CATALOG_COUNT})")
    end = CATALOG_BASE + count * CATALOG_STRIDE + 8
    if len(data) < end:
        raise DlcError(f"DLC catalog is truncated: {len(data)} bytes (need {end})")

    patched = bytearray(data)
    changed: list[str] = []
    for number in range(1, count + 1):
        key = str(number)
        item = translations.get(key)
        if not isinstance(item, dict):
            raise DlcError(f"translation missing for DLC catalog record {number}")
        title = item.get("title")
        description = item.get("description")
        if not isinstance(title, str) or not isinstance(description, str):
            raise DlcError(f"record {number} needs string title and description")

        record = CATALOG_BASE + (number - 1) * CATALOG_STRIDE
        original_title = decode_field(data, record + TITLE_OFFSET, TITLE_SIZE)
        prefix = original_title[:2]
        if prefix and not title.startswith(prefix):
            raise DlcError(
                f"record {number} category prefix changed: {original_title!r} -> {title!r}"
            )

        title_bytes = title.encode("utf-8")
        description_bytes = description.encode("utf-8")
        if len(title_bytes) >= TITLE_SIZE:
            raise DlcError(f"record {number} title exceeds {TITLE_SIZE - 1} bytes")
        if len(description_bytes) >= DESCRIPTION_SIZE:
            raise DlcError(f"record {number} description exceeds {DESCRIPTION_SIZE - 1} bytes")

        title_start = record + TITLE_OFFSET
        description_start = record + DESCRIPTION_OFFSET
        patched[title_start:title_start + TITLE_SIZE] = title_bytes.ljust(TITLE_SIZE, b"\0")
        patched[description_start:description_start + DESCRIPTION_SIZE] = description_bytes.ljust(
            DESCRIPTION_SIZE, b"\0"
        )
        changed.append(f"{number:03d} {original_title} -> {title}")

    return bytes(patched), changed


def output_path(root: Path) -> Path:
    return root / "load" / "mods" / TITLE_ID / "romfs" / CATALOG_NAME


def main() -> int:
    parser = argparse.ArgumentParser(description="DLC-000f5700 카탈로그 한글 LayeredFS 오버레이 생성")
    parser.add_argument("input", type=Path, help="DLC ZIP을 푼 폴더 또는 Content/00000000/*.app")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="오버레이 트리를 만들 폴더 (예: 에뮬레이터 사용자 폴더)",
    )
    parser.add_argument(
        "--translations",
        type=Path,
        default=Path(__file__).with_name("dlc_ko.json"),
        help="번역 맵 JSON (기본: 저장소의 dlc_ko.json)",
    )
    args = parser.parse_args()

    try:
        app_path, original = find_catalog(args.input)
        translations = load_translations(args.translations)
        patched, changed = patch_catalog(original, translations)
        destination = output_path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(patched)
    except (DlcError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    print(f"입력 NCCH: {app_path}")
    print(f"카탈로그: {len(original):,} 바이트 / {len(changed)}개 레코드")
    print(f"출력: {destination}")
    print(f"타이틀 ID: {TITLE_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
