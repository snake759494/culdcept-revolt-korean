# -*- coding: utf-8 -*-
"""DLC 리소스 파일(.dla/.dlb/.dld/.dlj/.dlm/.dlq) 읽기·쓰기.

구조
----
  0x00 u32 LE  무결성 값 = zlib CRC-32 over (복호화된 버퍼)[4:size]
  0x04 u32 LE  파일 크기
  0x09 u8      암호화 플래그(1이면 페이로드가 암호화됨)
  0x10~        Shift-JIS 제목, NUL 종료, 실질 26바이트 이내
  0x2B u8      페이로드 시작 오프셋(0이면 0x80)
  페이로드     LCG 스트림 암호. 복호화하면 게임 자체 컨테이너 또는 평문 텍스트.

★ 파일을 고치면 반드시 fix_crc() 로 0x00 을 갱신해야 한다. 갱신하지 않으면 게임이
  리소스를 거부하고, 그 결과 **DLC 가 통째로 사라진 것처럼** 보인다(이슈 #19~#21).
  제목을 유효한 일본어로 바꿔도 똑같이 거부되므로 인코딩 문제로 오인하기 쉽다.

게임 코드 근거(update_code.bin): 검증기 vaddr 0x002764d0, LCG 0x0026d41c,
CRC 0x0026e2cc, 제목 Shift-JIS 검사기 0x00120050.
"""
import struct
import zlib

M = 0xFFFFFFFF
LCG_ADD = 0x35733573
TITLE_OFF, TITLE_MAX = 0x10, 26      # NUL 포함 0x1B 바이트 자리, 실질 26바이트
PAYLOAD_OFF_FIELD = 0x2B
PAD = 0x20                            # 남는 자리는 공백. 널을 쓰면 문자열이 갈라진다.


def payload_off(buf) -> int:
    return buf[PAYLOAD_OFF_FIELD] or 0x80


def _crypt(buf: bytearray, off: int, nbytes: int, decrypt: bool) -> None:
    # 헤더가 어긋난 파일(합성 테스트 데이터 등)에서 버퍼 밖을 건드리지 않도록 자른다.
    nbytes = max(0, min(nbytes, len(buf) - off))
    x = 0
    for i in range(nbytes >> 2):
        p = off + i * 4
        x = (x * 5 + LCG_ADD) & M
        w = struct.unpack_from("<I", buf, p)[0]
        struct.pack_into("<I", buf, p, (w - x) & M if decrypt else (w + x) & M)


def decrypt(raw: bytes) -> bytes:
    """게임이 CRC 직전에 하는 제자리 복호화(암호화 플래그도 0으로) 재현."""
    b = bytearray(raw)
    size = struct.unpack_from("<I", b, 4)[0]
    if b[9]:
        _crypt(b, payload_off(b), size - payload_off(b), True)
        b[9] = 0
    return bytes(b)


def encrypt(plain: bytes) -> bytes:
    """decrypt() 의 역. 암호화 플래그를 되살리고 페이로드를 다시 암호화한다."""
    b = bytearray(plain)
    size = struct.unpack_from("<I", b, 4)[0]
    b[9] = 1
    _crypt(b, payload_off(b), size - payload_off(b), False)
    return bytes(b)


def compute_crc(raw: bytes) -> int:
    size = struct.unpack_from("<I", raw, 4)[0]
    return zlib.crc32(decrypt(raw)[4:size]) & M


def fix_crc(raw: bytes) -> bytes:
    b = bytearray(raw)
    struct.pack_into("<I", b, 0, compute_crc(bytes(b)))
    return bytes(b)


def title_ok(raw: bytes, limit: int = 0x1C) -> bool:
    """게임의 Shift-JIS 제목 검사기(vaddr 0x00120050)를 그대로 재현."""
    p, n = TITLE_OFF, 0
    while True:
        c = raw[p]
        p += 1
        if c == 0:
            return True
        if c < 0x20:
            return False
        if c < 0x80:
            n += 1
        else:
            if not (0x81 <= c <= 0x9F or 0xE0 <= c <= 0xFC):
                return False
            t = raw[p]
            p += 1
            if not (0x40 <= t <= 0xFC) or t == 0x7F:
                return False
            n += 2
        if n >= limit:
            return False


def accepted(raw: bytes) -> bool:
    """게임이 이 파일을 받아들일지 판정."""
    return title_ok(raw) and compute_crc(raw) == struct.unpack_from("<I", raw, 0)[0]


def _has_jp(seg: bytes) -> bool:
    i = 0
    while i < len(seg) - 1:
        c = seg[i]
        if 0x81 <= c <= 0x9F or 0xE0 <= c <= 0xFC:
            try:
                seg[i:i + 2].decode("cp932")
                return True
            except UnicodeDecodeError:
                pass
            i += 2
        else:
            i += 1
    return False


def enum_strings(raw: bytes, minlen: int = 2):
    """복호화된 페이로드에서 널 종료 일본어 문자열을 (오프셋, 바이트)로 열거."""
    plain = decrypt(raw)
    size = struct.unpack_from("<I", plain, 4)[0]
    start = payload_off(plain)
    out = []
    cur = start
    for i in range(start, min(size, len(plain))):
        if plain[i] != 0:
            continue
        seg = plain[cur:i]
        if len(seg) >= minlen and _has_jp(seg):
            try:
                seg.decode("cp932")
                out.append((cur, bytes(seg)))
            except UnicodeDecodeError:
                pass
        cur = i + 1
    return out


def replace_strings(raw: bytes, edits: dict) -> bytes:
    """edits = {오프셋: 새 바이트열}. 원문 길이 이하만 허용하고 공백으로 채운다.

    널을 채우면 문자열이 하나 더 생겨 뒤 필드가 밀린다 — 본편 DAT 과 같은 규칙이다.
    """
    b = bytearray(decrypt(raw))
    for off, new in edits.items():
        end = b.index(0, off)
        room = end - off
        if len(new) > room:
            raise ValueError("문자열이 너무 깁니다: %d > %d (오프셋 0x%x)" % (len(new), room, off))
        b[off:end] = new + bytes([PAD]) * (room - len(new))
    return fix_crc(encrypt(bytes(b)))
