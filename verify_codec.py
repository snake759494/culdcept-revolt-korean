#!/usr/bin/env python3
"""타입 0x08/0x0c 코덱 컴프레서 검증 도구.

  python verify_codec.py dlq  <파일.dlq ...>       # .dlq 섹션 재압축 크기 비교
  python verify_codec.py dat  <CULDCEPT.DAT> [n]   # DAT 엔트리 n개 표본 비교
  python verify_codec.py blocks <파일.dlq ...>     # 원본 인코더의 블록 구조 덤프
  python verify_codec.py reenc <파일.dlq ...>      # 원본 심볼열 그대로 재인코딩

`reenc` 는 테이블 인코딩만 따로 검증한다. LZ 파스를 빼고 원본이 고른 심볼열을
그대로 다시 써서 원본 크기 이하가 나오면 테이블 인코더가 원본과 동등하다는 뜻.

성공 기준: 모든 섹션이 왕복 무손실이고 재압축 크기 <= 원본 크기.
"""
import glob
import struct
import sys
import time

from culdcept import dlcres, huffman, scen
from culdcept.huffman import MASK, _BR, _BW, _Huff, _emit_varint, clz32, parse_varint


# --------------------------------------------------------- 계측 해제기 ----
# decompress() 와 같은 로직인데, 블록/테이블/심볼열을 전부 기록한다.
def _read_lengths_direct(br, nsym, nbits, special_pos, log):
    count = br.getbits(nbits)
    log['count'] = count
    if count == 0:
        s = br.getbits(nbits)
        log['degenerate'] = True
        log['single'] = s
        return None, s
    log['degenerate'] = False
    codelen = [0] * max(nsym, count + 40)
    i = 0
    log['skips'] = []
    while i < count:
        t = br.acc >> 29
        if t < 7:
            length = t
            br.consume(3)
        else:
            k = clz32((~((br.acc << 3) & MASK)) & MASK)
            length = 7 + k
            br.consume(length - 3)
        codelen[i] = length
        i += 1
        if i == special_pos:
            r = br.getbits(2)
            log['skips'].append((i, r))
            if r:
                end = r + i
                while i < end:
                    codelen[i] = 0
                    i += 1
    return codelen[:max(nsym, i)], None


def _read_litlen(br, log):
    cl_log = {}
    cl_len, cl_single = _read_lengths_direct(br, 19, 5, 3, cl_log)
    log['cl'] = cl_log
    log['cl_len'] = cl_len
    cl = _Huff(single=cl_single) if cl_single is not None else _Huff(cl_len)
    count = br.getbits(9)
    log['ll_count'] = count
    if count == 0:
        return _Huff(single=br.getbits(9))
    out = []
    while len(out) < count:
        s = cl.decode(br)
        if s > 2:
            out.append(s - 2)
        elif s == 0:
            out.append(0)
        elif s == 1:
            out.extend([0] * (3 + br.getbits(4)))
        else:
            out.extend([0] * (0x14 + br.getbits(9)))
    log['ll_lengths'] = out
    return _Huff(out)


def decompress_instr(entry):
    """(데이터, 블록기록들) 반환. 블록기록에 심볼열(syms)이 그대로 들어있다."""
    typ = entry[0]
    d = bytes(entry) + b'\x00' * 8
    window = 0x10 if typ == 0x0c else 0x0d
    size, pos = parse_varint(d, 1)
    br = _BR(d, pos)
    if pos & 1:
        br.acc = (d[pos] << 8) & MASK
        br.pos = pos + 1
        br.cnt = 8
    br.consume(16)
    out = bytearray()
    blocks = []
    dist_nsym = window + 1
    dist_nbits = (window + 1 - 10) & 5
    bits = lambda: br.pos * 8 - (br.cnt + 16)
    while len(out) < size:
        blog = {}
        b0 = bits()
        blog['r8'] = br.getbits(16)
        litlen = _read_litlen(br, blog)
        dlog = {}
        dl, ds = _read_lengths_direct(br, dist_nsym, dist_nbits, -1, dlog)
        blog['dist'] = dlog
        blog['dist_len'] = dl
        dist = _Huff(single=ds) if ds is not None else _Huff(dl)
        b1 = bits()
        blog['hdr_bits'] = b1 - b0
        blog['start_out'] = len(out)
        syms = []
        for _ in range(blog['r8']):
            sym = litlen.decode(br)
            if sym < 0x100:
                out.append(sym)
                syms.append((0, sym, 0))
            else:
                length = sym - 0xFD
                dsym = dist.decode(br)
                dd = 1 if dsym == 0 else (1 << (dsym - 1)) + 1 + br.getbits(dsym - 1)
                start = len(out) - dd
                for k in range(length):
                    out.append(out[start + k])
                syms.append((1, length, dd))
            if len(out) >= size:
                break
        blog['syms'] = syms
        blog['data_bits'] = bits() - b1
        blog['end_out'] = len(out)
        blocks.append(blog)
        if len(out) >= size:
            break
    return bytes(out[:size]), blocks, bits()


# ------------------------------------------------------------- 소스들 ----
def dlq_sections(paths):
    for pat in paths:
        for f in sorted(glob.glob(pat)):
            raw = open(f, 'rb').read()
            d = bytes(dlcres.decrypt(raw))
            po = dlcres.payload_off(raw)
            cont = d[po:struct.unpack_from('<I', d, 4)[0]]
            secs = scen.parse_sections(cont)
            if not secs:
                continue
            for i, (o, l) in enumerate(secs):
                if l and cont[o] in (0x08, 0x0c):
                    yield f, i, cont[o:o + l]


def dat_entries(path, want):
    fh = open(path, 'rb')
    count = struct.unpack('<I', fh.read(4))[0] // 8
    fh.seek(0)
    tbl = fh.read(count * 8)
    table = [struct.unpack_from('<II', tbl, i * 8) for i in range(count)]
    picked = []
    for i, (off, size) in enumerate(table):
        if not size or size > 400000:
            continue
        fh.seek(off)
        if fh.read(1)[0] in (0x08, 0x0c):
            picked.append(i)
    picked.sort(key=lambda i: -table[i][1])
    step = max(1, len(picked) // max(1, want))
    for i in picked[:8] + picked[8::step][:max(0, want - 8)]:
        off, size = table[i]
        fh.seek(off)
        yield path, i, fh.read(size)


# ------------------------------------------------------------- 명령들 ----
def cmd_sizes(items):
    tot_o = tot_n = bad = 0
    for name, i, sec in items:
        dec = huffman.decompress(sec)
        t0 = time.time()
        out = huffman.compress_real(dec, sec[0])
        dt = time.time() - t0
        ok = huffman.decompress(out) == dec
        flag = ''
        if not ok:
            flag = '  *** 왕복 실패'
            bad += 1
        elif len(out) > len(sec):
            flag = '  *** 원본보다 큼'
            bad += 1
        tot_o += len(sec)
        tot_n += len(out)
        print('%-40s #%-5s dec=%8d orig=%8d new=%8d %+7d %6.2fs%s' % (
            name.split('\\')[-1].split('/')[-1], i, len(dec), len(sec), len(out),
            len(out) - len(sec), dt, flag), flush=True)
    print('합계 orig=%d new=%d %+d (%+.2f%%) 실패=%d' % (
        tot_o, tot_n, tot_n - tot_o, -100.0 * (tot_o - tot_n) / max(1, tot_o), bad))
    return bad


def cmd_reenc(items):
    """원본이 고른 심볼열을 그대로 다시 인코딩 -- 테이블 인코더만 검증."""
    tot_o = tot_n = bad = 0
    for name, i, sec in items:
        dec, blocks, _ = decompress_instr(sec)
        window = 0x10 if sec[0] == 0x0c else 0x0d
        dist_nsym, dist_nbits = window + 1, (window + 1 - 10) & 5
        bw = _BW()
        for b in blocks:
            huffman._emit_block(bw, b['syms'], dist_nsym, dist_nbits)
        out = bytes([sec[0]]) + _emit_varint(len(dec)) + bw.getbytes() + b'\x00'
        ok = huffman.decompress(out) == dec
        if not ok or len(out) > len(sec):
            bad += 1
        tot_o += len(sec)
        tot_n += len(out)
        print('%-40s #%-5s orig=%8d reenc=%8d %+6d 왕복=%s' % (
            name.split('\\')[-1].split('/')[-1], i, len(sec), len(out),
            len(out) - len(sec), ok), flush=True)
    print('합계 orig=%d reenc=%d %+d 실패=%d' % (tot_o, tot_n, tot_n - tot_o, bad))
    return bad


def cmd_blocks(items):
    for name, i, sec in items:
        dec, blocks, endbits = decompress_instr(sec)
        print('%s #%s typ=%#04x comp=%d dec=%d 블록=%d 마지막바이트=%d/%d' % (
            name.split('\\')[-1].split('/')[-1], i, sec[0], len(sec), len(dec),
            len(blocks), -(-endbits // 8), len(sec)))
        for bi, b in enumerate(blocks):
            nlit = sum(1 for s in b['syms'] if s[0] == 0)
            nmat = len(b['syms']) - nlit
            print('   블록%-3d r8=%6d 출력=%8d 테이블=%5dbit 데이터=%8dbit '
                  '리터럴=%6d 매치=%6d 단위=%6d llcount=%d' % (
                      bi, b['r8'], b['end_out'] - b['start_out'], b['hdr_bits'],
                      b['data_bits'], nlit, nmat, nlit + 3 * nmat, b['ll_count']))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    mode = argv[1]
    if mode == 'dat':
        items = dat_entries(argv[2], int(argv[3]) if len(argv) > 3 else 30)
        return cmd_sizes(items)
    items = list(dlq_sections(argv[2:]))
    if not items:
        print('압축 섹션을 못 찾았다')
        return 2
    if mode == 'dlq':
        return cmd_sizes(items)
    if mode == 'reenc':
        return cmd_reenc(items)
    if mode == 'blocks':
        return cmd_blocks(items)
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
