#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify a v2.4 DLC overlay against the user's own plaintext DLC dump.

Usage::

    python verify_dlc_patch.py DLC-000f5700 \
        --base-dat patched/CULDCEPT.DAT --overlay dlc-mod

The verifier applies every emitted IPS patch in memory and compares it with
the title that ``apply_dlc_korean.py`` would produce.  It never modifies the
source DLC or the overlay.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from apply_dlc_korean import (
    DlcError,
    catalog_records,
    find_catalog,
    find_resources,
    load_syllable_map,
    load_translations,
    output_path,
    output_resource_path,
    patch_catalog_records,
    patch_resource_title,
    patch_resources,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def apply_ips(source: bytes, patch: bytes) -> bytes:
    """Apply the IPS subset emitted by this repository."""

    if not patch.startswith(b"PATCH"):
        raise DlcError("IPS header missing")
    result = bytearray(source)
    position = 5
    while True:
        if position + 3 > len(patch):
            raise DlcError("truncated IPS record")
        if patch[position:position + 3] == b"EOF":
            return bytes(result)
        offset = int.from_bytes(patch[position:position + 3], "big")
        position += 3
        if position + 2 > len(patch):
            raise DlcError("truncated IPS record length")
        size = int.from_bytes(patch[position:position + 2], "big")
        position += 2
        if size:
            if position + size > len(patch) or offset + size > len(result):
                raise DlcError("IPS data is outside the source resource")
            result[offset:offset + size] = patch[position:position + size]
            position += size
            continue
        if position + 3 > len(patch):
            raise DlcError("truncated IPS RLE record")
        repeat = int.from_bytes(patch[position:position + 2], "big")
        value = patch[position + 2]
        position += 3
        if offset + repeat > len(result):
            raise DlcError("IPS RLE data is outside the source resource")
        result[offset:offset + repeat] = bytes([value]) * repeat


def main() -> int:
    parser = argparse.ArgumentParser(description="DLC v2.4 LayeredFS 오버레이 검증")
    parser.add_argument("input", type=Path, help="원본 plaintext DLC 폴더 또는 .app")
    parser.add_argument("--base-dat", type=Path, required=True, help="v2.2 한글 폰트가 들어간 CULDCEPT.DAT")
    parser.add_argument("--overlay", type=Path, required=True, help="apply_dlc_korean.py의 출력 폴더")
    parser.add_argument(
        "--translations",
        type=Path,
        default=Path(__file__).with_name("dlc_ko.json"),
        help="번역 맵 JSON (기본: 저장소의 dlc_ko.json)",
    )
    args = parser.parse_args()

    try:
        _, original_catalog = find_catalog(args.input)
        translations = load_translations(args.translations)
        records = catalog_records(original_catalog, translations)
        expected_catalog, _ = patch_catalog_records(original_catalog, records)

        catalog_file = output_path(args.overlay)
        if not catalog_file.is_file():
            raise DlcError(f"카탈로그 오버레이가 없습니다: {catalog_file}")
        actual_catalog = catalog_file.read_bytes()
        if actual_catalog != expected_catalog:
            raise DlcError(f"카탈로그 오버레이가 번역 결과와 다릅니다: {catalog_file}")

        syllable_map = load_syllable_map(args.base_dat)
        resources = find_resources(args.input)
        expected_patches, _, _ = patch_resources(resources, records, syllable_map)
        by_original_title = {item.original_suffix: item for item in records}

        for resource_path, expected_ips in expected_patches.items():
            patch_file = output_resource_path(args.overlay, resource_path)
            if not patch_file.is_file():
                raise DlcError(f"직접 리소스 IPS가 없습니다: {patch_file}")
            actual_ips = patch_file.read_bytes()
            if actual_ips != expected_ips:
                raise DlcError(f"직접 리소스 IPS가 재현되지 않습니다: {patch_file}")

            source = resources[resource_path]
            title_bytes = source[0x10:0x30].split(b"\0", 1)[0]
            original_title = title_bytes.decode("shift_jis")
            item = by_original_title[original_title]
            actual_target = apply_ips(source, actual_ips)
            expected_target = patch_resource_title(source, item.translated_suffix, syllable_map)
            if actual_target != expected_target:
                raise DlcError(f"IPS 적용 결과가 다릅니다: {resource_path}")

        print(f"카탈로그 검증: O ({len(records)}개 레코드)")
        print(f"직접 리소스 검증: O ({len(expected_patches)}개 IPS)")
        print("결과: v2.4 DLC 오버레이가 원본에서 재현됩니다.")
        return 0
    except (DlcError, OSError, UnicodeDecodeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
