"""
CULDCEPT.DAT 타입 0x08 / 0x0c 코덱 -- 디컴프레서 + 컴프레서 (순수 파이썬).

컬드셉트 리볼트(3DS)의 "텍스트/폰트" 코덱입니다. DEFLATE 계열의 커스텀
canonical-Huffman + LZ 방식으로, 게임의 ARM 디코더에서 리버스 엔지니어링했습니다
(디스패처 guest 0x27f3f4 -> 핸들러 0x274b88 / 0x274b90, 비트 리더
0x275020/0x275028, 크기 varint 0x2747f8, 코드길이 리더 0x274e08 / 0x274d18).
게임 코드나 데이터는 포함하지 않으며, 포맷만 담고 있습니다.

  decompress(entry_bytes) -> bytes           # 타입/크기 헤더를 포함한 엔트리 전체
  compress(data, typ=0x0c) -> bytes          # 무압축(전부 리터럴) 유효 엔트리
  compress_real(data, typ=0x0c) -> bytes     # ★진짜 압축기(LZ77+캐노니컬 허프만)

compress_real 은 원본 인코더와 같은(대개 더 좋은) 압축률을 낸다. .dlq 시나리오
컨테이너는 섹션 사이 여유가 0바이트이고 파일 크기가 CRC 대상이라, 번역 후 다시
넣으려면 재압축 결과가 원본 섹션 크기 이하여야 하므로 이것이 필요하다.

타입 0x0d / 0x8d는 다른 (LZMA 계열) 레인지 코더를 쓰며 여기서 다루지 않습니다.
폰트와 대부분의 UI 텍스트는 0x08 / 0x0c 엔트리에 있습니다.
"""

MASK = 0xFFFFFFFF


def clz32(x):
    x &= MASK
    if x == 0:
        return 32
    n = 0
    while not (x & 0x80000000):
        x = (x << 1) & MASK
        n += 1
    return n


# ---------------------------------------------------------------- decoder ----
class _BR:
    """Bit reader matching the game's ARM routine (MSB-first, u16-LE refill)."""
    __slots__ = ('d', 'pos', 'acc', 'cnt')

    def __init__(self, d, pos):
        self.d = d
        self.pos = pos
        self.acc = 0
        self.cnt = 0

    def consume(self, n):
        self.cnt -= n
        self.acc = (self.acc << n) & MASK
        if self.cnt >= 0:
            return
        d = self.d
        p = self.pos
        h = d[p] | (d[p + 1] << 8)                      # little-endian halfword
        self.pos = p + 2
        r1 = (((h & 0xff) << 24) | (((h >> 8) & 0xff) << 16)) & MASK
        self.cnt += 16
        self.acc = (self.acc | (r1 >> self.cnt)) & MASK

    def getbits(self, n):
        if n == 0:
            self.consume(0)
            return 0
        v = self.acc >> (32 - n)
        self.consume(n)
        return v


def parse_varint(d, i):
    """Variable-length size (ARM 0x2747f8); continuation via the sign bit."""
    b1 = d[i]; i += 1
    r5 = b1 - 256 if b1 >= 128 else b1
    b2 = d[i]; i += 1
    r4 = (b2 | ((r5 << 8) & MASK)) & MASK
    if not (r4 & 0x80000000):
        return r4, i
    r4 &= 0x7FFF
    b3 = d[i]; i += 1
    r5 = b3 - 256 if b3 >= 128 else b3
    r4 = (r4 | ((r5 << 15) & MASK)) & MASK
    if not (r4 & 0x80000000):
        return r4, i
    r4 &= 0x3FFFFF
    b4 = d[i]; i += 1
    r4 = (r4 | (b4 << 22)) & MASK
    return r4, i


class _Huff:
    """Canonical (DEFLATE-order, MSB-first) Huffman decoder."""
    __slots__ = ('single', 'symtab', 'maxlen')

    def __init__(self, lengths=None, single=None):
        if single is not None:
            self.single = single
            return
        self.single = None
        maxlen = max(lengths) if lengths else 0
        self.maxlen = maxlen
        blcount = [0] * (maxlen + 1)
        for l in lengths:
            if l:
                blcount[l] += 1
        nextcode = [0] * (maxlen + 2)
        c = 0
        for l in range(1, maxlen + 1):
            c = (c + blcount[l - 1]) << 1
            nextcode[l] = c
        self.symtab = {}
        nc = nextcode[:]
        for sym, l in enumerate(lengths):
            if l:
                self.symtab[(l, nc[l])] = sym
                nc[l] += 1

    def decode(self, br):
        if self.single is not None:
            return self.single
        code = 0
        st = self.symtab
        for l in range(1, self.maxlen + 1):
            code = (code << 1) | ((br.acc >> 31) & 1)
            br.consume(1)
            s = st.get((l, code))
            if s is not None:
                return s
        raise ValueError("bad huffman code")


def _read_lengths_direct(br, nsym, nbits, special_pos):
    count = br.getbits(nbits)
    if count == 0:
        return None, br.getbits(nbits)
    codelen = [0] * max(nsym, count + 40)
    i = 0
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
            if r != 0:
                end = r + i
                while i < end:
                    codelen[i] = 0
                    i += 1
    return codelen[:max(nsym, i)], None


def _make(lengths, single):
    return _Huff(single=single) if single is not None else _Huff(lengths)


def _read_litlen(br):
    cl_len, cl_single = _read_lengths_direct(br, 19, 5, 3)
    cl = _make(cl_len, cl_single)
    count = br.getbits(9)
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
        else:  # s == 2
            out.extend([0] * (0x14 + br.getbits(9)))
    return _Huff(out)


def decompress(entry_bytes):
    """Decompress a whole type-0x08/0x0c entry (including its 4-byte header)."""
    typ = entry_bytes[0]
    if typ not in (0x08, 0x0c):
        raise NotImplementedError("type %#x not supported (0x0d/0x8d = range coder)" % typ)
    d = bytes(entry_bytes) + b'\x00' * 8       # guard for the final halfword refill
    window = 0x10 if typ == 0x0c else 0x0d
    size, pos = parse_varint(d, 1)
    br = _BR(d, pos)
    if pos & 1:                                # address-parity pre-load
        br.acc = (d[pos] << 8) & MASK
        br.pos = pos + 1
        br.cnt = 8
    br.consume(16)                             # prime the accumulator

    out = bytearray()
    dist_nsym = window + 1
    dist_nbits = (window + 1 - 10) & 5
    while len(out) < size:
        r8 = br.getbits(16)
        litlen = _read_litlen(br)
        dl, ds = _read_lengths_direct(br, dist_nsym, dist_nbits, -1)
        dist = _make(dl, ds)
        for _ in range(r8):
            sym = litlen.decode(br)
            if sym < 0x100:
                out.append(sym)
            else:
                length = sym - 0xFD
                dsym = dist.decode(br)
                dd = 1 if dsym == 0 else (1 << (dsym - 1)) + 1 + br.getbits(dsym - 1)
                start = len(out) - dd
                for k in range(length):
                    out.append(out[start + k])
            if len(out) >= size:
                break
        if len(out) >= size:
            break
    return bytes(out[:size])


# ---------------------------------------------------------------- encoder ----
# All-literal, uniform 8-bit scheme: every block uses a degenerate CL table
# (single symbol 10, 0 bits), a 256-entry all-length-8 litlen table (so literal
# byte B is written as the raw 8-bit value B, MSB-first) and an unused degenerate
# distance table.  The payload is just the literal bytes.  It does not compress,
# but it is a valid stream the game decodes exactly, which is all patching needs.
_BLOCK_MAX = 0xFFFF


def _emit_varint(size):
    if size < 0:
        raise ValueError("size < 0")
    if size < 0x8000:
        return bytes([size >> 8, size & 0xFF])
    if size < 0x400000:
        return bytes([0x80 | ((size >> 8) & 0x7F), size & 0xFF, (size >> 15) & 0x7F])
    if size < 0x40000000:
        return bytes([0x80 | ((size >> 8) & 0x7F), size & 0xFF,
                      0x80 | ((size >> 15) & 0x7F), (size >> 22) & 0xFF])
    raise ValueError("size too large for varint (>= 2^30)")


class _BW:
    __slots__ = ("acc", "nbits", "out")

    def __init__(self):
        self.acc = 0
        self.nbits = 0
        self.out = bytearray()

    def write(self, val, n):
        if n == 0:
            return
        self.acc = (self.acc << n) | (val & ((1 << n) - 1))
        self.nbits += n
        while self.nbits >= 8:
            self.nbits -= 8
            self.out.append((self.acc >> self.nbits) & 0xFF)
        self.acc &= (1 << self.nbits) - 1

    def getbytes(self):
        if self.nbits > 0:
            self.out.append((self.acc << (8 - self.nbits)) & 0xFF)
            self.acc = 0
            self.nbits = 0
        return bytes(self.out)


def compress(data, typ=0x0c):
    """Produce a valid type-0x08/0x0c entry (header + stream) for `data`."""
    if typ not in (0x08, 0x0c):
        raise ValueError("typ must be 0x08 or 0x0c")
    data = bytes(data)
    window = 0x10 if typ == 0x0c else 0x0d
    dist_nbits = (window + 1 - 10) & 5
    header = bytes([typ]) + _emit_varint(len(data))
    bw = _BW()
    i = 0
    while i < len(data):
        chunk = data[i:i + _BLOCK_MAX]
        bw.write(len(chunk), 16)      # r8: symbol count
        bw.write(0, 5); bw.write(10, 5)          # CL: single = 10
        bw.write(256, 9)                          # litlen: 256 x length-8
        bw.write(0, dist_nbits); bw.write(0, dist_nbits)   # dist: degenerate
        for b in chunk:
            bw.write(b, 8)
        i += len(chunk)
    return header + bw.getbytes()


# -------------------------------------------------------- real compressor ----
# compress_real() is a genuine LZ77 + canonical-Huffman encoder: the exact
# mirror image of decompress().  Needed because the DLC scenario containers
# (.dlq) are (offset,length) tables with *zero* slack between sections and a
# CRC-protected file size, so a re-encoded section must fit in the original
# section's byte budget.
#
# Layout produced (identical in shape to the shipped data):
#   [type][varint decompressed size][blocks...][1 pad byte]
# and per block
#   r8:16 | CL table | litlen table | dist table | r8 symbols
#
# The trailing pad byte reproduces the shipped encoder's own convention: the
# bit reader refills in halfwords, so it touches up to 2 bytes past the last
# consumed bit -- the original entries over-read their own section by the same
# 1..2 bytes, i.e. this is normal for the game's decoder.

MIN_MATCH = 3
MAX_MATCH = 255          # symbol 0xFD + 255 = 0x1FC, litlen count 509 <= 511
LIMIT_LL = 16            # CL symbol 18 -> litlen code length 16 (hard limit)
LIMIT_CL = 15
LIMIT_DIST = 15
_MAX_BLOCK_SYMS = 0xFFFF


def _pm_lengths(freq, limit):
    """Package-merge: optimal length-limited canonical code lengths.

    `freq` maps symbol -> positive count; returns symbol -> code length.
    """
    items = sorted((w, s) for s, w in freq.items() if w > 0)
    n = len(items)
    if n == 0:
        return {}
    if n == 1:
        return {items[0][1]: 1}
    base = [(w, (s,)) for w, s in items]
    cur = base
    for _ in range(limit - 1):
        pk = []
        for i in range(0, len(cur) - 1, 2):
            a = cur[i]
            b = cur[i + 1]
            pk.append((a[0] + b[0], a[1] + b[1]))
        if not pk:
            break
        cur = sorted(base + pk)
    res = {s: 0 for w, s in items}
    for _w, syms in cur[:2 * n - 2]:
        for s in syms:
            res[s] += 1
    return res


def _canon_codes(lengths):
    """Canonical codes, built exactly the way _Huff.__init__ reads them back."""
    maxlen = max(lengths) if lengths else 0
    blcount = [0] * (maxlen + 1)
    for l in lengths:
        if l:
            blcount[l] += 1
    nc = [0] * (maxlen + 2)
    c = 0
    for l in range(1, maxlen + 1):
        c = (c + blcount[l - 1]) << 1
        nc[l] = c
    codes = [0] * len(lengths)
    for sym, l in enumerate(lengths):
        if l:
            codes[sym] = nc[l]
            nc[l] += 1
    return codes


def _wr_len(bw, L):
    """Inverse of the 3-bit / unary code-length coding in _read_lengths_direct."""
    if L < 7:
        bw.write(L, 3)
    else:
        ones = L - 4                       # (3 + k) one bits, k = L - 7
        bw.write(((1 << ones) - 1) << 1, ones + 1)


def _len_cost(L):
    return 3 if L < 7 else L - 3


def _skip_run(lengths, i, count):
    r = 0
    while r < 3 and i + r < count and lengths[i + r] == 0:
        r += 1
    return r


def _wr_direct(bw, lengths, nbits, special_pos):
    """Inverse of _read_lengths_direct.  True == degenerate (0-bit) table."""
    count = len(lengths)
    while count and lengths[count - 1] == 0:
        count -= 1
    nz = [i for i, l in enumerate(lengths) if l]
    if len(nz) <= 1:                       # single symbol: count 0 + raw index
        bw.write(0, nbits)
        bw.write(nz[0] if nz else 0, nbits)
        return True
    bw.write(count, nbits)
    i = 0
    while i < count:
        _wr_len(bw, lengths[i])
        i += 1
        if i == special_pos:               # the reader always eats these 2 bits
            r = _skip_run(lengths, i, count)
            bw.write(r, 2)
            i += r
    return False


def _direct_cost(lengths, nbits, special_pos):
    count = len(lengths)
    while count and lengths[count - 1] == 0:
        count -= 1
    nz = [i for i, l in enumerate(lengths) if l]
    if len(nz) <= 1:
        return 2 * nbits
    c = nbits
    i = 0
    while i < count:
        c += _len_cost(lengths[i])
        i += 1
        if i == special_pos:
            r = _skip_run(lengths, i, count)
            c += 2
            i += r
    return c


def _rle_ops(ll):
    """litlen code-length array -> [(cl_symbol, extra_value, extra_bits)]."""
    ops = []
    ap = ops.append
    i = 0
    n = len(ll)
    while i < n:
        v = ll[i]
        if v:
            ap((v + 2, 0, 0))              # CL symbol s>2 means length s-2
            i += 1
            continue
        j = i
        while j < n and ll[j] == 0:
            j += 1
        run = j - i
        while run > 0:
            if run >= 20:
                t = run if run <= 531 else 531
                ap((2, t - 0x14, 9))
                run -= t
            elif run >= 3:
                t = run if run <= 18 else 18
                ap((1, t - 3, 4))
                run -= t
            else:
                ap((0, 0, 0))
                run -= 1
        i = j
    return ops


def _cl_for(ll_lengths):
    ops = _rle_ops(ll_lengths)
    freq = {}
    for o in ops:
        freq[o[0]] = freq.get(o[0], 0) + 1
    clmap = _pm_lengths(freq, LIMIT_CL)
    return ops, [clmap.get(s, 0) for s in range(19)]


def _wr_litlen(bw, ll_lengths):
    """Inverse of _read_litlen.  Returns (degenerate?, codes, trimmed lengths)."""
    count = len(ll_lengths)
    while count and ll_lengths[count - 1] == 0:
        count -= 1
    ll_lengths = ll_lengths[:count]
    nz = [i for i, l in enumerate(ll_lengths) if l]
    if len(nz) <= 1:
        bw.write(0, 5); bw.write(0, 5)     # CL is read unconditionally: make it cheap
        bw.write(0, 9)                     # litlen count 0 -> single symbol follows
        bw.write(nz[0] if nz else 0, 9)
        return True, None, ll_lengths
    ops, cl_lengths = _cl_for(ll_lengths)
    cl_degen = _wr_direct(bw, cl_lengths, 5, 3)
    cl_codes = _canon_codes(cl_lengths)
    bw.write(count, 9)
    for sym, ev, eb in ops:
        if not cl_degen:
            bw.write(cl_codes[sym], cl_lengths[sym])
        if eb:
            bw.write(ev, eb)
    return False, _canon_codes(ll_lengths), ll_lengths


def _litlen_cost(ll_lengths):
    count = len(ll_lengths)
    while count and ll_lengths[count - 1] == 0:
        count -= 1
    ll_lengths = ll_lengths[:count]
    if sum(1 for l in ll_lengths if l) <= 1:
        return 5 + 5 + 9 + 9
    ops, cl_lengths = _cl_for(ll_lengths)
    c = _direct_cost(cl_lengths, 5, 3) + 9
    cl_degen = sum(1 for l in cl_lengths if l) <= 1
    for sym, _ev, eb in ops:
        if not cl_degen:
            c += cl_lengths[sym]
        c += eb
    return c


def _dist_sym(dd):
    """dd -> (symbol, extra value, extra bits); inverse of the decoder formula
    dd = 1 if s == 0 else (1 << (s-1)) + 1 + getbits(s-1)."""
    if dd <= 2:
        return (0, 0, 0) if dd == 1 else (1, 0, 0)
    k = (dd - 1).bit_length()
    return k, dd - 1 - (1 << (k - 1)), k - 1


# ------------------------------------------------------------- LZ77 parse ----
def _lz_matches(data, max_dist, max_chain, nice_len):
    """Per-position candidates [(length, distance), ...]: strictly increasing
    lengths, each with the nearest distance that reaches it."""
    n = len(data)
    head = {}
    prev = [-1] * n
    out = [()] * n
    d = data
    for i in range(n - MIN_MATCH + 1):
        key = (d[i] << 16) | (d[i + 1] << 8) | d[i + 2]
        j = head.get(key, -1)
        prev[i] = j
        head[key] = i
        maxl = MAX_MATCH if n - i > MAX_MATCH else n - i
        best = MIN_MATCH - 1
        cands = []
        chain = max_chain
        lim = i - max_dist
        while j >= lim and j >= 0 and chain:
            chain -= 1
            # cheap reject, then confirm the known-good prefix at C speed
            if d[j + best] == d[i + best] and d[j:j + best] == d[i:i + best]:
                lo = best + 1                       # proven equal
                if lo >= maxl or d[j:j + maxl] == d[i:i + maxl]:
                    lo = maxl
                else:
                    hi = maxl                       # proven unequal
                    while hi - lo > 1:              # binary search, C-speed compares
                        mid = (lo + hi) >> 1
                        if d[j:j + mid] == d[i:i + mid]:
                            lo = mid
                        else:
                            hi = mid
                best = lo
                cands.append((lo, i - j))
                if lo >= nice_len or lo >= maxl:
                    break
            j = prev[j]
        if cands:
            out[i] = tuple(cands)
    return out


def _greedy_parse(data, cands):
    n = len(data)
    toks = []
    i = 0
    while i < n:
        c = cands[i]
        if c:
            l, dd = c[-1]
            c2 = cands[i + 1] if i + 1 < n else ()
            if c2 and c2[-1][0] > l:                # lazy match
                toks.append((0, data[i], 0))
                i += 1
                continue
            toks.append((1, l, dd))
            i += l
        else:
            toks.append((0, data[i], 0))
            i += 1
    return toks


def _tok_stats(toks):
    llf = {}
    df = {}
    for t in toks:
        s = t[1] if t[0] == 0 else t[1] + 0xFD
        llf[s] = llf.get(s, 0) + 1
        if t[0]:
            ds = _dist_sym(t[2])[0]
            df[ds] = df.get(ds, 0) + 1
    return llf, df


def _cost_model(llf, df, dist_nsym):
    llmap = _pm_lengths(llf, LIMIT_LL)
    dmap = _pm_lengths(df, LIMIT_DIST)
    worst = (max(llmap.values()) if llmap else 8) + 3
    llc = [(llmap.get(s, 0) or worst) for s in range(512)]
    dworst = (max(dmap.values()) if dmap else 4) + 3
    dc = [(dmap.get(s, 0) or dworst) + (s - 1 if s > 0 else 0)
          for s in range(dist_nsym)]
    return llc, dc


def _optimal_parse(data, cands, llc, dc, max_opts):
    """Shortest-path LZ parse under a bit-cost model taken from a previous pass."""
    n = len(data)
    INF = float('inf')
    cost = [INF] * (n + 1)
    argl = [0] * (n + 1)
    argd = [0] * (n + 1)
    cost[0] = 0.0
    half = max_opts >> 1
    for i in range(n):
        ci = cost[i]
        if ci == INF:
            continue
        c = ci + llc[data[i]]
        if c < cost[i + 1]:
            cost[i + 1] = c
            argl[i + 1] = 0
            argd[i + 1] = 0
        cl = cands[i]
        if not cl:
            continue
        lo = MIN_MATCH
        for (l, dd) in cl:
            ds = 0 if dd == 1 else (1 if dd == 2 else (dd - 1).bit_length())
            base = ci + dc[ds]
            if l - lo >= max_opts:              # sample, do not walk 250 lengths
                rng = list(range(lo, lo + half)) + list(range(l - half + 1, l + 1))
            else:
                rng = range(lo, l + 1)
            for t in rng:
                c = base + llc[t + 0xFD]
                if c < cost[i + t]:
                    cost[i + t] = c
                    argl[i + t] = t
                    argd[i + t] = dd
            lo = l + 1
            if lo > MAX_MATCH:
                break
    toks = []
    p = n
    while p > 0:
        l = argl[p]
        if l == 0:
            toks.append((0, data[p - 1], 0))
            p -= 1
        else:
            toks.append((1, l, argd[p]))
            p -= l
    toks.reverse()
    return toks


# ------------------------------------------------------------- block emit ----
def _block_tables(toks, dist_nsym):
    llf, df = _tok_stats(toks)
    llmap = _pm_lengths(llf, LIMIT_LL)
    maxsym = max(llmap) if llmap else 0
    ll_lengths = [llmap.get(s, 0) for s in range(maxsym + 1)]
    dmap = _pm_lengths(df, LIMIT_DIST)
    d_lengths = [dmap.get(s, 0) for s in range(dist_nsym)]
    return ll_lengths, d_lengths


def _emit_block(bw, toks, dist_nsym, dist_nbits):
    ll_lengths, d_lengths = _block_tables(toks, dist_nsym)
    bw.write(len(toks), 16)
    ll_degen, ll_codes, ll_lengths = _wr_litlen(bw, ll_lengths)
    d_degen = _wr_direct(bw, d_lengths, dist_nbits, -1)
    d_codes = _canon_codes(d_lengths)
    for t in toks:
        if t[0] == 0:
            if not ll_degen:
                bw.write(ll_codes[t[1]], ll_lengths[t[1]])
        else:
            sym = t[1] + 0xFD
            if not ll_degen:
                bw.write(ll_codes[sym], ll_lengths[sym])
            ds, ev, eb = _dist_sym(t[2])
            if not d_degen:
                bw.write(d_codes[ds], d_lengths[ds])
            if eb:
                bw.write(ev, eb)


def _block_cost(toks, dist_nsym, dist_nbits):
    ll_lengths, d_lengths = _block_tables(toks, dist_nsym)
    c = 16 + _litlen_cost(ll_lengths) + _direct_cost(d_lengths, dist_nbits, -1)
    ll_degen = sum(1 for l in ll_lengths if l) <= 1
    d_degen = sum(1 for l in d_lengths if l) <= 1
    for t in toks:
        sym = t[1] if t[0] == 0 else t[1] + 0xFD
        if not ll_degen:
            c += ll_lengths[sym]
        if t[0]:
            ds, _ev, eb = _dist_sym(t[2])
            if not d_degen:
                c += d_lengths[ds]
            c += eb
    return c


# Every block carries a fresh CL/litlen/dist table (~600..1400 bits), so long
# inputs want several of them: the shipped encoder flushes whenever
# (literals + 3*matches) reaches ~15000, i.e. roughly 12 KB of output.  We try a
# handful of budgets around that and keep the cheapest split.
_SPLIT_BUDGETS = (15000, 8000, 30000, 60000, 1 << 30)
_DEFAULT_BUDGET = 15000


def _split_blocks(toks, budget=_DEFAULT_BUDGET):
    if len(toks) <= _MAX_BLOCK_SYMS and budget >= 3 * len(toks):
        return [toks]
    out = []
    start = 0
    acc = 0
    for i, t in enumerate(toks):
        acc += 1 if t[0] == 0 else 3
        if acc >= budget or i - start + 1 >= _MAX_BLOCK_SYMS:
            out.append(toks[start:i + 1])
            start = i + 1
            acc = 0
    if start < len(toks):
        out.append(toks[start:])
    return out


def _choose_split(toks, dist_nsym, dist_nbits):
    best = None
    bestc = None
    seen = set()
    for b in _SPLIT_BUDGETS:
        parts = _split_blocks(toks, b)
        key = tuple(len(p) for p in parts)
        if key in seen:
            continue
        seen.add(key)
        c = sum(_block_cost(p, dist_nsym, dist_nbits) for p in parts)
        if bestc is None or c < bestc:
            bestc = c
            best = parts
    return best, bestc


def _total_cost(toks, dist_nsym, dist_nbits):
    return sum(_block_cost(ch, dist_nsym, dist_nbits)
               for ch in _split_blocks(toks, _DEFAULT_BUDGET))


def _parse_tokens(data, max_dist, dist_nsym, dist_nbits, effort):
    n = len(data)
    if effort <= 0:
        chain, nice, iters, opts = 16, 32, 0, 24
    elif effort == 1:
        chain, nice, iters, opts = 64, 64, 1, 32
    else:
        chain, nice, iters, opts = 256, 200, 3, 48
        if n > 1 << 16:                    # keep the pure-python runtime sane
            chain, nice, iters, opts = 64, 96, 2, 32
        if n > 1 << 18:
            chain, nice, iters, opts = 32, 64, 1, 24
    cands = _lz_matches(data, max_dist, chain, nice)
    best = _greedy_parse(data, cands)
    bestc = _total_cost(best, dist_nsym, dist_nbits)
    cur = best
    for _ in range(iters):
        llf, df = _tok_stats(cur)
        llc, dc = _cost_model(llf, df, dist_nsym)
        cur = _optimal_parse(data, cands, llc, dc, opts)
        c = _total_cost(cur, dist_nsym, dist_nbits)
        if c < bestc:
            bestc = c
            best = cur
        else:
            break
    return best


def compress_real(data, typ=0x0c, effort=2):
    """Really compress `data` into a type-0x08/0x0c entry (header + stream).

    effort 0 = fast greedy, 1 = one optimal-parse pass, 2 = full (default).
    Guarantees decompress(compress_real(x, t)) == x for every x.
    """
    if typ not in (0x08, 0x0c):
        raise ValueError("typ must be 0x08 or 0x0c")
    data = bytes(data)
    window = 0x10 if typ == 0x0c else 0x0d
    max_dist = 1 << window
    dist_nsym = window + 1
    dist_nbits = (window + 1 - 10) & 5
    bw = _BW()
    if data:
        toks = _parse_tokens(data, max_dist, dist_nsym, dist_nbits, effort)
        parts, _c = _choose_split(toks, dist_nsym, dist_nbits)
        for chunk in parts:
            _emit_block(bw, chunk, dist_nsym, dist_nbits)
    return bytes([typ]) + _emit_varint(len(data)) + bw.getbytes() + b'\x00'


if __name__ == "__main__":
    import os, random
    random.seed(1)
    for n in (0, 1, 1000, 70000, 300000):
        d = os.urandom(n)
        assert decompress(compress(d, 0x0c)) == d, n
        assert decompress(compress(d, 0x08)) == d, n
    print("all-literal round-trip OK")
    samples = [b'', b'A', b'AB', b'AAA', b'A' * 100000, bytes(range(256)) * 200,
               os.urandom(20000), (b'hello world ' * 900) + os.urandom(300)]
    samples += [bytes(random.choice(b'abcdefg ') for _ in range(5000))]
    for d in samples:
        for t in (0x08, 0x0c):
            e = compress_real(d, t)
            assert decompress(e) == d, (t, len(d))
    print("compress_real round-trip OK")
