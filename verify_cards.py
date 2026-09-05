#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""원본과 패치본 CULDCEPT.DAT의 수집 카드 449장을 전수 검사한다.

    python verify_cards.py <원본/CULDCEPT.DAT> <패치본/CULDCEPT.DAT>

카드 목록이나 일본어 원문을 저장소에 복사하지 않고, 엔트리 1190의 레코드 구조를
이용해 카드 경계를 찾는다. 각 레코드는 다음 널 종료 필드로 식별된다.

    [표시 이름] [능력] [영문 이름] [플레이버] [용어] [전략]

같은 영문 이름이 반복되는 변신용 내부 레코드는 수집 카드가 아니므로 제외한다.
남는 고유 영문 이름 레코드는 크리처 241장, 아이템 75장, 스펠 133장 순서이며
합계 449장이다.

검사는 다음을 모두 요구한다.

* 원본과 패치본의 엔트리 1190 길이가 같고, **카드 레코드 구간(섹션 s0)** 의 널
  구분 오프셋이 모두 동일할 것
* 일본어가 있던 다섯 필드가 모두 바뀌고 고정 완성형 한글 코드를 포함할 것
* 영문 식별자는 바뀌지 않을 것
* 필드별 일본어 원문 수와 카드 종류별 수가 알려진 전수 집계와 일치할 것

널 검사를 **s0 로 한정하는 이유**: 게임은 카드 레코드의 필드를 널로 구분해 세면서
읽으므로, s0 에 널이 하나만 늘어도 뒤 필드가 전부 밀린다. 반면 UI 섹션 s3 의 짧은
라벨은 **일부러 널로 채운다**(뒤에 공백을 붙이면 고정폭 폰트에서 칸이 벌어져 보인다).
s3 은 오프셋으로 참조하므로 널이 늘어도 안전하다.

엔트리 전체로 널을 세면 이 정상적인 s3 패딩 때문에 항상 불일치가 나고, 거기서 검사가
멈춰 **정작 중요한 카드 필드 검사가 한 번도 돌지 않았다**(v2.21~v2.23 내내 그랬다).

게임 데이터나 카드 원문은 출력하거나 저장하지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import struct
import sys
from collections import Counter
from pathlib import Path

from culdcept import font as fontmod
from culdcept import huffman, scen, wansung


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


CARD_ENTRY = 1190
FONT_ENTRY = 1054

CATEGORY_RANGES = (
    ("크리처", 241, 698, 2378),
    ("아이템", 75, 2385, 2903),
    ("스펠", 133, 2910, 3834),
)
EXPECTED_TOTAL = sum(count for _, count, _, _ in CATEGORY_RANGES)

FIELD_OFFSETS = (
    ("표시 이름", -2),
    ("능력", -1),
    ("플레이버", 1),
    ("용어", 2),
    ("전략", 3),
)
EXPECTED_JAPANESE_FIELDS = {
    "표시 이름": 449,
    "능력": 423,
    "플레이버": 449,
    "용어": 292,
    "전략": 449,
}

# 실제 영문 카드명에 줄바꿈이 들어간 항목이 하나 있다. 허용 문자는 카드명에 쓰이는
# ASCII로만 제한해 일반 UI 문구나 바이너리 조각이 레코드로 오인되지 않게 한다.
_ENGLISH_NAME = re.compile(rb"[A-Za-z][A-Za-z0-9 .&!'/():+,\-\n]*\Z")


def _read_entry(path: Path, index: int) -> bytes:
    """DAT 전체를 메모리에 올리지 않고 지정 엔트리만 읽는다."""
    with path.open("rb") as stream:
        first = stream.read(4)
        if len(first) != 4:
            raise ValueError(f"DAT 헤더가 너무 짧습니다: {path}")
        count = struct.unpack("<I", first)[0] // 8
        if not 0 <= index < count:
            raise ValueError(f"엔트리 {index}가 없습니다(엔트리 수 {count}): {path}")
        stream.seek(index * 8)
        record = stream.read(8)
        if len(record) != 8:
            raise ValueError(f"엔트리 {index} 테이블이 잘렸습니다: {path}")
        offset, size = struct.unpack("<II", record)
        stream.seek(0, 2)
        file_size = stream.tell()
        if offset + size > file_size:
            raise ValueError(
                f"엔트리 {index} 범위가 파일 밖입니다: "
                f"0x{offset:X}+0x{size:X} > 0x{file_size:X}"
            )
        stream.seek(offset)
        data = stream.read(size)
    if len(data) != size:
        raise ValueError(f"엔트리 {index}를 끝까지 읽지 못했습니다: {path}")
    return data


def _decoded_entry(path: Path, index: int) -> bytes:
    entry = _read_entry(path, index)
    if not entry or entry[0] not in (0x08, 0x0C):
        kind = "없음" if not entry else f"0x{entry[0]:02X}"
        raise ValueError(f"엔트리 {index}의 코덱이 0x08/0x0C가 아닙니다: {kind}")
    return huffman.decompress(entry)


def _is_sjis_lead(value: int) -> bool:
    """Shift-JIS의 실제 2바이트 선두 범위(반각 가나는 제외)."""
    return 0x81 <= value <= 0x9F or 0xE0 <= value <= 0xFC


def _is_sjis_trail(value: int) -> bool:
    return 0x40 <= value <= 0x7E or 0x80 <= value <= 0xFC


def japanese_char_count(raw: bytes) -> int:
    """제어 바이트가 섞인 필드에서도 안전하게 일본어 글자 수를 센다."""
    count = 0
    index = 0
    while index < len(raw):
        value = raw[index]
        if (
            _is_sjis_lead(value)
            and index + 1 < len(raw)
            and _is_sjis_trail(raw[index + 1])
        ):
            pair = raw[index:index + 2]
            try:
                char = pair.decode("shift_jis")
            except UnicodeDecodeError:
                index += 1
                continue
            codepoint = ord(char)
            if (
                0x3040 <= codepoint <= 0x30FF
                or 0x3400 <= codepoint <= 0x4DBF
                or 0x4E00 <= codepoint <= 0x9FFF
            ):
                count += 1
            index += 2
            continue
        index += 1
    return count


def is_english_name(raw: bytes) -> bool:
    return (
        1 <= len(raw) <= 48
        and _ENGLISH_NAME.fullmatch(raw) is not None
        and any(0x41 <= value <= 0x5A or 0x61 <= value <= 0x7A for value in raw)
    )


def discover_card_records(segments: list[bytes]) -> tuple[list[int], list[int]]:
    """(수집 카드 인덱스, 구조상 카드형 레코드 전체 인덱스)를 반환한다."""
    candidates = []
    for index in range(2, len(segments) - 3):
        if not is_english_name(segments[index]):
            continue
        if not japanese_char_count(segments[index - 2]):
            continue
        if not japanese_char_count(segments[index + 1]):
            continue
        if not japanese_char_count(segments[index + 3]):
            continue
        candidates.append(index)

    frequencies = Counter(segments[index] for index in candidates)
    collectible = [index for index in candidates if frequencies[segments[index]] == 1]
    return collectible, candidates


def contains_fixed_hangul(raw: bytes, hangul_codes: set[int]) -> bool:
    """필드에 패치의 고정 완성형 코드가 하나 이상 있는지 검사한다."""
    index = 0
    while index + 1 < len(raw):
        lead, trail = raw[index], raw[index + 1]
        if _is_sjis_lead(lead) and _is_sjis_trail(trail):
            if (lead << 8 | trail) in hangul_codes:
                return True
            index += 2
        else:
            index += 1
    return False


def null_offsets(data: bytes, start: int = 0, end: int | None = None) -> list[int]:
    """[start, end) 안의 널 위치. 범위를 안 주면 전체."""
    stop = len(data) if end is None else end
    return [index for index in range(start, stop) if data[index] == 0]


def card_region(entry: bytes) -> tuple[int, int]:
    """카드 레코드가 들어 있는 구간(섹션 s0)의 [시작, 끝).

    섹션을 못 읽으면 전체를 돌려준다(그 경우 예전처럼 전체를 검사한다).
    """
    sections = scen.parse_sections(entry) or []
    if not sections:
        return 0, len(entry)
    start, length = sections[0]
    return start, start + length


def segments_before(data: bytes, limit: int) -> int:
    """오프셋 `limit` 앞에서 끝나는 널 구분 세그먼트의 개수."""
    return sum(1 for index in range(limit) if data[index] == 0)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def audit_cards(original_path: Path, patched_path: Path) -> list[str]:
    """검사 결과를 출력하고, 실패 설명 목록을 반환한다."""
    original = _decoded_entry(original_path, CARD_ENTRY)
    patched = _decoded_entry(patched_path, CARD_ENTRY)

    failures: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    require(
        len(original) == len(patched),
        f"엔트리 {CARD_ENTRY} 길이 불일치: 원본 {len(original):,} / 패치본 {len(patched):,}",
    )
    original_nulls = null_offsets(original)
    patched_nulls = null_offsets(patched)
    require(
        original_nulls == patched_nulls,
        f"엔트리 {CARD_ENTRY} 널 구분 오프셋 불일치: "
        f"원본 {len(original_nulls):,} / 패치본 {len(patched_nulls):,}",
    )

    original_segments = original.split(b"\0")
    patched_segments = patched.split(b"\0")
    require(
        len(original_segments) == len(patched_segments),
        f"널 세그먼트 수 불일치: 원본 {len(original_segments):,} / "
        f"패치본 {len(patched_segments):,}",
    )
    if len(original_segments) != len(patched_segments):
        return failures

    records, all_candidates = discover_card_records(original_segments)
    require(
        len(records) == EXPECTED_TOTAL,
        f"수집 카드 수 불일치: 기대 {EXPECTED_TOTAL} / 발견 {len(records)}",
    )
    category_counts = {
        category: sum(start <= index <= end for index in records)
        for category, _, start, end in CATEGORY_RANGES
    }
    for category, expected, _, _ in CATEGORY_RANGES:
        require(
            category_counts[category] == expected,
            f"{category} 카드 수 불일치: 기대 {expected} / "
            f"발견 {category_counts[category]}",
        )
    require(
        sum(category_counts.values()) == len(records),
        "알려진 크리처·아이템·스펠 구간 밖에서 고유 카드형 레코드가 발견됨",
    )

    font_blob = _decoded_entry(patched_path, FONT_ENTRY)
    cmap = fontmod.parse_cmap(font_blob)
    hangul_codes = set(wansung.build_fixed_map(cmap).values())
    require(
        len(hangul_codes) == len(wansung.WANSUNG_2350),
        f"고정 완성형 폰트 매핑 수 불일치: 기대 {len(wansung.WANSUNG_2350)} / "
        f"발견 {len(hangul_codes)}",
    )

    japanese_fields = Counter()
    unchanged_fields: list[tuple[int, str]] = []
    fields_without_hangul: list[tuple[int, str]] = []
    changed_fields = Counter()
    changed_bytes = 0
    english_changed: list[int] = []

    for card_number, segment_index in enumerate(records, 1):
        if original_segments[segment_index] != patched_segments[segment_index]:
            english_changed.append(card_number)

        for field_name, relative in FIELD_OFFSETS:
            source = original_segments[segment_index + relative]
            target = patched_segments[segment_index + relative]
            if not japanese_char_count(source):
                continue
            japanese_fields[field_name] += 1
            if source == target:
                unchanged_fields.append((card_number, field_name))
                continue
            changed_fields[field_name] += 1
            changed_bytes += sum(a != b for a, b in zip(source, target))
            if not contains_fixed_hangul(target, hangul_codes):
                fields_without_hangul.append((card_number, field_name))

    require(not english_changed, f"영문 식별자가 바뀐 카드 {len(english_changed)}장")
    require(
        dict(japanese_fields) == EXPECTED_JAPANESE_FIELDS,
        "일본어 원문 필드 집계 불일치: "
        + ", ".join(f"{name}={japanese_fields[name]}" for name, _ in FIELD_OFFSETS),
    )
    require(
        not unchanged_fields,
        f"일본어 원문이 그대로인 필드 {len(unchanged_fields)}개",
    )
    require(
        not fields_without_hangul,
        f"변경됐지만 고정 완성형 한글 코드가 없는 필드 {len(fields_without_hangul)}개",
    )

    print(f"원본 SHA-256 : {sha256_file(original_path)}")
    print(f"패치 SHA-256 : {sha256_file(patched_path)}")
    print()
    print(f"[{'O' if len(records) == EXPECTED_TOTAL else 'X'}] 수집 카드 {len(records)}/{EXPECTED_TOTAL}장")
    for category, expected, _, _ in CATEGORY_RANGES:
        actual = category_counts[category]
        print(f"    {category}: {actual}/{expected}")
    print(
        f"[{'O' if original_nulls == patched_nulls else 'X'}] "
        f"카드 레코드 구간(s0) 널 구분 오프셋 {len(original_nulls):,}개 동일"
    )
    print(
        f"[O] 카드형 레코드 {len(all_candidates)}개 중 "
        f"반복 내부 레코드 {len(all_candidates) - len(records)}개 제외"
    )
    print("[O] 일본어 원문 필드 번역 적용")
    for field_name, _ in FIELD_OFFSETS:
        print(
            f"    {field_name}: {changed_fields[field_name]}/"
            f"{japanese_fields[field_name]} 변경"
        )
    print(f"[O] 실제 변경 바이트(검사 필드): {changed_bytes:,}")
    print(
        f"[{'O' if not english_changed else 'X'}] "
        f"영문 식별자 {len(records) - len(english_changed)}/{len(records)}개 보존"
    )
    print(f"[{'O' if not unchanged_fields else 'X'}] 미번역 일본어 필드 {len(unchanged_fields)}개")
    print(
        f"[{'O' if not fields_without_hangul else 'X'}] "
        f"한글 코드 없는 번역 대상 필드 {len(fields_without_hangul)}개"
    )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CULDCEPT.DAT 원본/패치본의 수집 카드 449장 전수 검증"
    )
    parser.add_argument("original", type=Path, help="일본판 Rev 2 원본 CULDCEPT.DAT")
    parser.add_argument("patched", type=Path, help="한글 패치가 적용된 CULDCEPT.DAT")
    args = parser.parse_args(argv)

    for path in (args.original, args.patched):
        if not path.is_file():
            parser.error(f"파일이 없습니다: {path}")

    try:
        failures = audit_cards(args.original, args.patched)
    except (OSError, ValueError, IndexError, struct.error) as error:
        print(f"[X] 검사 중단: {error}", file=sys.stderr)
        return 2

    if failures:
        print("\n결과: 실패")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\n결과: 449장 전부 번역 적용 및 구조 보존 확인")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
