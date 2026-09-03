# -*- coding: utf-8 -*-
"""DLC 리소스의 **압축 섹션 안** 텍스트를 뷰 문자열로 꺼내고 되돌린다.

`dlcres.enum_strings()` 는 복호화된 페이로드의 평문 문자열만 본다. 시나리오(.dlq)와
맵(.dlm)은 페이로드가 다시 섹션 컨테이너라 그 안이 안 보인다. 이 모듈은 섹션을 풀어
널 종료 문자열을 전부 훑는다.

뷰 표기 (게임 바이트 -> 사람이 읽고 쓰는 문자열)

    0x07              ▼      페이지 넘김(대화창 한 장)
    0x0a              \\n     줄바꿈
    0x03 0x30 0x2f    {N}    플레이어 이름 삽입
    그 밖의 제어바이트  ⟦k⟧    원문 바이트를 그대로 되돌릴 자리표시자

★ 되돌릴 때 이 표기를 그대로 바이트로 복원해야 한다. 예전에 `{N}` 이 든 대사를
  "이상한 문자열"로 보고 걸러내는 바람에, 이름이 들어가는 대사가 통째로 번역에서
  빠졌다(이슈 #23). 제어코드가 있다고 텍스트가 아닌 것이 아니다.

★★ 같은 실수를 한 번 더 했다. 예전 `_decode()` 는 **모르는 제어바이트가 하나라도
  있으면 그 문자열 전체를 텍스트가 아니라고 버렸다.** 그래서 선택지 "はい/いいえ"
  (0x15 가 붙어 있다)와 주문 안내문(0x03 파라미터)이 열거조차 되지 않아 원문 그대로
  남았다. 이제는 cardtext 와 같은 방식으로 모르는 제어바이트를 ⟦k⟧ 토큰으로 담아
  두고 되돌릴 때 그대로 복원한다 — 걸러내지 않는다.
"""
import struct

from . import huffman, scen
from . import dlcres

NAME_CODE = bytes([0x03, 0x30, 0x2F])
NAME_MARK = "{N}"
PAGE_MARK = "▼"
L, R = "⟦", "⟧"


def _decode(seg: bytes):
    """세그먼트를 (뷰 문자열, 일본어 글자수, 토큰목록) 으로. 텍스트가 아니면 (None,0,[]).

    모르는 제어바이트는 버리지 않고 ⟦k⟧ 토큰으로 담는다. 텍스트가 아니라고 보는 건
    **2바이트 문자로 해석되지 않는 바이트열**뿐이다.
    """
    out, tokens = [], []
    i, n, jp = 0, len(seg), 0
    while i < n:
        b = seg[i]
        if seg[i:i + 3] == NAME_CODE:
            out.append(NAME_MARK)
            i += 3
            continue
        if b == 0x07:
            out.append(PAGE_MARK)
            i += 1
            continue
        if b == 0x0A:
            out.append("\n")
            i += 1
            continue
        if b < 0x20:                                # 모르는 제어코드 -> 토큰으로 보존
            j = i
            while j < n and seg[j] < 0x20 and seg[j] not in (0x07, 0x0A) \
                    and seg[j:j + 3] != NAME_CODE:
                j += 1
                if j < n and seg[j - 1] == 0x03:    # 0x03 은 파라미터 1바이트를 문다
                    j += 1
            out.append(L + str(len(tokens)) + R)
            tokens.append(seg[i:j].hex())
            i = j
            continue
        if b < 0x80:
            out.append(chr(b))
            i += 1
            continue
        if i + 1 >= n:
            return None, 0, []
        try:
            ch = seg[i:i + 2].decode("cp932")
        except UnicodeDecodeError:
            return None, 0, []
        if len(ch) != 1:
            return None, 0, []
        out.append(ch)
        if "぀" <= ch <= "ヿ" or "一" <= ch <= "鿿":
            jp += 1
        i += 2
    return "".join(out), jp, tokens


def encode(view: str, syll2code: dict, tokens=()) -> bytes:
    """뷰 문자열을 게임 바이트로. 완성형 한글은 폰트 슬롯 코드로 나간다."""
    out = bytearray()
    i, n = 0, len(view)
    while i < n:
        if view.startswith(NAME_MARK, i):
            out += NAME_CODE
            i += len(NAME_MARK)
            continue
        ch = view[i]
        if ch == L:
            r = view.find(R, i)
            if r > 0:
                try:
                    out += bytes.fromhex(tokens[int(view[i + 1:r])])
                except (ValueError, IndexError):
                    pass
                i = r + 1
                continue
        i += 1
        if ch == PAGE_MARK:
            out.append(0x07)
            continue
        if ch == "\n":
            out.append(0x0A)
            continue
        code = syll2code.get(ch)
        if code is not None:
            out += bytes([code >> 8, code & 0xFF])
            continue
        out += ch.encode("cp932")
    return bytes(out)


def sections(raw: bytes):
    """(섹션 번호, 코덱 타입, 해제된 섹션) 목록. 압축 섹션만."""
    plain = dlcres.decrypt(raw)
    size = struct.unpack_from("<I", plain, 4)[0]
    start = dlcres.payload_off(plain)
    container = plain[start:size]
    parsed = scen.parse_sections(container)
    if not parsed:
        return []
    out = []
    for index, (offset, length) in enumerate(parsed):
        if not length:
            continue
        blob = container[offset:offset + length]
        if blob[0] not in (0x08, 0x0C):
            continue
        try:
            out.append((index, blob[0], huffman.decompress(blob)))
        except Exception:                       # noqa: BLE001
            continue
    return out


def enum_section_text(section: bytes, min_jp: int = 2):
    """섹션 안의 널 종료 텍스트를 (오프셋, 원본바이트, 뷰) 로 전부 열거한다."""
    found = []
    offset = 0
    for seg in section.split(b"\x00"):
        if len(seg) >= 2:
            view, jp, _tokens = _decode(seg)
            if view is not None and jp >= min_jp:
                found.append((offset, bytes(seg), view))
        offset += len(seg) + 1
    return found


def enum_all(raw: bytes, min_jp: int = 2):
    """리소스 하나의 압축 섹션 전체에서 텍스트를 열거한다.

    반환: [(섹션번호, 오프셋, 원본바이트, 뷰), ...]
    """
    out = []
    for index, _typ, section in sections(raw):
        for offset, original, view in enum_section_text(section, min_jp):
            out.append((index, offset, original, view))
    return out
