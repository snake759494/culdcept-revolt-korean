# -*- coding: utf-8 -*-
"""카드 데이터베이스(엔트리 1190) 텍스트 처리.

1190 은 null 종료 SJIS 문자열의 모음이며, 카드 능력/설명/플레이버 텍스트가
들어 있습니다. 문자열은 포인터로 참조되므로 **제자리 교체(원문 바이트 길이 이하,
부족분 0x20 채움)** 만 안전합니다.

카드 텍스트에는 아이콘 가이지(비표준 SJIS)와 제어코드가 섞여 있어, 번역문은
"뷰(view)" 형태 — 한글 + `⟦k⟧` 토큰 자리표시자 — 로 저장합니다. 각 토큰은 원문에서
그대로 보존해야 할 바이트열(아이콘·제어코드)을 가리키며, 적용 시 **본인 파일의
원문 문자열을 다시 토큰화**해 그 바이트를 채워 넣습니다. 따라서 이 저장소에는
일본어 원문이 없습니다 — 인덱스와 한글 뷰만 있습니다(cards_ko.json).
"""
from collections import OrderedDict

from . import scen

L, R = "⟦", "⟧"   # ⟦ ⟧


def _jp_char_count(s):
    """문자열 내 디코드 가능한 일본어(가나/한자) 글자 수."""
    cnt = 0
    i = 0
    n = len(s)
    while i < n:
        b = s[i]
        if 0x81 <= b <= 0xfc and i + 1 < n:
            try:
                ch = s[i:i+2].decode("shift_jis")
            except UnicodeDecodeError:
                ch = ""
            # 임의 바이트열에서는 2바이트가 두 글자로 풀리기도 한다(실행코드 스캔 등).
            if len(ch) == 1:
                o = ord(ch)
                if (0x3040 <= o <= 0x30ff) or (0x4e00 <= o <= 0x9fff):
                    cnt += 1
            i += 2
        else:
            i += 1
    return cnt


def enum_unique(ui):
    """1190 평문에서 실제 텍스트로 보이는 null 종료 문자열을 열거·중복제거.

    반환: OrderedDict {bytes: [offset, ...]} — 첫 등장 순서(= 인덱스).
    cards_ko.json 의 키는 이 순서의 정수 인덱스입니다.

    선두에 색상·위치 서식 바이트(0x0e/0x18/0x0c 등)가 붙은 카드 설명·통계 패널
    문자열은 scen._looks_text 를 통과하지 못하므로, 디코드 가능한 일본어 글자가
    3자 이상이면 함께 포함합니다(서식 코드는 인코딩 시 토큰으로 보존).
    """
    def has_jp(bs):
        return any(0x81 <= bs[i] <= 0x9f or 0xe0 <= bs[i] <= 0xfc for i in range(len(bs) - 1))
    strings = []
    start = 0
    for j in range(len(ui)):
        if ui[j] == 0:
            s = bytes(ui[start:j])
            if len(s) >= 2 and has_jp(s) and (scen._looks_text(s) or _jp_char_count(s) >= 3):
                strings.append((start, s))
            start = j + 1
    uniq = OrderedDict()
    for off, s in strings:
        uniq.setdefault(s, []).append(off)
    return uniq


def _translatable(raw, i):
    b = raw[i]
    if b == 0x0a:
        return True, 1, "\n"
    if 0x20 <= b < 0x7f:
        return True, 1, chr(b)
    if 0x81 <= b <= 0xfc and i + 1 < len(raw):
        try:
            return True, 2, raw[i:i+2].decode("shift_jis")
        except UnicodeDecodeError:
            return False, 2, None      # 아이콘 가이지
    return False, 1, None              # 0x07 / 0x03 파라미터 등


def tokenize(raw):
    """원문 바이트 -> (뷰 텍스트, 토큰 리스트). 번역가능 문자는 문자로,
    보존 바이트열은 ⟦k⟧ 토큰(hex)으로."""
    view, tokens, i, n = [], [], 0, len(raw)
    while i < n:
        ok, nb, txt = _translatable(raw, i)
        if ok:
            view.append(txt); i += nb
        else:
            j = i; chunk = bytearray()
            while j < n:
                ok2, nb2, _ = _translatable(raw, j)
                if ok2:
                    break
                chunk += raw[j:j+nb2]; j += nb2
            view.append(L + str(len(tokens)) + R)
            tokens.append(bytes(chunk).hex())
            i = j
    return "".join(view), tokens


NAME_MARK = "{N}"                       # 주인공 이름이 들어가는 자리
NAME_CODE = bytes([0x03, 0x30, 0x2F])   # 실행 중에 세이브의 이름으로 바뀐다


def encode(view_text, tokens, syll2code):
    """번역 뷰(한글+⟦k⟧+\\n) -> 게임 바이트열."""
    out = bytearray(); i = 0; n = len(view_text)
    while i < n:
        ch = view_text[i]
        if view_text.startswith(NAME_MARK, i):
            # 이걸 빠뜨리면 화면에 글자 그대로 "{N}" 이 나온다. dialogue_ko.json 이
            # 이 표기를 쓰는데, 예전에는 apply_korean_full 쪽 인코더만 알고 있어서
            # 같은 문장을 실행코드에 넣을 때 리터럴이 그대로 들어갔다.
            out += NAME_CODE
            i += len(NAME_MARK)
            continue
        if ch == "\n":
            out.append(0x0a); i += 1
        elif ch == L:
            r = view_text.find(R, i)
            if r < 0:
                i += 1; continue
            try:
                out += bytes.fromhex(tokens[int(view_text[i+1:r])])
            except (ValueError, IndexError):
                pass
            i = r + 1
        else:
            i += 1
            if 0xAC00 <= ord(ch) <= 0xD7A3:
                code = syll2code.get(ch)
                if code is not None:
                    out += bytes([code >> 8, code & 0xff])
            else:
                try:
                    out += ch.encode("shift_jis")
                except UnicodeEncodeError:
                    pass
    return bytes(out)


def strip_name_fill(name: bytes) -> bytes:
    """카드 이름 뒤에 우리가 붙인 채움(폭 0 제어코드·공백)을 떼어 낸다."""
    while True:
        if name.endswith(b"\x08@"):
            name = name[:-2]
        elif name.endswith(b" "):
            name = name[:-1]
        else:
            return name


def rebalance_names(region: bytes, name_ends) -> bytes:
    """카드 **이름 필드를 채우지 않고**, 남는 바이트를 바로 뒤 필드로 넘긴다.

    원본 카드 이름 510개 중 채움이 붙은 것은 **하나도 없다.** 번역이 짧다고 뒤를
    채우면 어느 쪽으로 채우든 탈이 났다.

    * 공백으로 채우면 고정폭 폰트에서 그 공백이 그대로 폭이 된다. 카드 이름은
      배너 같은 다른 문장에 끼워 넣어지므로 "ロア의파이어드레이크␣␣␣␣" 가 배너를
      넘겨 ＳＴ/ＨＰ 변환 줄을 화면 밖으로 밀어냈다.
    * 폭 0 제어코드(`0x08 @`)로 채우면 배너는 멀쩡해지지만, **손패 목록 렌더러가
      그 제어코드에 걸린다** — 이름이 통째로 사라지거나, 색이 다음 줄까지 번지거나,
      글자가 깨진다. 목록 아래로 갈수록 심해진다(상태가 누적된다).

    그래서 채우지 않는다. 이름은 번역한 만큼만 쓰고, 남는 바이트는 **바로 뒤
    필드(능력)의 꼬리 공백**으로 옮긴다. 능력 설명은 자기 패널에서 줄이 바뀌므로
    꼬리 공백이 보이지 않고, 원래부터 그렇게 채워 왔다.

    널 **개수**와 레코드 전체 길이는 그대로다. 널 하나가 레코드 안에서 조금
    앞으로 옮겨질 뿐이다 — 게임은 이 구간을 널 단위로 **순서대로** 읽는다(널을
    하나 더 넣으면 뒤 필드가 전부 밀리는 것이 그 증거다).
    """
    out = bytearray(region)
    moved = 0
    for end in sorted(name_ends):
        start = out.rfind(b"\x00", 0, end) + 1
        nxt = out.find(b"\x00", end + 1)
        if nxt < 0:
            continue
        name = bytes(out[start:end])
        body = strip_name_fill(name)
        if body == name or not body:
            continue
        freed = len(name) - len(body)
        nextfield = bytes(out[end + 1:nxt])
        out[start:nxt] = body + b"\x00" + nextfield + b" " * freed
        moved += 1
    assert len(out) == len(region), "구간 길이가 바뀌었다"
    assert out.count(b"\x00") == region.count(b"\x00"), "널 개수가 바뀌었다"
    return bytes(out), moved
