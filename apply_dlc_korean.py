#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a Korean LayeredFS overlay for Culdcept Revolt DLC.

The supplied DLC is a set of plaintext NCCH containers.  The running game
reads display names from both ``ContentInfoArchive_JPN_ja.bin`` and direct DLC
resource headers (``.dld``, ``.dlq``, ``.dlm`` and related files), so the tool
emits a translated catalog plus narrowly bounded IPS title patches under
``romfs_ext``.

Usage::

    python apply_dlc_korean.py path/to/DLC-000f5700 \
        --base-dat path/to/patched/CULDCEPT.DAT --output dlc-mod

The output is a LayeredFS tree rooted at ``load/mods/0004008c000f5700``.
Only translated fields and small IPS patches are written; no game or DLC
content is distributed by this repository.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from culdcept import dat as datmod
from culdcept import font as fontmod
from culdcept import huffman
from culdcept import wansung

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


TITLE_ID = "0004008c000f5700"
CATALOG_NAME = "ContentInfoArchive_JPN_ja.bin"
CATALOG_COUNT = 108
CATALOG_BASE = 0xC8
CATALOG_STRIDE = 0xC8
TITLE_OFFSET = 0x08
TITLE_SIZE = 0x40
DESCRIPTION_OFFSET = 0x48
DESCRIPTION_SIZE = 0x80

RESOURCE_TITLE_OFFSET = 0x10
# The resource header validator at ARM 0x0027635c passes 0x1c bytes starting
# at 0x10 to the Shift-JIS validator, then reads byte 0x2b separately as the
# encrypted payload offset.  The title therefore has 0x1b bytes (including
# its terminator), not 0x20.  Writing through 0x2f, as v2.4/v2.6 did, zeroed
# the payload offset.  A 0x34-byte avatar then used the 0x80 fallback offset,
# underflowed its decrypt length, and looped over unmapped memory at
# PC 0x00122204 (issue #13).
RESOURCE_TITLE_SIZE = 0x1B
RESOURCE_EXTENSIONS = frozenset({".dla", ".dlb", ".dld", ".dlj", ".dlm", ".dlq"})

# These are the records shown in the issue #8 screenshots.  Requiring them to
# be found in the direct resources prevents a catalog-only or incomplete DLC
# dump from producing a seemingly successful but ineffective v2.4 overlay.
ISSUE8_REQUIRED_RECORDS = frozenset({2, 70, *range(53, 65), *range(99, 105)})

# U+00B7 is useful in the UTF-8 catalog, but is not representable in Shift-JIS
# resource headers.  The visually equivalent Shift-JIS middle dot is used in
# those headers only.
RESOURCE_CHAR_REPLACEMENTS = {"·": "・"}


class DlcError(ValueError):
    """A malformed or unsupported DLC input."""


@dataclass(frozen=True)
class CatalogRecord:
    number: int
    original_title: str
    translated_title: str
    original_suffix: str
    translated_suffix: str
    translated_description: str


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


def app_candidates(input_path: Path) -> list[Path]:
    if input_path.is_file() and input_path.suffix.lower() == ".app":
        candidates = [input_path]
    elif input_path.is_dir():
        candidates = sorted(input_path.rglob("*.app"))
    else:
        raise DlcError(f"DLC folder or .app file not found: {input_path}")

    if not candidates:
        raise DlcError(f"no .app files found below: {input_path}")
    return candidates


def find_catalog(input_path: Path) -> tuple[Path, bytes]:
    candidates = app_candidates(input_path)
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


def find_resources(input_path: Path) -> dict[str, bytes]:
    """Read direct DLC resources keyed by their RomFS path.

    A resource can occur in more than one NCCH app in the supplied dump.  The
    duplicate is accepted only when its bytes are identical.
    """

    resources: dict[str, bytes] = {}
    errors: list[str] = []
    for app_path in app_candidates(input_path):
        try:
            locations = parse_romfs(app_path)
            app_data = app_path.read_bytes()
        except DlcError as exc:
            errors.append(str(exc))
            continue

        for romfs_path, (offset, size) in locations.items():
            if PurePosixPath(romfs_path).suffix.lower() not in RESOURCE_EXTENSIONS:
                continue
            data = app_data[offset:offset + size]
            if len(data) != size:
                raise DlcError(f"{app_path.name}: resource data truncated for {romfs_path}")
            previous = resources.get(romfs_path)
            if previous is not None and previous != data:
                raise DlcError(f"duplicate DLC resource differs between apps: {romfs_path}")
            resources[romfs_path] = data

    if not resources:
        detail = "; ".join(errors[:3])
        raise DlcError(
            "no direct DLC resources (.dla/.dlb/.dld/.dlj/.dlm/.dlq) found"
            + (f": {detail}" if detail else "")
        )
    return resources


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


def catalog_records(
    data: bytes, translations: dict[str, dict[str, str]]
) -> list[CatalogRecord]:
    if len(data) < 8 or u32(data, 0) != 1:
        raise DlcError("unexpected DLC catalog header")
    count = u32(data, 4)
    if count != CATALOG_COUNT:
        raise DlcError(f"unexpected DLC catalog record count: {count} (expected {CATALOG_COUNT})")
    end = CATALOG_BASE + count * CATALOG_STRIDE + 8
    if len(data) < end:
        raise DlcError(f"DLC catalog is truncated: {len(data)} bytes (need {end})")

    records: list[CatalogRecord] = []
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

        records.append(
            CatalogRecord(
                number=number,
                original_title=original_title,
                translated_title=title,
                original_suffix=original_title[len(prefix):],
                translated_suffix=title[len(prefix):],
                translated_description=description,
            )
        )
    return records


def patch_catalog_records(data: bytes, records: list[CatalogRecord]) -> tuple[bytes, list[str]]:
    patched = bytearray(data)
    changed: list[str] = []
    for item in records:
        record = CATALOG_BASE + (item.number - 1) * CATALOG_STRIDE
        title_bytes = item.translated_title.encode("utf-8")
        description_bytes = item.translated_description.encode("utf-8")
        title_start = record + TITLE_OFFSET
        description_start = record + DESCRIPTION_OFFSET
        patched[title_start:title_start + TITLE_SIZE] = title_bytes.ljust(TITLE_SIZE, b"\0")
        patched[description_start:description_start + DESCRIPTION_SIZE] = description_bytes.ljust(
            DESCRIPTION_SIZE, b"\0"
        )
        changed.append(f"{item.number:03d} {item.original_title} -> {item.translated_title}")
    return bytes(patched), changed


def patch_catalog(data: bytes, translations: dict[str, dict[str, str]]) -> tuple[bytes, list[str]]:
    """Patch all fixed-size catalog records, retaining the old public API."""

    return patch_catalog_records(data, catalog_records(data, translations))


def load_syllable_map(base_dat: Path) -> dict[str, int]:
    """Build the fixed Wansung mapping used by the v2.2 patched font."""

    try:
        data = base_dat.read_bytes()
        archive = datmod.Dat(data)
        if archive.count <= 1054:
            raise DlcError(f"base DAT has no font entry 1054: {base_dat}")
        raw_font = huffman.decompress(archive.entry(1054))
        cmap = fontmod.parse_cmap(raw_font)
        return wansung.build_fixed_map(cmap)
    except DlcError:
        raise
    except (OSError, IndexError, struct.error, ValueError) as exc:
        raise DlcError(f"cannot read patched base DAT {base_dat}: {exc}") from exc


def decode_resource_title(data: bytes, resource_path: str) -> str:
    if len(data) < RESOURCE_TITLE_OFFSET + RESOURCE_TITLE_SIZE:
        raise DlcError(f"DLC resource is too small for a title header: {resource_path}")
    raw = data[RESOURCE_TITLE_OFFSET:RESOURCE_TITLE_OFFSET + RESOURCE_TITLE_SIZE].split(b"\0", 1)[0]
    try:
        return raw.decode("shift_jis")
    except UnicodeDecodeError as exc:
        raise DlcError(f"DLC resource title is not Shift-JIS: {resource_path}") from exc


def encode_resource_title(title: str, syllable_map: dict[str, int]) -> bytes:
    normalized = "".join(RESOURCE_CHAR_REPLACEMENTS.get(ch, ch) for ch in title)
    encoded = bytearray()
    for ch in normalized:
        part = wansung.encode_char(ch, syllable_map)
        if not part:
            raise DlcError(f"DLC resource title contains an unsupported character: {title!r} ({ch!r})")
        encoded.extend(part)
    if len(encoded) >= RESOURCE_TITLE_SIZE:
        raise DlcError(
            f"DLC resource title exceeds {RESOURCE_TITLE_SIZE - 1} bytes: {title!r}"
        )
    return bytes(encoded)


def patch_resource_title(
    data: bytes, title: str, syllable_map: dict[str, int]
) -> bytes:
    encoded = encode_resource_title(title, syllable_map)
    patched = bytearray(data)
    start = RESOURCE_TITLE_OFFSET
    patched[start:start + RESOURCE_TITLE_SIZE] = encoded.ljust(RESOURCE_TITLE_SIZE, b"\0")
    return bytes(patched)


def make_ips_patch(source: bytes, target: bytes) -> bytes:
    """Create a minimal IPS patch for equal-length source and target bytes."""

    if len(source) != len(target):
        raise DlcError("IPS source and target must have the same length")

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
            chunk_size = min(i - start, 0xFFFF)
            if start > 0xFFFFFF:
                raise DlcError(f"resource offset is too large for IPS: 0x{start:x}")
            patch.extend(start.to_bytes(3, "big"))
            patch.extend(chunk_size.to_bytes(2, "big"))
            patch.extend(target[start:start + chunk_size])
            start += chunk_size
    patch.extend(b"EOF")
    return bytes(patch)


def patch_resources(
    resources: dict[str, bytes],
    records: list[CatalogRecord],
    syllable_map: dict[str, int],
) -> tuple[dict[str, bytes], list[str], set[int]]:
    by_original_title: dict[str, CatalogRecord] = {}
    for item in records:
        previous = by_original_title.get(item.original_suffix)
        if previous is not None and previous.translated_suffix != item.translated_suffix:
            raise DlcError(
                f"catalog has duplicate direct title with different translations: {item.original_suffix!r}"
            )
        by_original_title[item.original_suffix] = item

    patches: dict[str, bytes] = {}
    changed: list[str] = []
    matched_numbers: set[int] = set()
    for resource_path, source in sorted(resources.items()):
        original_title = decode_resource_title(source, resource_path)
        item = by_original_title.get(original_title)
        if item is None:
            # Keep unknown future resources untouched.  The required issue #8
            # records below still make incomplete dumps fail loudly.
            continue
        matched_numbers.add(item.number)
        target = patch_resource_title(source, item.translated_suffix, syllable_map)
        if target != source:
            patches[resource_path] = make_ips_patch(source, target)
            changed.append(f"{resource_path}: {original_title} -> {item.translated_suffix}")

    missing = sorted(ISSUE8_REQUIRED_RECORDS - matched_numbers)
    if missing:
        numbers = ", ".join(str(number) for number in missing)
        raise DlcError(
            f"DLC direct-resource titles missing for issue #8 records: {numbers}"
        )
    return patches, changed, matched_numbers


def output_path(root: Path) -> Path:
    return root / "load" / "mods" / TITLE_ID / "romfs" / CATALOG_NAME


def output_resource_path(root: Path, resource_path: str) -> Path:
    normalized = resource_path.replace("\\", "/").lstrip("/")
    relative = PurePosixPath(normalized)
    if not normalized or relative == PurePosixPath(".") or any(part in ("", ".", "..") for part in relative.parts):
        raise DlcError(f"unsafe DLC resource path: {resource_path!r}")
    relative_path = Path(*relative.parts)
    return (
        root
        / "load"
        / "mods"
        / TITLE_ID
        / "romfs_ext"
        / relative_path.parent
        / f"{relative_path.name}.ips"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="DLC-000f5700 한글 LayeredFS 오버레이 생성")
    parser.add_argument("input", type=Path, help="DLC ZIP을 푼 폴더 또는 Content/00000000/*.app")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="오버레이 트리를 만들 폴더 (예: 에뮬레이터 사용자 폴더)",
    )
    parser.add_argument(
        "--base-dat",
        type=Path,
        help="한글 폰트가 들어간 본편 CULDCEPT.DAT (직접 리소스 패치에 필요)",
    )
    parser.add_argument(
        "--catalog-only",
        action="store_true",
        help="Azahar 호환 모드: 카탈로그만 생성하고 직접 리소스 IPS는 생략",
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
        records = catalog_records(original, translations)
        patched_catalog, changed_catalog = patch_catalog_records(original, records)

        resource_patches: dict[str, bytes] = {}
        changed_resources: list[str] = []
        matched_numbers: set[int] = set()
        if args.catalog_only:
            if args.base_dat is not None:
                raise DlcError("--catalog-only와 --base-dat는 함께 사용할 수 없습니다")
        else:
            if args.base_dat is None:
                raise DlcError(
                    "직접 리소스 제목 패치에는 --base-dat가 필요합니다 "
                    "(--catalog-only는 레거시 카탈로그 전용 모드입니다)"
                )
            syllable_map = load_syllable_map(args.base_dat)
            resources = find_resources(args.input)
            resource_patches, changed_resources, matched_numbers = patch_resources(
                resources, records, syllable_map
            )

        catalog_destination = output_path(args.output)
        catalog_destination.parent.mkdir(parents=True, exist_ok=True)
        catalog_destination.write_bytes(patched_catalog)
        for resource_path, patch in resource_patches.items():
            destination = output_resource_path(args.output, resource_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(patch)
    except (DlcError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    print(f"입력 NCCH: {app_path}")
    print(f"카탈로그: {len(original):,} 바이트 / {len(changed_catalog)}개 레코드")
    if args.catalog_only:
        print("직접 리소스: 생략 (--catalog-only)")
    else:
        print(
            f"직접 리소스: {len(resource_patches)}개 IPS / "
            f"{len(matched_numbers)}개 카탈로그 레코드 매칭"
        )
        print(f"필수 화면 항목 패치: {len(ISSUE8_REQUIRED_RECORDS)}개 매칭")
    print(f"출력: {catalog_destination.parent.parent.parent.parent.parent}")
    print(f"타이틀 ID: {TITLE_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
