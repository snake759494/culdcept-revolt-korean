# -*- coding: utf-8 -*-
"""빌드된 DAT 안에서 **실제로 들어간 문장**을 찾아 그대로 보여 준다.

번역 JSON 에 뭐라고 적혀 있는지와, 게임 파일에 최종적으로 무엇이 들어갔는지는
다른 얘기다. 페이지 바이트 예산이 모자라면 빌더가 공백부터 지우기 때문에,
JSON 에는 "백작에겐 원한이" 라고 있어도 파일에는 "백작에겐원한이" 가 들어갈 수 있다.
제보에 답하기 전에 **파일 쪽**을 이걸로 확인한다.

    python 화면문장확인.py <빌드한.DAT> "찾을 한국어" [더 찾을 것 …]

찾은 자리의 앞뒤를 함께 보여 주므로 공백이 살아 있는지 눈으로 확인할 수 있다.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "_scratch")
from culdcept import huffman, scen                       # noqa: E402
from culdcept.dat import Dat                             # noqa: E402
from kotool import maps, encode, decode                  # noqa: E402

CONTEXT = 70


def sections(blob):
    """엔트리를 풀어 (이름, 바이트) 목록으로. 컨테이너면 섹션까지 펼친다."""
    try:
        blob = huffman.decompress(blob)
    except Exception:                                     # noqa: BLE001
        pass
    out = [("", blob)]
    try:
        secs = scen.parse_sections(blob) or []
    except Exception:                                     # noqa: BLE001
        secs = []
    for k, (off, ln) in enumerate(secs):
        if not ln or off + ln > len(blob):
            continue
        part = blob[off:off + ln]
        try:
            part = huffman.decompress(part)
        except Exception:                                 # noqa: BLE001
            pass
        out.append((".s%d" % k, part))
    return out


def main():
    path, words = sys.argv[1], sys.argv[2:]
    if not words:
        sys.exit(__doc__)
    syll, rev = maps(path)
    needles = [(w, encode(w, syll)) for w in words]
    dat = Dat(open(path, "rb").read())
    hits = {w: 0 for w in words}
    for index in range(dat.count):
        try:
            entry = dat.entry(index)
        except Exception:                                 # noqa: BLE001
            continue
        if not entry:
            continue
        for tag, blob in sections(entry):
            for word, needle in needles:
                start = 0
                while True:
                    at = blob.find(needle, start)
                    if at < 0:
                        break
                    hits[word] += 1
                    lo, hi = max(0, at - CONTEXT), at + len(needle) + CONTEXT
                    print("e%d%s +%d\n    %s\n" % (index, tag, at,
                                                   decode(blob[lo:hi], rev)))
                    start = at + 1
    print("-" * 60)
    for word in words:
        print("%-24s %d군데" % (word, hits[word]))


if __name__ == "__main__":
    main()
