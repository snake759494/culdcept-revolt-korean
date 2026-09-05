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
import hashlib
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from culdcept import huffman

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


BASE_TITLE_ID = "00040000000F5700"
UPDATE_TITLE_ID = "0004000e000f5700"
# 게임 업데이트(ver 1.2) 실행코드를 BLZ 해제한 것. 원본과 한글화본의 해시.
UPDATE_CODE_SHA256 = "4b21f19242488e28b68dffdf29b65f8af32be2a58431a5031edaa8e8c74af6e1"
UPDATE_CODE_KO_SHA256 = "ca235c5a162648e08a47caa60b151c39ce8fc02452d7d788f3abd45bc98e52ed"
# 그 코드 안에서 카드 DB 가 놓인 구간(=엔트리 1190 의 s0 와 같은 길이).
UPDATE_CARD_DB = (0x308578, 153786)
DLC_TITLE_ID = "0004008c000f5700"
CATALOG_NAME = "ContentInfoArchive_JPN_ja.bin"
EXPECTED_CATALOG_SIZE = 21_808
EXPECTED_CATALOG_COUNT = 108
EXPECTED_DIRECT_IPS = 108
BASE_CARD_PROBES = ((84608, 16), (103135, 12), (183653, 6))
BASE_CONFIRM_TAILS = ((211679, 31), (211711, 29))
LOG_GLOB = "azahar_log*.txt"
FATAL_DIRECT_PATCH_PC = "0x00122204"
RESOURCE_PAYLOAD_OFFSET_FIELD = 0x2B


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



# 카탈로그는 UTF-8 인데 게임이 Shift-JIS 로 바꿔 그린다. 한글을 그대로 적으면 변환이
# 실패해 DLC 목록이 통째로 비어 버렸다(이슈 #19/#20). 한글 글리프가 들어앉은 한자로
# 적어야 하고, 이 검사가 그 회귀를 막는다.
CATALOG_RECORD_BASE = 0xC8
CATALOG_RECORD_STRIDE = 0xC8
CATALOG_FIELDS = ((0x08, 0x40), (0x48, 0x80))


def _catalog_sjis_failures(data: bytes, count: int) -> int:
    failures = 0
    for index in range(count):
        record = CATALOG_RECORD_BASE + index * CATALOG_RECORD_STRIDE
        for offset, size in CATALOG_FIELDS:
            field = data[record + offset:record + offset + size]
            if not field:
                continue
            text = field.split(bytes(1))[0].decode("utf-8", "replace")
            try:
                text.encode("cp932")
            except UnicodeEncodeError:
                failures += 1
    return failures


def _check_catalog(user_dir: Path) -> Check:
    """DLC 이름 번역 오버레이가 **게임 검사를 통과하는지**까지 확인한다.

    DLC 리소스 파일은 헤더 0x00 에 CRC-32 무결성 값이 있다. 이걸 갱신하지 않고 제목만
    바꾸면 게임이 리소스를 전부 거부해 DLC 가 통째로 사라진 것처럼 보인다(이슈 #19~#22).
    그래서 파일이 있는지만 보지 않고, 실제로 IPS 를 적용해 CRC 와 Shift-JIS 제목 검사를
    통과하는지 직접 확인한다.
    """
    folder = _find_path(user_dir, "load", "mods", DLC_TITLE_ID, "romfs_ext")
    if folder is None or not folder.is_dir():
        return Check("DLC 이름 번역", "!", "설치되지 않음 — DLC 항목 이름이 원문으로 나옵니다")
    patches = sorted(folder.glob("*.ips"))
    if not patches:
        return Check("DLC 이름 번역", "!", "IPS 가 없습니다")

    content = _find_installed_dlc_content(user_dir)
    if content is None:
        return Check("DLC 이름 번역", "!", f"{len(patches)}개 설치됨 (DLC 본체가 없어 검사 생략)")

    try:
        from apply_dlc_text import RESOURCE_EXT, romfs_files
        from apply_update_code import apply_ips_patch
        from culdcept import dlcres
    except Exception as exc:                       # noqa: BLE001
        return Check("DLC 이름 번역", "!", f"{len(patches)}개 설치됨 (검사 도구 없음: {exc})")

    originals = {}
    for app_path in sorted(content.rglob("*.app")):
        app = app_path.read_bytes()
        for name, offset, size in romfs_files(app):
            if name.lower().endswith(RESOURCE_EXT):
                originals.setdefault(name, app[offset:offset + size])

    ok = bad = 0
    for patch in patches:
        raw = originals.get(patch.name[:-4])
        if raw is None:
            continue
        try:
            result = apply_ips_patch(raw, patch.read_bytes())
            if len(result) == len(raw) and dlcres.accepted(result):
                ok += 1
            else:
                bad += 1
        except Exception:                          # noqa: BLE001
            bad += 1
    if bad:
        return Check(
            "DLC 이름 번역",
            "X",
            f"{ok}개 정상 / {bad}개가 게임 검사(CRC·제목)를 통과하지 못합니다 — "
            "이 상태로 두면 ★DLC 가 통째로 사라집니다★. 설치.cmd 를 다시 실행하세요.",
            True,
        )
    return Check("DLC 이름 번역", "O", f"{ok}개 — 게임 검사(CRC·Shift-JIS 제목) 통과")


def _find_installed_dlc_content(user_dir: Path):
    sdmc = _find_path(user_dir, "sdmc", "Nintendo 3DS")
    if sdmc is None or not sdmc.is_dir():
        return None
    for id0 in sdmc.iterdir():
        if not id0.is_dir():
            continue
        for id1 in id0.iterdir():
            content = _find_path(id1, "title", "0004008c", "000f5700", "content")
            if content is not None and content.is_dir() and any(content.rglob("*.app")):
                return content
    return None


def _check_catalog_unused(user_dir: Path) -> Check:
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
    failures = _catalog_sjis_failures(data, EXPECTED_CATALOG_COUNT)
    if failures:
        return Check(
            "DLC 카탈로그",
            "X",
            f"{len(data):,}바이트 / {EXPECTED_CATALOG_COUNT}개 레코드 — "
            f"Shift-JIS 로 바꿀 수 없는 필드 {failures}개. 게임이 카탈로그를 읽지 못해 "
            "★DLC 가 통째로 사라집니다★. 최신 패키지로 다시 설치하세요.",
            True,
        )
    return Check("DLC 카탈로그", "O",
                 f"{len(data):,}바이트 / {EXPECTED_CATALOG_COUNT}개 레코드 / Shift-JIS 변환 가능")


def _check_direct_ips(user_dir: Path) -> Check:
    path = _find_path(user_dir, "load", "mods", DLC_TITLE_ID, "romfs_ext")
    if path is None or not path.is_dir():
        return Check("DLC 직접 리소스 IPS", "O", "0개 — v2.5 호환(카탈로그 전용) 모드")
    try:
        patches = [item for item in path.rglob("*") if item.is_file() and item.suffix.casefold() == ".ips"]
    except OSError as exc:
        return Check("DLC 직접 리소스 IPS", "!", f"검색 실패: {exc}")
    malformed = []
    corrupt_header = []
    for patch in patches:
        try:
            data = patch.read_bytes()
        except OSError:
            malformed.append(patch.name)
            continue
        if len(data) < 8 or data[:5] != b"PATCH" or data[-3:] != b"EOF":
            malformed.append(patch.name)
            continue
        try:
            cursor = 5
            while data[cursor:cursor + 3] != b"EOF":
                if cursor + 5 > len(data):
                    raise ValueError
                offset = int.from_bytes(data[cursor:cursor + 3], "big")
                size = int.from_bytes(data[cursor + 3:cursor + 5], "big")
                cursor += 5
                if size == 0:
                    if cursor + 3 > len(data):
                        raise ValueError
                    size = int.from_bytes(data[cursor:cursor + 2], "big")
                    cursor += 3
                else:
                    if cursor + size > len(data):
                        raise ValueError
                    cursor += size
                if offset <= RESOURCE_PAYLOAD_OFFSET_FIELD < offset + size:
                    corrupt_header.append(patch.name)
                    break
        except (IndexError, ValueError):
            malformed.append(patch.name)
    if malformed:
        return Check(
            "DLC 직접 리소스 IPS",
            "X",
            f"형식 오류 {len(malformed)}개 (PATCH/EOF 헤더 확인 필요)",
            True,
        )
    if corrupt_header:
        return Check(
            "DLC 직접 리소스 IPS",
            "X",
            f"구형 손상 패치 {len(corrupt_header)}개가 리소스 헤더 0x2B를 덮습니다. "
            "v2.8의 108개 IPS로 전부 덮어쓰세요.",
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


def _find_dlc_tickets(user_dir: Path) -> list[Path]:
    """nand/dbs/ticket.db 안의 DLC 티켓 파일 목록(대소문자 무시)."""
    ticket_dir = _find_path(user_dir, "nand", "dbs", "ticket.db")
    if ticket_dir is None or not ticket_dir.is_dir():
        return []
    prefix = DLC_TITLE_ID.casefold()
    try:
        return [
            item
            for item in ticket_dir.iterdir()
            if item.is_file()
            and item.name.casefold().startswith(prefix)
            and item.suffix.casefold() == ".tik"
        ]
    except OSError:
        return []


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
    detail = f"{len(found)}개 경로 / {files}개 .app (content 하위 검색)"

    # .app 만 복사해 넣으면 Azahar 가 DLC 를 인식하지 못한다. 타이틀 메타데이터
    # (.tmd) 와 티켓이 모두 있어야 게임에서 추가 콘텐츠가 보인다.
    tmds = sum(
        1
        for directory in found
        for item in directory.rglob("*")
        if item.is_file() and item.suffix.casefold() == ".tmd"
    )
    if not tmds:
        return Check(
            "실제 DLC 설치",
            "X",
            detail + " / .tmd 없음 — content 폴더에 .app 만 복사하면 DLC 가 인식되지 않습니다. "
            "Azahar 의 파일 > 설치(CIA)로 본인 소유 DLC CIA 를 다시 설치하세요.",
            True,
        )
    detail += f" / .tmd {tmds}개"

    if not _find_dlc_tickets(user_dir):
        return Check(
            "실제 DLC 설치",
            "X",
            detail + " / DLC 티켓 없음 — nand/dbs/ticket.db/0004008C000F5700.*.tik 가 없습니다. "
            "티켓이 없으면 게임 안에서 추가 콘텐츠가 통째로 사라진 것처럼 보입니다. "
            "Azahar 의 파일 > 설치(CIA)로 본인 소유 DLC CIA 를 다시 설치하세요.",
            True,
        )
    return Check("실제 DLC 설치", "O", detail + " / 티켓 있음")


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
    if (
        FATAL_DIRECT_PATCH_PC in folded
        and "hw.memory" in folded
        and "unmapped" in folded
    ):
        names = ", ".join(name for name, _ in chunks)
        return Check(
            "Azahar 로그",
            "X",
            f"{names}: {FATAL_DIRECT_PATCH_PC} 미매핑 메모리 루프 — 구형 직접 IPS가 "
            "리소스 헤더 0x2B를 덮어 복호화 길이가 언더플로된 #13 패턴입니다. "
            "v2.8의 108개 IPS로 전부 덮어쓰세요.",
            True,
        )
    if "failed to patch" in folded:
        names = ", ".join(name for name, _ in chunks)
        return Check("Azahar 로그", "X", f"{names}: IPS 패치 실패 메시지가 있습니다.", True)
    markers = []
    if "layeredfs replacement file in use for /culdcept.dat" in folded:
        markers.append("본편 DAT 적용 확인")
    if "layeredfs patched file" in folded:
        markers.append("IPS 적용 로그 확인")
    # DLC IPS 는 108개 콘텐츠마다 전부 시도되므로 "건너뜀"이 수만 건 나오는 것이 정상이다.
    # 예전에는 이걸 이상 징후로 봤지만, 실제 원인은 따로 있었다(헤더 CRC 미갱신).
    skipped_patches = folded.count("original file for patch")
    if skipped_patches:
        markers.append(f"DLC IPS 대조 {skipped_patches}건(정상)")
    # 예전에는 카탈로그 반복 접근을 프리징 징후로 봤으나, 실제 원인은 리소스 헤더의
    # CRC 미갱신이었다(이슈 #22에서 규명). 카탈로그를 항목 수만큼 읽는 것은 정상이라
    # 이 휴리스틱은 거짓 경보만 냈다 — 제거한다.
    if not markers:
        names = ", ".join(name for name, _ in chunks)
        return Check("Azahar 로그", "!", f"{names}: LayeredFS 적용 로그가 없습니다. 게임을 한 번 실행한 뒤 다시 검사하세요.")
    names = ", ".join(name for name, _ in chunks)
    detail = f"{names}: " + ", ".join(markers)
    status = "O"
    return Check("Azahar 로그", status, detail)


# ---------------------------------------------------------------- 심층 진단 ----
# 엔트리 1190 은 압축을 풀면 다시 5개 섹션짜리 컨테이너다.  섹션마다 무엇이 들어
# 있는지, 그리고 원본에 남아 있던 일본어 가나 바이트가 몇 개였는지를 기록해 둔다.
# 파일 크기나 세 군데 probe 만으로는 "UI 는 한글인데 카드만 원문" 같은 반쪽 상태를
# 잡아내지 못해서(이슈 #17), 섹션별 번역률을 직접 계산한다.
CARD_DB_SECTIONS = (
    ("s0 카드 이름·능력·설명", 0x000028, 153786, 44986),
    ("s1 보조 텍스트",          0x0258E4,   3253,   677),
    ("s2 규칙·도움말",          0x02659C,  12382,  2647),
    ("s3 메뉴·UI 텍스트",       0x0295FC,  84164, 20201),
)
# 배포본별 지문: (파일 크기, s0 가나 수) -> 이름
KNOWN_BUILDS = {
    (291_464_350, 44986): "원본(한글패치 안 됨)",
    (294_044_643, 44973): "v1.0 (2026-07-10, 카드 DB 미번역)",
    (294_044_643,  4109): "v1.1",
    (296_031_199,  4109): "v1.2 / v1.3",
    (296_032_236,  1701): "v1.4 ~ v1.6",
    (303_849_467,  1695): "v1.7",
    (303_997_594,  1695): "v1.8",
    (304_251_261,  1695): "v1.9",
    (300_005_903,  1695): "v2.0 이후(현재 계열)",
}


def _kana_count(buf: bytes, start: int, length: int) -> int:
    """Shift-JIS 가나·기호 리드바이트(0x81~0x84) 쌍의 개수 = 남은 원문 분량."""
    seg = buf[start:start + length]
    n = i = 0
    end = len(seg) - 1
    while i < end:
        if 0x81 <= seg[i] <= 0x84:
            n += 1
            i += 2
        else:
            i += 1
    return n


def _check_card_db(user_dir: Path) -> Check:
    path = _find_path(user_dir, "load", "mods", BASE_TITLE_ID, "romfs", "CULDCEPT.DAT")
    if path is None or not path.is_file():
        return Check("카드 DB 번역 상태", "X", "본편 CULDCEPT.DAT 이 없어 검사하지 못했습니다.", True)
    try:
        data = path.read_bytes()
        entry_offset, entry_size = struct.unpack_from("<II", data, 1190 * 8)
        ui = huffman.decompress(data[entry_offset:entry_offset + entry_size])
    except (OSError, IndexError, struct.error, ValueError, NotImplementedError) as exc:
        return Check("카드 DB 번역 상태", "X", f"엔트리 1190 해제 실패: {exc}", True)

    parts = []
    worst = None
    for label, start, length, original in CARD_DB_SECTIONS:
        left = _kana_count(ui, start, length)
        done = max(0, min(100, round((1 - left / original) * 100)))
        parts.append(f"{label} {done}%")
        if worst is None or done < worst[0]:
            worst = (done, label, left)

    size = path.stat().st_size
    s0_left = _kana_count(ui, CARD_DB_SECTIONS[0][1], CARD_DB_SECTIONS[0][2])
    build = KNOWN_BUILDS.get((size, s0_left))
    if build is None:
        # 정확히 일치하는 배포본이 없으면 s0 만으로 대략 판정한다.
        build = "알 수 없는 조합" if s0_left > 5000 else "현재 계열(크기 다름)"
    detail = " / ".join(parts) + f" — 판정: {build}"

    if worst is not None and worst[0] < 50:
        return Check(
            "카드 DB 번역 상태",
            "X",
            detail + f" ▶ {worst[1]} 섹션에 원문이 {worst[2]:,}자 남아 있습니다. "
            "게임이 이 파일이 아닌 다른 CULDCEPT.DAT 을 읽고 있거나 파일이 구버전입니다.",
            True,
        )
    return Check("카드 DB 번역 상태", "O", detail)


OTHER_USER_DIRS = (
    ("Azahar", ("AppData", "Roaming", "Azahar")),
    ("Azahar(Local)", ("AppData", "Local", "Azahar")),
    ("Citra", ("AppData", "Roaming", "Citra")),
    ("Lime3DS", ("AppData", "Roaming", "Lime3DS")),
)


def _newest_log_time(user_dir: Path) -> float:
    log_dir = _find_path(user_dir, "log")
    if log_dir is None or not log_dir.is_dir():
        return 0.0
    times = [item.stat().st_mtime for item in log_dir.glob(LOG_GLOB) if item.is_file()]
    return max(times) if times else 0.0


def _check_other_user_dirs(user_dir: Path) -> Check:
    """진단한 폴더 말고 다른 에뮬레이터 사용자 폴더가 실제로 쓰이고 있는지 본다.

    설치는 A 폴더에 했는데 게임은 B 폴더로 돌아가면, 파일 검사는 전부 통과하는데
    게임에는 아무 변화가 없다(이슈 #17 의 유력 원인).  최근에 쓴 로그가 있는 쪽이
    실제로 돌아가는 폴더다.
    """
    home = Path.home()
    here = user_dir.resolve()
    mine = _newest_log_time(user_dir)
    others = []
    for name, parts in OTHER_USER_DIRS:
        candidate = home.joinpath(*parts)
        if not candidate.is_dir() or candidate.resolve() == here:
            continue
        stamp = _newest_log_time(candidate)
        if stamp:
            others.append((stamp, name, candidate))
    # azahar.exe 옆의 포터블 user 폴더
    for exe_dir in (Path("C:/Program Files/Azahar"), Path("C:/Program Files (x86)/Azahar")):
        candidate = exe_dir / "user"
        if candidate.is_dir() and candidate.resolve() != here:
            others.append((_newest_log_time(candidate), "포터블(azahar.exe 옆 user)", candidate))
    if not others:
        return Check("다른 에뮬레이터 폴더", "O", "발견되지 않음")
    newer = [item for item in others if item[0] > mine]
    text = ", ".join(f"{name} ({path})" for _, name, path in others)
    if newer:
        return Check(
            "다른 에뮬레이터 폴더",
            "X",
            f"{text} — 이 폴더의 로그가 더 최근입니다. 게임이 그쪽 폴더로 실행되고 있으므로 "
            "설치.cmd 를 그 폴더를 지정해 다시 실행하세요: 설치.cmd \"<폴더경로>\"",
            True,
        )
    return Check("다른 에뮬레이터 폴더", "!", f"{text} — 사용 흔적은 더 오래됐습니다.")


def _check_save_states(user_dir: Path) -> Check:
    """세이브 스테이트를 불러오면 패치 전 화면이 그대로 살아난다."""
    states = _find_path(user_dir, "states")
    dat = _find_path(user_dir, "load", "mods", BASE_TITLE_ID, "romfs", "CULDCEPT.DAT")
    if states is None or not states.is_dir():
        return Check("세이브 스테이트", "O", "없음")
    files = [item for item in states.glob(f"{BASE_TITLE_ID}*.cst") if item.is_file()]
    if not files:
        return Check("세이브 스테이트", "O", "없음")
    if dat is not None and dat.is_file():
        stale = [item for item in files if item.stat().st_mtime < dat.stat().st_mtime]
        if stale:
            return Check(
                "세이브 스테이트",
                "!",
                f"{len(stale)}개가 패치본보다 오래됐습니다. 스테이트를 불러오면 "
                "패치 전 텍스트와 DLC 목록이 그대로 살아납니다 — 반드시 게임을 새로 시작하세요.",
            )
    return Check("세이브 스테이트", "O", f"{len(files)}개(패치본보다 최신)")



def _find_installed_update(user_dir: Path) -> Path | None:
    """가상 SD 에 설치된 게임 업데이트(0004000e000f5700)를 찾는다."""
    sdmc = _find_path(user_dir, "sdmc", "Nintendo 3DS")
    if sdmc is None or not sdmc.is_dir():
        return None
    for id0 in sdmc.iterdir():
        if not id0.is_dir():
            continue
        for id1 in id0.iterdir():
            content = _find_path(id1, "title", "0004000e", "000f5700", "content")
            if content is None or not content.is_dir():
                continue
            apps = [item for item in content.rglob("*.app") if item.is_file()]
            if apps:
                return max(apps, key=lambda item: item.stat().st_size)
    return None


def _check_update_code(user_dir: Path) -> Check:
    """업데이트 실행코드 안의 카드 DB 가 한글로 바뀌었는지 본다(이슈 #17).

    ver 1.2 업데이트에는 RomFS 가 없고 `.code` 만 있는데, 그 안에 카드 이름·능력·
    설명이 통째로 들어 있다. 업데이트를 깔면 게임은 카드 텍스트를 CULDCEPT.DAT 이
    아니라 이 실행코드에서 읽는다. 그래서 DAT 만 한글화하면 메뉴는 한글인데 카드만
    원문으로 남는다 — 오래 잡히지 않던 증상의 정체다.
    """
    update = _find_installed_update(user_dir)
    override = _find_path(user_dir, "load", "mods", BASE_TITLE_ID, "exefs", "code.bin")
    if update is None:
        if override is not None and override.is_file():
            return Check(
                "게임 업데이트 실행코드",
                "X",
                "업데이트가 설치돼 있지 않은데 exefs/code.bin 오버라이드가 있습니다. "
                "설치.cmd 를 실행하면 정리됩니다.",
                True,
            )
        return Check("게임 업데이트 실행코드", "O", "업데이트 미설치 — 카드 텍스트는 DAT 에서 읽습니다")

    if override is None or not override.is_file():
        return Check(
            "게임 업데이트 실행코드",
            "X",
            f"게임 업데이트(ver 1.2)가 설치돼 있는데 한글화된 실행코드가 없습니다: {update.name}. "
            "이 상태면 메뉴는 한글이지만 ★카드 이름·능력만 원문★ 으로 나옵니다. "
            "설치.cmd 를 실행하세요.",
            True,
        )

    data = override.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest == UPDATE_CODE_KO_SHA256:
        return Check("게임 업데이트 실행코드", "O", f"카드 DB 한글화 확인 ({len(data):,}바이트)")
    if digest == UPDATE_CODE_SHA256:
        return Check(
            "게임 업데이트 실행코드",
            "X",
            "오버라이드가 원본 실행코드 그대로입니다 — 카드가 원문으로 나옵니다. 설치.cmd 를 실행하세요.",
            True,
        )
    start, length = UPDATE_CARD_DB
    if len(data) >= start + length:
        left = _kana_count(data, start, length)
        done = max(0, min(100, round((1 - left / 44986) * 100)))
        status, blocking = ("O", False) if done >= 90 else ("X", True)
        return Check("게임 업데이트 실행코드", status,
                     f"카드 DB 번역률 {done}% (알려진 판과 다른 실행코드)", blocking)
    return Check("게임 업데이트 실행코드", "!", f"알 수 없는 실행코드 ({len(data):,}바이트)")


# ------------------------------------------------------- 배포본 정확 판별 ----
# `KNOWN_BUILDS` 는 (파일크기, 가나수) 로만 보기 때문에 v2.0 이후를 전부 "현재 계열"
# 하나로 묶어 버린다. 그래서 **여러 판을 건너뛰며 옛 DAT 을 그대로 쓰고 있어도**
# 정상으로 보였다(이슈 #26). 설치 안내가 "본편 CULDCEPT.DAT 은 건드리지 않습니다"
# 라고 적혀 있어, 릴리즈마다 xdelta 를 다시 적용해야 한다는 걸 놓치기 쉽다.
# 그래서 SHA-256 으로 **어느 판인지 정확히** 찍어 준다.
RELEASE_DAT_SHA = "9ccd540e5dd5b2a0d98e1fbb9941cdf1909f74990a883f3c968328f49f6f6f1d"
RELEASE_NAME = "v2.25"
KNOWN_DAT_SHA = {
    "82cedc2e6d91ef28b1cf776e7dd0219be5fcefe5b325a980c78dc1107edb8562": "v2.17",
    "d457cd6a2a1cce0955347170d709571f1092805b6a1c52ce7a25976fd0af0f94": "v2.18",
    "7dd7ddf16bc5558b4cfb3db85922c32a3af4fade810e5e79e20ca68d4aff16d4": "v2.19",
    "2b9cf91f7381c8c810a1cf25f2530989d638374b18842ca5cff57ee92f89e334": "v1.4",
    "752cb0a351f68985fdaf56d0f9b3d6771951113b342f617785f1525712ecfcb7": "v1.6",
    "ac26c42f2980cbef959869b45307801688154bd018982f953784422eb79ec1e8": "v1.8",
    "d75ac2b051433da15a9fe0eb26e22c64b594f9829094708eb3d6ddbd8bb2c54f": "v1.9",
    "41f9339eb3989d7375848eca04fe79b22afb29a494e4999540e70e18459faa3c": "v2.0",
    "6b10fbbdcba523bbc8a1b545f9452a3eac6ff85a9d459791f9049c4493c73c80": "v2.1",
    "b51c535dda74d72ca6ddaae7f69d5a834512fbd42be5c43f9c83d10903b8c19d": "v2.20/v2.21",
    "dc9f7457d04011b659efb7af5dae7b38adf43fb336762348fe61bdc3d1e3ec2f": "v2.22",
    "0c6aeb5c4836382dc4e83832bdb042a784cdf35ea298f676651018ad4c515179": "v2.23",
    "6f9b2f79640ca57394f51e00fbb4f083e5d941fe4be461e2bfcbf4b41e224de1": "v2.24",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_dat_version(user_dir: Path) -> Check:
    """설치된 CULDCEPT.DAT 이 **이번 릴리즈로 만든 것인지** 해시로 확인한다."""
    path = _find_path(user_dir, "load", "mods", BASE_TITLE_ID, "romfs", "CULDCEPT.DAT")
    if path is None or not path.is_file():
        return Check("본편 DAT 판본", "X",
                     "본편 CULDCEPT.DAT 이 없습니다. README 1단계를 하세요.", True)
    got = _sha256(path)
    if got == RELEASE_DAT_SHA:
        return Check("본편 DAT 판본", "O", f"{RELEASE_NAME} 로 만든 파일이 맞습니다.")
    old = KNOWN_DAT_SHA.get(got)
    which = f"{old} 로 만든 파일입니다" if old else "어느 판인지 알 수 없는 파일입니다"
    return Check(
        "본편 DAT 판본", "X",
        f"{which} (현재 릴리즈 = {RELEASE_NAME}). "
        f"★ 본편 텍스트·인물 이름·대사는 **거의 전부 이 파일 안에** 있습니다. "
        f"설치.cmd 는 이 파일을 건드리지 않으므로, **릴리즈마다** 원본 CULDCEPT.DAT 에 "
        f"culdcept-korean.xdelta 를 다시 적용해 이 자리에 덮어써야 합니다(README 1단계).",
        True)


def inspect_install(user_dir: Path) -> list[Check]:
    return [
        _check_base(user_dir),
        _check_dat_version(user_dir),
        _check_card_db(user_dir),
        _check_update_code(user_dir),
        _check_catalog(user_dir),
        _check_wrong_base_placement(user_dir),
        _check_installed_dlc(user_dir),
        _check_virtual_sd(user_dir),
        _check_other_user_dirs(user_dir),
        _check_save_states(user_dir),
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
