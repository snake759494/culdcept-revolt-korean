# -*- coding: utf-8 -*-
"""BLZ (backwards LZSS) 해제 — 3DS/NDS 실행코드(.code) 압축.

파일 끝 8바이트가 푸터:
    u32 @ len-8 : (헤더크기 hdr_len << 24) | 압축영역크기 enc_len
    u32 @ len-4 : 압축 해제로 늘어나는 크기 inc_len (0이면 비압축)

레이아웃: [비압축 앞부분 dec_len][압축영역 enc_len (끝 hdr_len 은 푸터)]
압축 스트림은 **뒤에서 앞으로** 읽고 쓴다.
"""
import struct


def decompress(data: bytes) -> bytes:
    pak = bytes(data)
    n = len(pak)
    inc_len = struct.unpack_from('<I', pak, n - 4)[0]
    if inc_len == 0:
        return pak                                   # 비압축
    hdr_and_enc = struct.unpack_from('<I', pak, n - 8)[0]
    hdr_len = hdr_and_enc >> 24
    enc_len = hdr_and_enc & 0x00FFFFFF
    dec_len = n - enc_len                            # 비압축 앞부분 길이
    pak_len = enc_len - hdr_len                      # 실제 압축 스트림 길이
    raw_len = n + inc_len                            # 최종 크기

    raw = bytearray(raw_len)
    raw[:dec_len] = pak[:dec_len]                    # 앞부분 그대로 복사

    p = dec_len + pak_len                            # 읽기 포인터(감소)
    r = raw_len                                      # 쓰기 포인터(감소)
    p_end = dec_len
    r_end = dec_len

    while r > r_end:
        p -= 1
        flags = pak[p]
        for _ in range(8):
            if p <= p_end:
                break
            if flags & 0x80:
                p -= 1; hi = pak[p]
                p -= 1; lo = pak[p]
                v = (hi << 8) | lo
                ln = (v >> 12) + 3
                pos = (v & 0x0FFF) + 3
                for _ in range(ln):
                    r -= 1
                    raw[r] = raw[r + pos]
            else:
                p -= 1
                r -= 1
                raw[r] = pak[p]
            flags = (flags << 1) & 0xFF
            if r <= r_end:
                break
    return bytes(raw)
