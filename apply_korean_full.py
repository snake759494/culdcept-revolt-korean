#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
컬드셉트 리볼트(3DS, 일판) **전체 스토리 대사 + 카드 데이터베이스 + UI** 한국어 패치.

본인의 CULDCEPT.DAT 에서 시나리오 컨테이너(엔트리 1946~1958)의 모든 대사와,
카드 데이터베이스(엔트리 1190: 카드 능력·설명·플레이버 및 UI/시작설정 텍스트)를
찾아 한국어로 교체하고, 필요한 한글 글리프를 폰트(엔트리 1054)에 그려 넣어
패치된 CULDCEPT.DAT 를 씁니다.

게임은 대사 페이지를 텍스트 영역 내 절대 오프셋으로 참조하므로, 각 대화창의
한국어는 원문 페이지의 바이트 길이 이하로 넣고 부족분은 공백으로 채워 모든
오프셋을 보존합니다. 카드 텍스트(1190)도 포인터로 참조되므로 원문 문자열 길이
이하로 제자리 교체합니다(dialogue_ko.json / cards_ko.json 의 번역은 이 한도에
맞춰져 있습니다).

이 툴은 게임 데이터를 포함하지 않습니다 — 한글 글리프는 폰트에서 그려지고,
원문 바이트(아이콘·제어코드 포함)는 전부 본인의 파일에서 읽습니다.
dialogue_ko.json / cards_ko.json 은 한국어 번역만 담습니다(일본어 원문 없음).

사용법:
    python apply_korean_full.py <원본 CULDCEPT.DAT> <출력 CULDCEPT.DAT> [--font TTF]
"""
import argparse
import json
import os
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

from culdcept import dat as datmod, huffman, font as fontmod, pagepad, scen, wansung, cardtext
from opening_ko import UI_KO, SETUP_KO

FONT_ENTRY, UI_ENTRY = 1054, 1190
CONTAINERS = list(range(1946, 1959))
PAD = 0x20
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FONTS = [
    os.path.join(_HERE, "fonts", "NanumSquareNeo-cBd.ttf"),
    r"C:\Windows\Fonts\malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]
_FW = {'!': '！', '?': '？'}


def is_h(c): return 0xAC00 <= ord(c) <= 0xD7A3


def pick_font(explicit):
    if explicit:
        return explicit
    for p in DEFAULT_FONTS:
        if os.path.exists(p):
            return p
    return None


def shrink_container(container, budget):
    """컨테이너가 원래 엔트리 크기를 넘으면 **손대지 않은 섹션까지 다시 압축**한다.

    엔트리가 원래 자리에 안 들어가면 파일 끝으로 밀리는데, 그러면 게임이 옛
    자리를 읽어 원문을 보여 주는 일이 있었다(이슈 #27). 우리 압축기는 게임의
    자체 인코더보다 결과가 작을 때가 많으므로, 번역하지 않은 섹션을 다시 눌러
    번역한 섹션이 커진 만큼을 상쇄한다.
    """
    if len(container) <= budget:
        return container
    sections = scen.parse_sections(container)
    if not sections:
        return container
    for k, (off, ln) in enumerate(sections):
        if not ln or container[off] not in (0x08, 0x0C):
            continue
        blob = container[off:off + ln]
        try:
            dec = huffman.decompress(blob)
            cand = huffman.compress_real(dec, blob[0], effort=3)
        except Exception:                                  # noqa: BLE001
            continue
        if len(cand) < len(blob) and huffman.decompress(cand) == dec:
            container = scen.rebuild_container(container, k, cand)
        if len(container) <= budget:
            break
    return container


def pack(data, typ):
    """엔트리/섹션을 다시 압축한다 — **진짜 압축기를 먼저 쓴다.**

    `huffman.compress()` 는 전부 리터럴로 내보내서 결과가 원본의 3배쯤 된다.
    그러면 엔트리가 원래 자리에 안 들어가 파일 끝으로 밀리는데, 그 상태에서
    게임이 옛 자리를 읽어 원문을 보여 주는 일이 있었다(이슈 #27). 실제로
    2장 시나리오 s3 는 5,592 -> 15,809 바이트로 부풀어 있었다.
    compress_real() 은 같은 섹션을 5,608 바이트로 만든다 — 원본과 거의 같다.
    """
    # 0x0d/0x8d(레인지 코더)는 다시 압축할 방법이 없다. 그렇다고 typ 을 그대로
    # 넘기면 compress_real 이 거부해서 **전량 리터럴**로 떨어지는데, 그러면
    # 엔트리가 4~5배로 부풀어(e1669: 61,524 -> 299,407) 원래 자리에 못 들어가고
    # 파일 끝으로 밀린다. 게임은 타입 바이트로 코덱을 고르므로 huffman(0x08)로
    # 바꿔 써도 정상이다 — 진짜 압축기를 태우면 대개 원래 자리에 들어간다
    # (e1601: 158,396 -> 35,591 <= 슬롯 37,961).
    ctyp = typ if typ in (0x08, 0x0C) else 0x08
    try:
        out = huffman.compress_real(data, ctyp, effort=3)
        if huffman.decompress(out) == data:
            return out
    except Exception:                                      # noqa: BLE001
        pass
    return huffman.compress(data, typ=ctyp)                # 안 되면 원래 방식


def main():
    ap = argparse.ArgumentParser(description="컬드셉트 리볼트 전체 대사 한국어 패치")
    ap.add_argument("infile")
    ap.add_argument("outfile")
    ap.add_argument("--font", default=None)
    args = ap.parse_args()

    ttf = pick_font(args.font)
    if not ttf or not os.path.exists(ttf):
        sys.exit("한글 폰트를 찾지 못했습니다. --font <TTF 경로> 로 지정하세요")

    ko = json.load(open(os.path.join(_HERE, "dialogue_ko.json"), encoding="utf-8"))
    cards_path = os.path.join(_HERE, "cards_ko.json")
    cards_ko = json.load(open(cards_path, encoding="utf-8")) if os.path.exists(cards_path) else {}
    block_path = os.path.join(_HERE, "block_ko.json")
    block_ko = json.load(open(block_path, encoding="utf-8")) if os.path.exists(block_path) else {}
    missed_path = os.path.join(_HERE, "missed_ko.json")
    missed_ko = json.load(open(missed_path, encoding="utf-8")) if os.path.exists(missed_path) else {}
    extra_path = os.path.join(_HERE, "cards_extra_ko.json")
    cards_extra = json.load(open(extra_path, encoding="utf-8")) if os.path.exists(extra_path) else {}
    d = datmod.Dat(open(args.infile, "rb").read())
    cmap = fontmod.parse_cmap(huffman.decompress(d.entry(FONT_ENTRY)))

    # 폰트: 완성형 2350 + 번역/카드/블록대사/UI/설정에 쓰인 2350 밖 음절
    used = {c for ev in ko.values() for pages in ev.values() for p in pages for c in p if is_h(c)}
    used |= {c for t in list(UI_KO.values()) + list(SETUP_KO.values()) for c in t if is_h(c)}
    used |= {c for v in cards_ko.values() for c in v if is_h(c)}
    used |= {c for evs in block_ko.values() for pages in evs.values() for p in pages for c in p if is_h(c)}
    used |= {c for mm in missed_ko.values() for pages in mm.values() for p in pages for c in p if is_h(c)}
    extra = [c for c in sorted(used) if c not in set(wansung.WANSUNG_2350)]
    syll2code = wansung.build_fixed_map(cmap, extra=extra)
    print("한글 %d자(완성형 2350%s) 폰트 주입" % (len(syll2code), (" + %d" % len(extra)) if extra else ""))

    def encp(text):
        out = bytearray(); i = 0
        while i < len(text):
            if text[i] == "\n": out.append(0x0a); i += 1
            elif text[i:i+3] == "{N}": out += bytes([0x03, 0x30, 0x2f]); i += 3
            else:
                out += wansung.encode_char(text[i], syll2code); i += 1
        return bytes(out)

    trunc_warnings = []
    trunc_src = [""]
    wide_warnings = []

    def trunc(bs, limit):
        # 잘리면 화면에서 글자가 사라진다. 조용히 넘어가면 번역을 고칠 때
        # 무엇이 잘렸는지 알 수 없으므로 반드시 알린다.
        if len(bs) > limit:
            trunc_warnings.append((len(bs), limit, trunc_src[0], bytes(bs[:limit])))
        if len(bs) <= limit: return bs
        out = bytearray(); i = 0
        while i < len(bs):
            step = 3 if bs[i] == 0x03 else (2 if 0x81 <= bs[i] <= 0xfc and i+1 < len(bs) else 1)
            if len(out)+step > limit: break
            out += bs[i:i+step]; i += step
        return bytes(out)

    def pad_page(enc, opage):
        """페이지를 원본 바이트 길이에 맞춘다 — 채움은 **전각 공백**.

        예전에는 반각 공백(0x20)으로 각 줄을 원본 줄의 **바이트 길이**까지
        채웠다. 근거는 "공백은 1바이트니 2바이트 글자보다 좁다"였는데, 이
        폰트는 고정폭이라 **반각 공백도 한 칸을 그대로 차지한다**. 그래서
        40바이트(20칸) 원문 줄 자리에 30바이트 한글(16칸)을 넣고 10바이트를
        반각 공백으로 채우면 26칸이 되어 대화창을 넘고, 넘친 만큼이 빈
        대화창으로 보였다(이슈 #24 재발 · #29). 전각 공백은 2바이트에 한 칸이라
        원문과 밀도가 같다. 자세한 건 culdcept/pagepad.py 참고.
        """
        out = pagepad.pad_page(enc, opage)
        # 원본보다 넓어진 줄은 대화창을 넘겨 빈 페이지를 만든다 — 반드시 알린다.
        was, now = pagepad.widest(opage), pagepad.widest(out)
        if now > was:
            wide_warnings.append((now, was, trunc_src[0]))
        return out

    def pad_fill(view, tokens, syll2code, enc, target):
        """번역 결과를 원문 바이트 길이에 맞춰 **공백(0x20)** 으로 채운다.

        널이 아니라 공백을 쓰는 이유: 게임은 카드 레코드의 필드를 널로 구분된
        순서대로 읽으므로, 널을 더 넣으면 빈 세그먼트가 생겨 뒤 필드가 밀린다.

        채우는 위치가 중요하다. 문자열이 제어코드로 끝나는데 공백을 맨 뒤에 붙이면,
        예/아니오 버튼을 화면 밖으로 밀어낸다. 그래서 뒤쪽 12자 안에 줄바꿈이나
        토큰이 있으면 **그 앞에** 채워 넣는다(눈에 보이지 않는 자리).
        """
        need = target - len(enc)
        if need <= 0:
            return enc
        cut = None
        # 뒤쪽 12자 안의 **줄바꿈**만 대상으로 하고, 그마저도 뒤에 실제 글자가
        # 없을 때만 그 앞에 채운다. 토큰까지 대상으로 삼으면 '강타[   (아이콘)]'
        # 처럼 괄호 안에 공백이 끼어 보기 나쁘다.
        for i in range(max(0, len(view) - 12), len(view)):
            if view[i] == chr(10):
                tail = view[i:]
                if not any("가" <= c <= "힣" for c in tail):
                    cut = i
                    break
        if cut is None:                    # 평범한 문장 → 그냥 뒤에 채움
            return enc + bytes([PAD]) * need
        padded = view[:cut] + " " * need + view[cut:]
        out = cardtext.encode(padded, tokens, syll2code)
        if len(out) == target:
            return out
        return enc + bytes([PAD]) * need      # 길이가 안 맞으면 안전하게 원래 방식

    def fit_page(view, tokens, budget):
        """예산 초과 시: 끝쪽 공백부터 제거 → 그래도 넘으면 안전 절단(문자경계 보존)."""
        enc = cardtext.encode(view, tokens, syll2code)
        if len(enc) <= budget:
            return enc
        s = list(view)
        while len(cardtext.encode("".join(s), tokens, syll2code)) > budget:
            pos = -1
            for j in range(len(s) - 1, -1, -1):
                if s[j] == " ": pos = j; break
            if pos < 0: break
            del s[pos]
        enc = cardtext.encode("".join(s), tokens, syll2code)
        return enc if len(enc) <= budget else trunc(enc, budget)

    def apply_missed(dec, mm, label=""):
        """find_text_region 이 놓친 중간 텍스트 세그먼트를 오프셋 기준 제자리 교체.
        각 세그먼트를 페이지(0x07) 단위로 원문 바이트 길이 이하 교체(0x20 패딩)해
        모든 페이지 오프셋을 보존한다. mm = {offset(str): [korean_page, ...]}."""
        if not mm:
            return dec
        dec = bytearray(dec)
        for off_str, pages in mm.items():
            off = int(off_str)
            end = dec.find(b"\x00", off)
            if end < 0:
                continue
            seg = bytes(dec[off:end])
            opages = seg.split(b"\x07")
            newseg = bytearray()
            for pi, opage in enumerate(opages):
                if pi < len(pages) and pages[pi] != "":
                    _, tokens = cardtext.tokenize(opage)
                    trunc_src[0] = "missed_ko %s o%s.p%d" % (label, off_str, pi)
                    enc = fit_page(pages[pi], tokens, len(opage))
                    newseg += pad_page(enc, opage)
                else:
                    newseg += opage
                if pi < len(opages) - 1:
                    newseg += b"\x07"
            if len(newseg) < len(seg):
                newseg += bytes([PAD]) * (len(seg) - len(newseg))
            if len(newseg) == len(seg):
                dec[off:end] = newseg
        return bytes(dec)

    # 폰트 주입 — 4bpp(대사·카드 패널) + 1bpp(소형 UI/HUD·스톡정보·카드상세 헤더) 모든 섹션
    # 글리프별로 잉크가 셀(w x h)에 들어가는 최대 포인트 크기를 찾아 렌더.
    # (셀 크기 그대로 렌더하면 일부 음절의 잉크가 셀보다 1~3px 커서, 중앙정렬 시
    #  위가 잘려 '목'이 '복'처럼 보이는 문제가 있었음)
    fontbuf = bytearray(huffman.decompress(d.entry(FONT_ENTRY)))
    sizes = fontmod.find_all_sections(fontbuf)
    fcache = {}
    _meas = ImageDraw.Draw(Image.new("L", (64, 64)))

    def render_cell(s, w, h):
        size = h
        while size >= 6:
            px = fcache.get(size)
            if px is None:
                px = ImageFont.truetype(ttf, size); fcache[size] = px
            bb = _meas.textbbox((0, 0), s, font=px)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            if tw <= w and th <= h:
                break
            size -= 1
        img = Image.new("L", (w, h), 0)
        dr = ImageDraw.Draw(img)
        dr.text(((w - tw) // 2 - bb[0], (h - th) // 2 - bb[1]), s, fill=255, font=px)
        return img

    for (soff, bpg, w, h, bpp) in sizes:
        for s, code in syll2code.items():
            img = render_cell(s, w, h)
            glyph = fontmod.render_a4(img, w, h) if bpp == 4 else fontmod.render_1bpp(img, w, h)
            fontmod.write_glyph(fontbuf, soff, bpg, cmap[code], glyph)
    new_font = pack(bytes(fontbuf), d.entry_type(FONT_ENTRY))
    assert huffman.decompress(new_font) == bytes(fontbuf)

    # 대사 주입(컨테이너 1946~1958, 페이지 길이보존)
    n_ev = 0
    for idx in CONTAINERS:
        ent = d.entry(idx)
        secs = scen.parse_sections(ent)
        if not secs:
            continue
        # 비압축(raw) 섹션의 미번역(예: 1947.s2 퀘스트 제목·노드명) — 제자리 교체(공백 패딩)
        ent = bytearray(ent)
        for k, (off, ln) in enumerate(secs):
            mm = missed_ko.get(f"{idx}.r{k}", {})
            if not mm or not ln or off >= len(ent) or ent[off] in (0x08, 0x0c, 0x0d, 0x8d):
                continue
            for off_s, pages in mm.items():
                so = off + int(off_s)
                end = ent.find(b"\x00", so, off + ln)
                if end < 0:
                    continue
                bud = end - so
                _, tokens = cardtext.tokenize(bytes(ent[so:end]))
                trunc_src[0] = "%d.r%d o%s" % (idx, k, off_s)
                enc = fit_page(pages[0], tokens, bud)
                # 공백(0x20)으로 채운다 — 널을 채우면 빈 세그먼트가 생겨
                # [제목][설명][노드명…] 순서로 읽는 퀘스트 데이터가 밀린다(이슈 #3).
                ent[so:end] = enc + bytes([PAD]) * (bud - len(enc))
        ent = bytes(ent)
        cont = ent
        for k, (off, ln) in enumerate(secs):
            if not ln or ent[off] not in (0x08, 0x0c):
                continue
            try:
                dec = huffman.decompress(ent[off:off+ln])
            except Exception:
                continue
            ts, events = scen.find_text_region(dec)          # 끝 영역(원본 기준) 확정
            mm = missed_ko.get(f"{idx}.s{k}", {})
            if ts is None and not mm:
                continue
            dec = apply_missed(dec, mm, f"{idx}.s{k}")        # 놓친 중간 세그먼트 제자리 교체(끝 영역 유무 무관)
            new_dec = dec                                     # 기본값: missed 만 반영
            if ts is not None:
                evmap = ko.get(f"e{idx}_s{k}", {})
                region = bytearray()
                for ei, ev in enumerate(events):
                    opages = ev.split(b"\x07")
                    kp = evmap.get(str(ei))
                    for pi, opage in enumerate(opages):
                        if kp is not None and pi < len(kp) and kp[pi] != "":
                            enc = encp(kp[pi])
                            trunc_src[0] = "e%d_s%d.e%d.p%d" % (idx, k, ei, pi)
                            if len(enc) > len(opage):
                                enc = trunc(enc, len(opage))
                            region += pad_page(enc, opage)
                        else:
                            region += opage
                        if pi < len(opages) - 1:
                            region += b"\x07"
                    region += b"\x00"
                    n_ev += 1
                if len(region) == len(dec) - ts:             # 끝 영역 재조립이 유효하면 결합
                    new_dec = dec[:ts] + bytes(region)
            if new_dec == huffman.decompress(ent[off:off+ln]):
                continue                                      # 변경 없음 → 건너뜀
            new_sec = pack(new_dec, ent[off])
            assert huffman.decompress(new_sec) == new_dec
            cont = scen.rebuild_container(cont, k, new_sec)
        cont = shrink_container(cont, len(d.entry(idx)))
        d.replace_entry(idx, cont)

    # 카드 데이터베이스 + UI + 시작설정(엔트리 1190)
    ui = bytearray(huffman.decompress(d.entry(UI_ENTRY)))
    # 카드 텍스트: 본인 파일에서 문자열을 열거·중복제거한 순서(=인덱스)로 제자리 교체
    n_card = 0
    _secs = scen.parse_sections(bytes(ui)) or []
    s3_lo, s3_hi = (_secs[3][0], _secs[3][0] + _secs[3][1]) if len(_secs) > 3 else (0, 0)

    if cards_ko:
        uniq = cardtext.enum_unique(ui)
        for idx, (raw, offs) in enumerate(uniq.items()):
            view = cards_ko.get(str(idx))
            if view is None:
                continue
            _, tokens = cardtext.tokenize(raw)
            enc = cardtext.encode(view, tokens, syll2code)
            if len(enc) > len(raw):
                trunc_src[0] = "cards_ko[%d] %r" % (idx, view[:28])
                enc = trunc(enc, len(raw))
            # 남는 자리는 **공백(0x20)** 으로 채운다 — 널(0x00)이 아니다.
            # 널로 채우면 문자열이 일찍 끝나 **빈 세그먼트가 새로 생긴다**. 게임은
            # 카드 레코드의 필드(이름·능력치·영문명·플레이버)를 널로 구분된 순서대로
            # 읽으므로, 빈 세그먼트가 끼면 뒤 필드가 전부 밀려 설명문이 비어 보인다
            # (이슈 #3). 원본의 널 개수를 그대로 유지해야 한다.
            #
            # 다만 문자열이 제어코드로 끝나면 공백을 뒤에 붙일 때 그 공백이 한 줄로
            # 렌더돼 예/아니오 버튼을 밀어낸다(이슈 #1). 그래서 pad_fill() 이
            # **제어코드 앞쪽에** 채워 넣는다.
            body = pad_fill(view, tokens, syll2code, enc, len(raw))
            # UI 섹션(s3)의 **토큰·줄바꿈 없는 짧은 라벨**은 널로 채운다.
            # 이런 라벨은 다른 문장 안에 그대로 끼워 넣어지므로("맵이나 <셉터> 등"),
            # 뒤에 붙은 공백이 고정폭 폰트에서 글자 칸만큼 벌어져 보인다(이슈 #24).
            # s3 은 오프셋 참조라 널을 넣어도 안전하다 — UI_KO 가 이미 같은 방식으로
            # "マップ"->"맵" 등을 넣고 있고 화면에서 정상 동작한다(같은 줄의 "맵"은
            # 벌어지지 않고 "셉터"만 벌어진 것이 그 증거).
            body_nul = enc + b"\x00" * (len(raw) - len(enc))
            plain = not tokens and bytes([10]) not in raw
            for off in offs:
                inline = plain and s3_lo <= off < s3_hi
                ui[off:off+len(raw)] = body_nul if inline else body
                n_card += 1

    # enum_unique 필터가 놓친 문자열(오프셋 기준). cards_extra_ko.json 참고.
    n_extra = 0
    for off_s, spec in (cards_extra or {}).items():
        if off_s.startswith("_"):
            continue
        off = int(off_s)
        end = ui.find(b"\x00", off)                      # 원문은 널 종료
        if end < 0:
            continue
        raw = bytes(ui[off:end])
        # 안전장치: 기록된 길이와 다르면 오프셋이 틀린 것이므로 건드리지 않는다.
        # (틀린 오프셋에 쓰면 포인터 테이블 등을 덮어써 파일이 깨진다.)
        if len(raw) != spec["len"]:
            print(f"  ! cards_extra 오프셋 {off} 길이 불일치"
                  f"(기대 {spec['len']}, 실제 {len(raw)}) — 건너뜀")
            continue
        _, tokens = cardtext.tokenize(raw)
        enc = cardtext.encode(spec["ko"], tokens, syll2code)
        if len(enc) > len(raw):
            trunc_src[0] = "cards_extra[%s]" % off_s
            enc = trunc(enc, len(raw))
        ui[off:off+len(raw)] = pad_fill(spec["ko"], tokens, syll2code, enc, len(raw))
        n_extra += 1
    def kob(t): return b"".join(wansung.encode_char(c, syll2code) for c in t)
    for jp, k in UI_KO.items():
        nb = jp.encode("shift_jis"); kb = kob(k); p = 0
        while True:
            i = ui.find(nb, p)
            if i < 0: break
            if (i == 0 or ui[i-1] == 0) and (i+len(nb) >= len(ui) or ui[i+len(nb)] == 0):
                ui[i:i+len(nb)] = kb + b"\x00"*(len(nb)-len(kb))
            p = i + 1
    for jp, k in SETUP_KO.items():
        nb = jp.encode("shift_jis"); kb = kob(k); p = 0
        while True:
            i = ui.find(nb, p)
            if i < 0: break
            if i == 0 or ui[i-1] in (0, 0x0c):
                en = ui.find(b"\x00", i)
                if en < 0: en = len(ui)
                if len(kb) <= en - i:
                    ui[i:en] = kb + b"\x00"*(en-i-len(kb))
            p = i + 1
    ui = bytearray(apply_missed(bytes(ui), missed_ko.get(str(UI_ENTRY), {})))
    new_ui = pack(bytes(ui), d.entry_type(UI_ENTRY))
    assert huffman.decompress(new_ui) == bytes(ui)

    # 캐릭터/전투 대사 블록(엔트리 1849~1945, 직접압축 블롭, 페이지 길이보존)
    # + missed_ko 에만 있는 기타 블롭 엔트리도 함께 처리
    n_blk = 0
    blob_keys = set(block_ko) | {k for k in missed_ko
                                 if "." not in k and int(k) != UI_ENTRY}
    for entry_s in sorted(blob_keys, key=int):
        evs = block_ko.get(entry_s, {})
        idx = int(entry_s)
        ent = d.entry(idx)
        if not ent or ent[0] not in (0x08, 0x0c):
            continue
        try:
            dec = huffman.decompress(ent)
        except Exception:
            continue
        ts, events = scen.find_text_region(dec)
        mm = missed_ko.get(str(idx), {})
        if ts is None and not mm:
            continue
        dec = apply_missed(dec, mm, str(idx))   # 놓친 중간 세그먼트(예: 1849 튜토리얼)
        if ts is None:                # 끝 영역 없는 블롭: missed 만 반영
            if dec != huffman.decompress(ent):
                new_sec = pack(dec, ent[0])
                assert huffman.decompress(new_sec) == dec
                d.replace_entry(idx, new_sec)
            continue
        region = bytearray()
        for ei, ev in enumerate(events):
            opages = ev.split(b"\x07")
            kp = evs.get(str(ei))
            for pi, opage in enumerate(opages):
                if kp is not None and pi < len(kp) and kp[pi] != "":
                    _, tokens = cardtext.tokenize(opage)
                    trunc_src[0] = "block e%d.e%d.p%d" % (idx, ei, pi)
                    enc = fit_page(kp[pi], tokens, len(opage))
                    region += pad_page(enc, opage)
                else:
                    region += opage
                if pi < len(opages) - 1:
                    region += b"\x07"
            region += b"\x00"
            if kp is not None:
                n_blk += 1
        if len(region) != len(dec) - ts:
            continue
        new_dec = dec[:ts] + bytes(region)
        new_sec = pack(new_dec, ent[0])
        assert huffman.decompress(new_sec) == new_dec
        d.replace_entry(idx, new_sec)

    if trunc_warnings:
        worst = max(w - l for w, l, _, _ in trunc_warnings)
        print("  ! 길이 초과로 잘린 문자열 %d개 (최대 %d바이트 초과)"
              % (len(trunc_warnings), worst))
        # 무엇이 잘렸는지 모르면 고칠 수 없다. 어디서 몇 바이트 넘쳤는지 함께 남긴다.
        for w, l, src, cut in trunc_warnings[:40]:
            print("      +%d  %s" % (w - l, src))
    if wide_warnings:
        print("  ! 원본보다 넓어진 줄 %d개 (대화창 넘침·빈 페이지 위험)"
              % len(wide_warnings))
        for now, was, src in sorted(wide_warnings, reverse=True)[:40]:
            print("      %d칸 > 원본 %d칸  %s" % (now, was, src))
    d.replace_entry(FONT_ENTRY, new_font)
    d.replace_entry(UI_ENTRY, new_ui)
    open(args.outfile, "wb").write(d.build())
    print("스토리대사 %d + 카드 %d(+보정 %d) + 캐릭터대사 %d + UI/설정 교체 완료 -> %s"
          % (n_ev, n_card, n_extra, n_blk, args.outfile))


if __name__ == "__main__":
    main()
