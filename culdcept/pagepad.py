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

BOX = 20                    # 대화창 한 줄의 칸 수 — 원본 대사 줄 폭의 최대값
ROWS = 3                    # 대화창이 한 번에 보여 주는 줄 수
FULL = b"\x81\x40"          # 전각 공백 = 2바이트 1칸
HALF = b"\x20"              # 반각 공백 = 1바이트 1칸
NEWLINE = 0x0A


CTRL_ARG = (0x08, 0x0E)     # 인자 1바이트를 먹는 제어코드


def _step(bs, i) -> int:
    """바이트 i 에서 시작하는 한 조각의 길이."""
    c = bs[i]
    if c == 0x03 and i + 2 < len(bs):       # 아이콘·색 지정(3바이트)
        return 3
    if c in CTRL_ARG and i + 1 < len(bs):   # 0x08 O … 0x08 @ 같은 강조 토글
        return 2
    if 0x81 <= c <= 0xFC and i + 1 < len(bs):
        return 2
    return 1


def cells(bs) -> int:
    """화면에서 차지하는 **칸 수**. 제어코드는 0칸, 글자는 고정폭 한 칸.

    제어코드를 한 칸으로 세면 안 된다. 원본 대사 줄을 전수로 재 보면, 제어코드를
    0칸으로 세고 0x08/0x0e 가 인자 한 바이트를 먹는다고 봐야 **예외 없이 20칸
    이하**가 된다(그렇지 않으면 21칸짜리가 남는다).
    """
    n = i = 0
    while i < len(bs):
        step = _step(bs, i)
        if bs[i] >= 0x20:                   # 제어코드가 아니면 한 칸
            n += 1
        i += step
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


def _rows(width: int, box: int = BOX) -> int:
    """폭이 `width` 칸인 줄이 대화창에서 차지하는 줄 수."""
    return max(1, -(-width // box))


def _pick(widths, add: int) -> int:
    """`add` 칸을 어느 줄에 얹을지 — **줄 수가 안 늘어나는 쪽**을 먼저 고른다.

    화면에서 문제가 되는 건 폭이 아니라 **줄 수**다(20칸을 넘으면 게임이 알아서
    줄을 바꾸고, 3줄을 넘으면 빈 대화창이 한 장 생긴다).
    """
    return min(range(len(widths)),
               key=lambda i: (_rows(widths[i] + add), widths[i], i))


def _upgrade_spaces(page: bytes, need: int):
    """낱말 사이 **반각 공백을 전각 공백으로 올려** 바이트만 먹인다.

    고정폭 폰트라 전각 공백도 반각 공백과 똑같이 한 칸이다. 그런데 2바이트다.
    그래서 이렇게 올리면 **화면은 하나도 안 변하면서** 원본 길이에 맞추는 데 필요한
    바이트를 한 개씩 먹어 준다 — 줄 끝에 채움을 덜 붙여도 되니 줄이 안 넘친다.

    Korean 은 낱말마다 공백을 쓰는데 원문 일본어는 거의 안 쓴다. 그 차이가 그대로
    "채워야 할 바이트"로 돌아오던 것을, 바로 그 공백으로 되갚는 셈이다.
    """
    if need <= 0:
        return bytes(page), 0
    out, used, i = bytearray(), 0, 0
    while i < len(page):
        step = _step(page, i)
        if step == 1 and page[i] == 0x20 and used < need:
            out += FULL
            used += 1
        else:
            out += page[i:i + step]
        i += step
    return bytes(out), used


def pad_page(enc: bytes, opage: bytes) -> bytes:
    """`enc` 를 `opage` 와 같은 바이트 길이로 만든다(넘치면 그대로 돌려준다)."""
    need = len(opage) - len(enc)
    if need <= 0:
        return bytes(enc)
    enc, used = _upgrade_spaces(enc, need)              # 칸 수를 안 늘리는 몫 먼저
    need -= used
    if need <= 0:
        return bytes(enc)
    lines = split_lines(enc)
    widths = [cells(l) for l in lines]
    extra = [0] * len(lines)                            # 줄별 전각 공백 개수
    for _ in range(need // 2):
        index = _pick(widths, 1)
        extra[index] += 1
        widths[index] += 1
    out = [l + FULL * extra[i] for i, l in enumerate(lines)]
    if need % 2:                                        # 남는 1바이트 = 반각 공백 하나
        out[_pick(widths, 1)] += HALF
    res = bytes([NEWLINE]).join(out)
    if len(res) != len(opage):                          # 이론상 안 나지만 안전장치
        return bytes(enc) + HALF * need
    return res


def widest(page: bytes) -> int:
    """페이지에서 가장 넓은 줄의 칸 수."""
    return max((cells(l) for l in split_lines(page)), default=0)


def visual_lines(page, box=BOX) -> int:
    """게임이 대화창 폭에서 **알아서 줄을 바꾼 뒤**의 줄 수.

    20칸을 넘는 줄이 곧 결함인 것은 아니다. 한 줄짜리 페이지가 24칸이면 두 줄로
    나뉘어도 대화창(3줄) 안에 들어간다. 진짜 결함은 이렇게 센 줄 수가 ROWS 를
    넘는 페이지다 — 넘친 만큼이 **빈 대화창** 한 장으로 보인다.
    """
    total = 0
    for line in split_lines(page):
        width = cells(line)
        total += max(1, -(-width // box))          # 올림 나눗셈
    return total


def words(page: bytes) -> list:
    """공백·줄바꿈으로 끊은 낱말 목록(구분자는 버린다).

    2·3바이트 글자 안쪽의 0x20/0x0a 는 건드리지 않는다.
    """
    out, start, i = [], 0, 0
    while i < len(page):
        step = _step(page, i)
        if step == 1 and page[i] in (0x20, NEWLINE):
            if i > start:
                out.append(bytes(page[start:i]))
            start = i + 1
        i += step
    if len(page) > start:
        out.append(bytes(page[start:]))
    return out


SENT_END = ("。", "．", ".", "!", "?", "！", "？", "…",
            "」", "』", "）", ")", "〜", ",", "，", "、")
OPEN_MARK = ("「", "『", "（", "(")


# 줄 끝에 오면 어색한 낱말 — 뒤 낱말과 한 덩어리로 읽힌다.
# ("살 수 있는 건 카드가 봉인된 / 돌이야" 처럼 갈라지면 읽기 나쁘다)
DANGLING = frozenset((
    "못", "안", "좀", "더", "덜", "잘", "또", "곷", "막",
    "참", "꿘", "아주", "매우", "너무", "가장", "제일",
    "그", "이", "저", "한", "두", "세", "몇", "무슠", "어떤",
    "모든", "온갖", "각", "새", "옛", "수", "줄", "리", "채",
    "만큼", "내", "번", "온",
))
# 관형형 어미 — 뒤에 꾸밈을 받을 말이 반드시 온다.
DANGLING_TAIL = ("는", "던", "할", "될", "인는")


def _dangles(word: bytes, to_text) -> bool:
    """이 낱말로 줄을 끝내면 뒤 낱말과 갈라져 읽기 나쁜가.

    한글은 JIS 제1수준 한자 슬롯을 빌려 쓰므로 cp932 로 풀면 한자가 나온다.
    그래서 **폰트 역매핑을 넘겨받아** 읽을 수 있는 한글로 바꿔 판단한다.
    """
    text = to_text(word) if to_text else ""
    if not text:
        return False
    if text in DANGLING:
        return True
    if len(text) >= 2 and text.endswith("의"):     # -의 (소유격)
        return True
    return len(text) >= 2 and text.endswith(DANGLING_TAIL)


def _ends_sentence(word: bytes) -> bool:
    """줄을 여기서 끊어도 자연스러운가 — 문장부호로 끝나면 그렇다."""
    try:
        text = word.decode("cp932", "ignore")
    except Exception:                                   # noqa: BLE001
        return False
    return bool(text) and text[-1] in "".join(SENT_END)


def _opens(word: bytes) -> bool:
    try:
        text = word.decode("cp932", "ignore")
    except Exception:                                   # noqa: BLE001
        return False
    return bool(text) and text[-1] in "".join(OPEN_MARK)


def _best_lines(parts, box, rows, orig_breaks, to_text=None):
    """줄바꿈 자리를 **가장 좋게** 고른다(작은 DP).

    좋다는 기준은 세 가지다.
      * 원래 줄바꿈 자리를 그대로 쓰면 가장 좋다(글쓴이의 의도).
      * 문장부호 뒤에서 끊으면 좋다 — "카드가 봉인된 / 돌이야" 같은 갈라짐을 막는다.
      * 줄 길이가 고를수록 좋다.
    """
    n = len(parts)
    widths = [cells(p) for p in parts]

    def span(i, j):                                     # 낱말 i..j-1 을 한 줄로
        return sum(widths[i:j]) + (j - i - 1)

    inf = float("inf")
    dp = [[(inf, None)] * (n + 1) for _ in range(rows + 1)]
    dp[0][0] = (0, None)
    for k in range(1, rows + 1):
        for j in range(1, n + 1):
            best = (inf, None)
            for i in range(j):
                prev = dp[k - 1][i][0]
                if prev == inf:
                    continue
                width = span(i, j)
                if width > box:
                    continue
                cost = prev
                if j < n:                               # 마지막 줄은 여백을 안 따진다
                    cost += (box - width) ** 2
                    cost += 0 if _ends_sentence(parts[j - 1]) else 90
                    cost += 150 if _opens(parts[j - 1]) else 0
                    cost += 200 if _dangles(parts[j - 1], to_text) else 0
                    cost -= 120 if j in orig_breaks else 0
                if cost < best[0]:
                    best = (cost, i)
            dp[k][j] = best
    out = []
    for k in range(1, rows + 1):
        if dp[k][n][0] == inf:
            continue
        lines, j = [], n
        for step in range(k, 0, -1):
            i = dp[step][j][1]
            lines.append(parts[i:j])
            j = i
        out.append((dp[k][n][0], list(reversed(lines))))
    return out


def _join(lines) -> bytes:
    return bytes([NEWLINE]).join(b" ".join(l) for l in lines)


def rewrap(page: bytes, budget: int, box: int = BOX, rows: int = ROWS, to_text=None):
    """**낱말은 그대로 두고 줄바꿈만 다시 잡아** 대화창 안에 넣어 본다.

    20칸을 넘는 줄은 게임이 알아서 나누므로, 두 줄짜리 21칸+21칸 페이지는 화면에서
    네 줄이 되어 대화창(3줄)을 넘는다. 같은 낱말을 세 줄로 다시 나누면 세 줄에
    들어간다 — 글자를 하나도 바꾸지 않고 고칠 수 있다.

    구분자(공백·줄바꿈)를 하나씩만 다시 넣으므로 바이트 수는 그대로다.
    넣지 못하면 None 을 돌려준다.
    """
    authored = [words(l) for l in split_lines(page)]
    authored = [l for l in authored if l]
    if not authored:
        return None
    parts, breaks, seen = [], set(), 0
    for line in authored:
        parts += line
        seen += len(line)
        breaks.add(seen)                                # 원래 줄이 끝나던 자리
    candidates = _best_lines(parts, box, rows, breaks, to_text)
    if not candidates:
        return None
    # ★ 채움까지 넣고 판정해야 한다. 두 줄 19칸+19칸은 그 자체로는 두 줄이지만,
    #   예산을 맞추려 4칸을 채우면 21칸+21칸이 되어 네 줄로 펼쳐진다. 세 줄로
    #   나눠 두면 채움이 들어가도 세 줄에 머문다.
    for _cost, lines in sorted(candidates, key=lambda c: c[0]):
        out = _join(lines)
        if len(out) > budget:
            continue
        if visual_lines(pad_page(out, bytes(budget)), box) <= rows:
            return out
    return None
