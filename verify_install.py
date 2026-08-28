#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnose a Culdcept Revolt LayeredFS installation without changing it.

This checks the paths that matter for issue #10:

* the v2.2 base-game replacement;
* the DLC catalog and optional direct-resource IPS overlay;
* accidental placement of DLC files under the base-game title ID;
* an installed DLC title under Azahar's virtual SD card;
* the virtual-SD setting and useful LayeredFS log messages.

Usage::

    python verify_install.py "C:/Users/me/AppData/Roaming/Azahar"

The script is intentionally read-only.  It does not rename, delete, or copy
anything in the Azahar user directory.
"""

from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from culdcept import huffman

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


BASE_TITLE_ID = "00040000000F5700"
DLC_TITLE_ID = "0004008c000f5700"
CATALOG_NAME = "ContentInfoArchive_JPN_ja.bin"
EXPECTED_CATALOG_SIZE = 21_808
EXPECTED_CATALOG_COUNT = 108
EXPECTED_DIRECT_IPS = 108
BASE_CARD_PROBES = ((84608, 16), (103135, 12), (183653, 6))
BASE_CONFIRM_TAILS = ((211679, 31), (211711, 29))
LOG_GLOB = "azahar_log*.txt"
CATALOG_REPEAT_WARNING_THRESHOLD = 50


@dataclass(frozen=True)
class Check:
    label: str
    status: str
    detail: str
    blocking: bool = False


def _find_child(parent: Path | None, name: str) -> Path | None:
    """Find a direct child case-insensitively, for portable diagnostics."""

    if parent is None or not parent.is_dir():
        return None
    exact = parent / name
    if exact.exists():
        return exact
    folded = name.casefold()
    matches = [child for child in parent.iterdir() if child.name.casefold() == folded]
    return matches[0] if len(matches) == 1 else None


def _find_path(root: Path, *parts: str) -> Path | None:
    current: Path | None = root
    for part in parts:
        current = _find_child(current, part)
        if current is None:
            return None
    return current


def _config_path(user_dir: Path) -> Path | None:
    return _find_path(user_dir, "config", "qt-config.ini")


def _is_hangul_probe(value: bytes) -> bool:
    """Check the fixed Wansung codes used by the Korean font mapping."""

    if len(value) < 2:
        return False
    count = 0
    index = 0
    while index + 1 < len(value):
        code = (value[index] << 8) | value[index + 1]
        if 0x889F <= code <= 0x9872:
            count += 1
            index += 2
        elif value[index] in (0x00, 0x20):
            index += 1
        else:
            return False
    return count > 0


def _check_base(user_dir: Path) -> Check:
    path = _find_path(user_dir, "load", "mods", BASE_TITLE_ID, "romfs", "CULDCEPT.DAT")
    if path is None or not path.is_file():
        return Check(
            "본편 CULDCEPT.DAT",
            "X",
            f"없음: load/mods/{BASE_TITLE_ID}/romfs/CULDCEPT.DAT",
            True,
        )
    size = path.stat().st_size
    if size == 0:
        return Check("본편 CULDCEPT.DAT", "X", "파일 크기가 0바이트입니다.", True)
    detail = f"{size:,}바이트: {path}"
    if size != 300_005_903:
        detail += " (재빌드한 폰트에 따라 크기는 달라질 수 있음)"
    try:
        data = path.read_bytes()
        table_size = struct.unpack_from("<I", data, 0)[0]
        entry_count = table_size // 8
        if entry_count <= 1190:
            return Check("본편 CULDCEPT.DAT", "X", detail + " / 카드 DB 엔트리 1190 없음", True)
        entry_offset, entry_size = struct.unpack_from("<II", data, 1190 * 8)
        compressed = data[entry_offset:entry_offset + entry_size]
        ui = huffman.decompress(compressed)
        probes_ok = all(_is_hangul_probe(ui[offset:offset + length]) for offset, length in BASE_CARD_PROBES)
        tails_ok = all(ui[offset + length - 1] == 0x2F for offset, length in BASE_CONFIRM_TAILS)
    except (OSError, IndexError, struct.error, ValueError, NotImplementedError) as exc:
        return Check("본편 CULDCEPT.DAT", "X", detail + f" / 카드 DB 검사 실패: {exc}", True)
    if not probes_ok or not tails_ok:
        return Check(
            "본편 CULDCEPT.DAT",
            "X",
            detail + " / 본편 카드·확인 메시지 한글화 probe 불일치",
            True,
        )
    detail += " / 카드·확인 메시지 한글화 probe 통과"
    return Check("본편 CULDCEPT.DAT", "O", detail)


def _check_catalog(user_dir: Path) -> Check:
    path = _find_path(user_dir, "load", "mods", DLC_TITLE_ID, "romfs", CATALOG_NAME)
    if path is None or not path.is_file():
        return Check(
            "DLC 카탈로그",
            "X",
            f"없음: load/mods/{DLC_TITLE_ID}/romfs/{CATALOG_NAME}",
            True,
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        return Check("DLC 카탈로그", "X", f"읽기 실패: {exc}", True)
    if len(data) != EXPECTED_CATALOG_SIZE:
        return Check(
            "DLC 카탈로그",
            "X",
            f"크기 {len(data):,}바이트 (예상 {EXPECTED_CATALOG_SIZE:,})",
            True,
        )
    if len(data) < 8 or struct.unpack_from("<II", data, 0) != (1, EXPECTED_CATALOG_COUNT):
        return Check("DLC 카탈로그", "X", "헤더 또는 108개 레코드 수가 올바르지 않습니다.", True)
    return Check("DLC 카탈로그", "O", f"{len(data):,}바이트 / {EXPECTED_CATALOG_COUNT}개 레코드")


def _check_direct_ips(user_dir: Path) -> Check:
    path = _find_path(user_dir, "load", "mods", DLC_TITLE_ID, "romfs_ext")
    if path is None or not path.is_dir():
        return Check("DLC 직접 리소스 IPS", "O", "0개 — v2.5 호환(카탈로그 전용) 모드")
    try:
        patches = [item for item in path.rglob("*") if item.is_file() and item.suffix.casefold() == ".ips"]
    except OSError as exc:
        return Check("DLC 직접 리소스 IPS", "!", f"검색 실패: {exc}")
    malformed = []
    for patch in patches:
        try:
            data = patch.read_bytes()
        except OSError:
            malformed.append(patch.name)
            continue
        if len(data) < 8 or data[:5] != b"PATCH" or data[-3:] != b"EOF":
            malformed.append(patch.name)
    if malformed:
        return Check(
            "DLC 직접 리소스 IPS",
            "X",
            f"형식 오류 {len(malformed)}개 (PATCH/EOF 헤더 확인 필요)",
            True,
        )
    count = len(patches)
    if count not in (0, EXPECTED_DIRECT_IPS):
        return Check(
            "DLC 직접 리소스 IPS",
            "X",
            f"{count}개 (예상 0개 호환 모드 또는 {EXPECTED_DIRECT_IPS}개 전체 모드)",
            True,
        )
    mode = "호환 모드" if count == 0 else "전체 모드"
    return Check("DLC 직접 리소스 IPS", "O", f"{count}개 — {mode}")


def _check_wrong_base_placement(user_dir: Path) -> Check:
    wrong_catalog = _find_path(user_dir, "load", "mods", BASE_TITLE_ID, "romfs", CATALOG_NAME)
    wrong_ext = _find_path(user_dir, "load", "mods", BASE_TITLE_ID, "romfs_ext")
    wrong_ips = []
    if wrong_ext is not None and wrong_ext.is_dir():
        wrong_ips = [item for item in wrong_ext.rglob("*") if item.is_file()]
    if wrong_catalog is not None or wrong_ips:
        detail = []
        if wrong_catalog is not None:
            detail.append(CATALOG_NAME)
        if wrong_ips:
            detail.append(f"본편 romfs_ext 파일 {len(wrong_ips)}개")
        return Check("DLC의 본편 폴더 오배치", "X", ", ".join(detail), True)
    return Check("DLC의 본편 폴더 오배치", "O", "발견되지 않음")


def _sdmc_root(user_dir: Path) -> Path:
    """Return the SD root Azahar is configured to use, if available."""

    config = _config_path(user_dir)
    configured = _read_setting(config, "sdmc_directory") if config else None
    if not configured:
        return user_dir / "sdmc"
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = user_dir / path
    return path


def _find_installed_dlc(user_dir: Path) -> list[Path]:
    """Return installed DLC content directories under any 3DS ID pair."""

    nintendo_3ds = _find_path(_sdmc_root(user_dir), "Nintendo 3DS")
    if nintendo_3ds is None or not nintendo_3ds.is_dir():
        return []
    found: list[Path] = []
    for id0 in nintendo_3ds.iterdir():
        if not id0.is_dir():
            continue
        for id1 in id0.iterdir():
            if not id1.is_dir():
                continue
            content = _find_path(id1, "title", "0004008c", "000f5700", "content")
            if content is None or not content.is_dir():
                continue
            # Azahar stores the NCCH content one level below `content` in
            # the usual layout: `content/00000000/*.app`.  Some older dumps
            # place the apps directly in `content`, so recurse instead of
            # assuming either layout.
            try:
                has_app = any(
                    item.is_file() and item.suffix.casefold() == ".app"
                    for item in content.rglob("*")
                )
            except OSError:
                has_app = False
            if has_app:
                found.append(content)
    return found


def _check_installed_dlc(user_dir: Path) -> Check:
    found = _find_installed_dlc(user_dir)
    if not found:
        return Check(
            "실제 DLC 설치",
            "!",
            f"{_sdmc_root(user_dir)}\\Nintendo 3DS\\*\\*\\title\\0004008c\\000f5700\\content\\**\\*.app를 찾지 못했습니다. "
            "모드 ZIP은 DLC 본체를 설치하지 않으므로 Azahar에서 본인 소유 DLC를 먼저 설치하세요.",
        )
    files = sum(
        1
        for directory in found
        for item in directory.rglob("*")
        if item.is_file() and item.suffix.casefold() == ".app"
    )
    return Check("실제 DLC 설치", "O", f"{len(found)}개 경로 / {files}개 .app (content 하위 검색)")


def _read_setting(config: Path, key: str) -> str | None:
    try:
        for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            name, value = line.split("=", 1)
            if name.strip().casefold() == key.casefold():
                return value.strip()
    except OSError:
        return None
    return None


def _check_virtual_sd(user_dir: Path) -> Check:
    config = _config_path(user_dir)
    if config is None or not config.is_file():
        return Check("가상 SD 설정", "!", "config/qt-config.ini를 찾지 못했습니다.")
    value = _read_setting(config, "use_virtual_sd")
    if value is None:
        return Check("가상 SD 설정", "!", "use_virtual_sd 설정을 찾지 못했습니다.")
    if value.casefold() not in ("true", "1", "yes"):
        return Check("가상 SD 설정", "X", f"use_virtual_sd={value} — true로 켜야 합니다.", True)
    return Check("가상 SD 설정", "O", "use_virtual_sd=true")


def _check_log(user_dir: Path) -> Check:
    log_dir = _find_path(user_dir, "log")
    if log_dir is None or not log_dir.is_dir():
        return Check("Azahar 로그", "!", "log/azahar_log*.txt를 찾지 못했습니다.")
    try:
        logs = sorted(
            (item for item in log_dir.glob(LOG_GLOB) if item.is_file()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except OSError as exc:
        return Check("Azahar 로그", "!", f"로그 목록 읽기 실패: {exc}")
    if not logs:
        return Check("Azahar 로그", "!", "log/azahar_log*.txt를 찾지 못했습니다.")
    chunks = []
    for log in logs[:5]:
        try:
            chunks.append((log.name, log.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    if not chunks:
        return Check("Azahar 로그", "!", "로그 읽기에 실패했습니다.")
    text = "\n".join(content for _, content in chunks)
    folded = text.casefold()
    if "failed to patch" in folded or "original file for patch" in folded:
        names = ", ".join(name for name, _ in chunks)
        return Check("Azahar 로그", "X", f"{names}: IPS 원본 파일 누락 또는 패치 실패 메시지가 있습니다.", True)
    markers = []
    if "layeredfs replacement file in use for /culdcept.dat" in folded:
        markers.append("본편 DAT 적용 확인")
    if "layeredfs patched file" in folded:
        markers.append("IPS 적용 로그 확인")
    catalog_hits = folded.count(
        "layeredfs replacement file in use for /contentinfoarchive_jpn_ja.bin"
    )
    process_cleanups = folded.count("cleaning up process")
    suspicious_loop = (
        catalog_hits >= CATALOG_REPEAT_WARNING_THRESHOLD and process_cleanups > 0
    )
    if suspicious_loop:
        markers.append(
            f"카탈로그 반복 접근 {catalog_hits}회 후 프로세스 정리 — 프리징 의심"
        )
    if not markers:
        names = ", ".join(name for name, _ in chunks)
        return Check("Azahar 로그", "!", f"{names}: LayeredFS 적용 로그가 없습니다. 게임을 한 번 실행한 뒤 다시 검사하세요.")
    names = ", ".join(name for name, _ in chunks)
    status = "!" if suspicious_loop else "O"
    detail = f"{names}: " + ", ".join(markers)
    if suspicious_loop:
        detail += "; v2.7 호환(카탈로그 전용) 모드로 직접 IPS를 분리하세요."
    return Check("Azahar 로그", status, detail)


def inspect_install(user_dir: Path) -> list[Check]:
    return [
        _check_base(user_dir),
        _check_catalog(user_dir),
        _check_direct_ips(user_dir),
        _check_wrong_base_placement(user_dir),
        _check_installed_dlc(user_dir),
        _check_virtual_sd(user_dir),
        _check_log(user_dir),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Culdcept Revolt Azahar 설치 진단(읽기 전용)")
    parser.add_argument("azahar_user_dir", type=Path, help="Azahar 사용자 폴더")
    args = parser.parse_args()

    user_dir = args.azahar_user_dir.expanduser()
    if not user_dir.is_dir():
        print(f"오류: Azahar 사용자 폴더가 없습니다: {user_dir}", file=sys.stderr)
        return 2

    print(f"진단 대상: {user_dir.resolve()}")
    print("상태: O=정상, X=수정 필요, !=추가 확인")
    checks = inspect_install(user_dir)
    for check in checks:
        print(f"[{check.status}] {check.label}: {check.detail}")
    if any(check.blocking for check in checks):
        print("결과: 수정이 필요한 항목이 있습니다.")
        return 1
    print("결과: 핵심 경로와 패치 구조는 정상입니다. ! 항목은 환경 확인이 필요합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
