# -*- coding: utf-8 -*-
"""대사 페이지를 **원본 바이트 길이에 맞춰 채우되 줄이 넓어지지 않게** 한다.

배경: 이 게임의 대사 폰트는 고정폭이다. 그래서 **반각 공백(1바이트)도 한자·가나·
한글(2바이트)과 똑같이 한 칸**을 차지한다. 예전 코드는 "공백은 1바이트라 2바이트
글자보다 좁으니 원본 줄 길이(바이트)까지 채우면 절대 안 넘친다"고 봤는데, 이게
틀렸다. 40바이트(=20칸)짜리 원문 줄을 30바이트 한글로 옮기고 남는 10바이트를
반각 공백으로 채우면 16칸 + 10칸 = **26칸**이 되어 대화창을 넘긴다. 넘친 만큼은
다음 줄로 밀리고, 페이지가 밀려 **빈 대화창**이 한 장 생긴다(이슈 #24/#29).

고치는 법: 채움을 **전각 공백 0x8140**으로 한다. 2바이트에 한 칸이라 원문 글자와
밀도가 같아, 바이트를 맞추면 칸도 원문 수준으로 맞는다. 남는 홀수 1바이트만
반각 공백 하나로 메운다. 어느 줄에 넣을지는 **그때그때 가장 짧은 줄**에 한 칸씩
주어, 결과적으로 가장 넓은 줄의 폭이 최소가 되게 한다.

0x8140 은 폰트 cmap 에 그대로 있고(한글은 JIS 제1수준 한자 슬롯 0x889f~0x9872 만
가져다 쓴다) 원래대로 빈칸을 그린다.
"""
import heapq

FULL = b"\x81\x40"          # 전각 공백 = 2바이트 1칸
HALF = b"\x20"              # 반각 공백 = 1바이트 1칸
NEWLINE = 0x0A


def _step(bs, i):
    """바이트 i 에서 시작하는 글자 하나의 길이."""
    c = bs[i]
    if c == 0x03:           # 3바이트 제어코드(아이콘·색 등)
        return 3
    if 0x81 <= c <= 0xFC and i + 1 < len(bs):
        return 2
    return 1


def cells(bs) -> int:
    """화면에서 차지하는 **칸 수**. 고정폭이라 글자 수와 같다."""
    n = i = 0
    while i < len(bs):
        i += _step(bs, i)
        n += 1
    return n


def split_lines(bs) -> list:
    """줄바꿈(0x0a)으로 나눈다. 2·3바이트 글자 **안쪽**의 0x0a 는 건드리지 않는다."""
    out, start, i = [], 0, 0
    while i < len(bs):
        step = _step(bs, i)
        if step == 1 and bs[i] == NEWLINE:
            out.append(bytes(bs[start:i]))
            start = i + 1
        i += step
    out.append(bytes(bs[start:]))
    return out


def pad_page(enc: bytes, opage: bytes) -> bytes:
    """`enc` 를 `opage` 와 같은 바이트 길이로 만든다(넘치면 그대로 돌려준다)."""
    need = len(opage) - len(enc)
    if need <= 0:
        return bytes(enc)
    lines = split_lines(enc)
    extra = [0] * len(lines)                    # 줄별 전각 공백 개수
    heap = [(cells(l), i) for i, l in enumerate(lines)]
    heapq.heapify(heap)
    for _ in range(need // 2):
        width, index = heapq.heappop(heap)
        extra[index] += 1
        heapq.heappush(heap, (width + 1, index))
    out = [l + FULL * extra[i] for i, l in enumerate(lines)]
    if need % 2:                                # 남는 1바이트 = 반각 공백 하나
        j = min(range(len(out)), key=lambda i: cells(out[i]))
        out[j] += HALF
    res = bytes([NEWLINE]).join(out)
    if len(res) != len(opage):                  # 이론상 안 나지만 안전장치
        return bytes(enc) + HALF * need
    return res


def widest(page: bytes) -> int:
    """페이지에서 가장 넓은 줄의 칸 수."""
    return max((cells(l) for l in split_lines(page)), default=0)
