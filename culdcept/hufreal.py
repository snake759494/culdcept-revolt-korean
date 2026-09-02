# -*- coding: utf-8 -*-
"""Real LZ77 + canonical-Huffman compressor for the Culdcept Revolt 0x08/0x0c codec.

`huffman.compress()` emits an all-literal stream (valid, but ~3x the original
size).  `compress_real()` here is a genuine encoder: it mirrors
`huffman.decompress()` bit for bit, so `decompress(compress_real(x)) == x`, and
it beats the ratio of the game's own encoder on every entry tested.

Use it where a re-encoded entry must fit back into its original byte budget --
notably the (offset, length) section containers of the DLC .dlq scenario files,
which have no slack between sections.

    compress_real(data, typ=0x0c, effort=2) -> bytes    # header + bitstream

effort 0 = lazy/greedy parse only (fastest), 3 = deepest match search +
cost-driven re-parse + block splitting.  2 is a good default.

Everything below `# --- huffman code lengths ---` can be pasted verbatim into
culdcept/huffman.py; `_BW` and `_emit_varint` already exist there, so drop this
module's copies of those two when doing so.
"""
import heapq

# ---------------------------------------------------------------- bit writer -
class _BW:
    __slots__ = ("acc", "nbits", "out")

    def __init__(self):
        self.acc = 0
        self.nbits = 0
        self.out = bytearray()

    def write(self, val, n):
        if n <= 0:
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


# ------------------------------------------------------- huffman code lengths -
def _code_lengths(freqs, limit):
    n = len(freqs)
    lengths = [0] * n
    used = [i for i in range(n) if freqs[i]]
    if not used:
        return lengths
    if len(used) == 1:
        lengths[used[0]] = 1
        return lengths
    kids = []
    heap = [(freqs[s], s) for s in used]
    heapq.heapify(heap)
    nxt = n
    while len(heap) > 1:
        w1, a = heapq.heappop(heap)
        w2, b = heapq.heappop(heap)
        kids.append((a, b))
        heapq.heappush(heap, (w1 + w2, nxt))
        nxt += 1
    stack = [(heap[0][1], 0)]
    while stack:
        node, dep = stack.pop()
        if node < n:
            lengths[node] = dep or 1
        else:
            a, b = kids[node - n]
            stack.append((a, dep + 1))
            stack.append((b, dep + 1))
    if max(lengths) <= limit:
        return lengths
    for s in used:
        if lengths[s] > limit:
            lengths[s] = limit
    order = sorted(used, key=lambda s: (freqs[s], s))          # ascending freq
    total = 1 << limit
    kraft = sum(1 << (limit - lengths[s]) for s in used)
    while kraft > total:
        for s in order:
            if lengths[s] < limit:
                kraft -= 1 << (limit - lengths[s] - 1)
                lengths[s] += 1
                break
        else:
            raise ValueError("alphabet too large to length-limit")
    for s in reversed(order):
        while lengths[s] > 1 and kraft + (1 << (limit - lengths[s])) <= total:
            kraft += 1 << (limit - lengths[s])
            lengths[s] -= 1
    return lengths


def _canon_codes(lengths):
    maxlen = max(lengths) if lengths else 0
    blcount = [0] * (maxlen + 2)
    for l in lengths:
        if l:
            blcount[l] += 1
    nc = [0] * (maxlen + 2)
    c = 0
    for l in range(1, maxlen + 1):
        c = (c + blcount[l - 1]) << 1
        nc[l] = c
    codes = [0] * len(lengths)
    for s, l in enumerate(lengths):
        if l:
            codes[s] = nc[l]
            nc[l] += 1
    return codes


# ------------------------------------------ direct ("3-bit + escape") tables --
def _len_code_bits(L):
    if L < 7:
        return L, 3
    extra = L - 7
    return (7 << (extra + 1)) | (((1 << extra) - 1) << 1), 3 + extra + 1


def _direct_walk(lengths, count, special_pos):
    """Yield (value, nbits) for the body of a direct table."""
    i = 0
    while i < count:
        yield _len_code_bits(lengths[i])
        i += 1
        if i == special_pos:
            z = 0
            while z < 3 and i + z < count and lengths[i + z] == 0:
                z += 1
            yield (z, 2)
            i += z


class _DirectTable:
    """A code-length table stored in the _read_lengths_direct format."""
    __slots__ = ("degen", "sym", "bits", "lens", "codes", "nbits", "special_pos", "count")

    def __init__(self, freqs, nbits, special_pos, limits=(15,)):
        n = len(freqs)
        used = [i for i, f in enumerate(freqs) if f]
        self.nbits = nbits
        self.special_pos = special_pos
        if len(used) <= 1:
            self.degen = True
            self.sym = used[0] if used else 0
            if self.sym >= (1 << nbits):
                raise ValueError("degenerate symbol does not fit")
            self.bits = 2 * nbits
            self.lens = [0] * n
            self.codes = [0] * n
            self.count = 0
            return
        self.degen = False
        best = None
        for lim in limits:
            L = _code_lengths(freqs, lim)
            cnt = max(i for i, x in enumerate(L) if x) + 1
            tb = nbits + sum(nb for _v, nb in _direct_walk(L, cnt, special_pos))
            cost = tb + sum(freqs[i] * L[i] for i in used)
            if best is None or cost < best[0]:
                best = (cost, L, tb, cnt)
        _, self.lens, self.bits, self.count = best
        if self.count >= (1 << nbits):
            raise ValueError("direct table count does not fit in %d bits" % nbits)
        self.codes = _canon_codes(self.lens)

    def write(self, bw):
        if self.degen:
            bw.write(0, self.nbits)
            bw.write(self.sym, self.nbits)
            return
        bw.write(self.count, self.nbits)
        for v, nb in _direct_walk(self.lens, self.count, self.special_pos):
            bw.write(v, nb)

    def emit(self, bw, s):
        if self.lens[s]:
            bw.write(self.codes[s], self.lens[s])


# ------------------------------------------- litlen table (CL-coded lengths) --
def _cl_items(lengths):
    items = []
    n = len(lengths)
    i = 0
    while i < n:
        if lengths[i]:
            items.append((lengths[i] + 2, 0, 0))
            i += 1
            continue
        j = i
        while j < n and lengths[j] == 0:
            j += 1
        run = j - i
        while run:
            if run >= 0x14:
                t = min(run, 0x14 + 511)
                items.append((2, t - 0x14, 9))
            elif run >= 3:
                t = min(run, 3 + 15)          # symbol 1 carries only 4 extra bits
                items.append((1, t - 3, 4))
            else:
                t = 1
                items.append((0, 0, 0))
            run -= t
        i = j
    return items


_LIT_LIMITS = (15, 14, 13, 12, 11, 10, 9, 16)
_CL_LIMITS = (7, 8, 9, 10, 11, 12, 15)


class _LitTable:
    __slots__ = ("degen", "sym", "bits", "lens", "codes", "cl", "items", "count")

    def __init__(self, freqs, lit_limits=_LIT_LIMITS, cl_limits=_CL_LIMITS):
        n = len(freqs)
        used = [i for i, f in enumerate(freqs) if f]
        if len(used) <= 1:
            self.degen = True
            self.sym = used[0] if used else 0
            self.cl = _DirectTable([0] * 19, 5, 3)
            self.bits = self.cl.bits + 9 + 9
            self.lens = [0] * n
            self.codes = [0] * n
            self.count = 0
            self.items = None
            return
        self.degen = False
        best = None
        for lim in lit_limits:
            if lim > 16:
                continue
            L = _code_lengths(freqs, lim)
            cnt = max(used) + 1
            if cnt > 511:
                raise ValueError("litlen alphabet too large")
            items = _cl_items(L[:cnt])
            clf = [0] * 19
            for s, _v, _nb in items:
                clf[s] += 1
            cl = _DirectTable(clf, 5, 3, cl_limits)
            tb = cl.bits + 9 + sum(cl.lens[s] + nb for s, _v, nb in items)
            cost = tb + sum(freqs[i] * L[i] for i in used)
            if best is None or cost < best[0]:
                best = (cost, L, tb, cnt, items, cl)
        _, self.lens, self.bits, self.count, self.items, self.cl = best
        self.codes = _canon_codes(self.lens)

    def write(self, bw):
        self.cl.write(bw)
        if self.degen:
            bw.write(0, 9)
            bw.write(self.sym, 9)
            return
        bw.write(self.count, 9)
        for s, v, nb in self.items:
            self.cl.emit(bw, s)
            if nb:
                bw.write(v, nb)

    def emit(self, bw, s):
        if self.lens[s]:
            bw.write(self.codes[s], self.lens[s])


# --------------------------------------------------------------------- block --
_MAX_MATCH = 255
_MIN_MATCH = 3
_NLIT = _MAX_MATCH + 0xFD + 1                       # 509 symbols (0..508)


def _dist_sym(dd):
    return 0 if dd == 1 else (dd - 1).bit_length()


class _Block:
    """tokens: list of (litlen_sym, dsym, dextra); dsym == -1 for a literal."""

    def __init__(self, tokens, dist_nsym, dist_nbits):
        self.tokens = tokens
        self.dist_nbits = dist_nbits
        lit_freq = [0] * _NLIT
        dist_freq = [0] * dist_nsym
        for s, d, _e in tokens:
            lit_freq[s] += 1
            if d >= 0:
                dist_freq[d] += 1
        self.lit = _LitTable(lit_freq)
        self.dist = _DirectTable(dist_freq, dist_nbits, -1)
        extra = 0
        for d, f in enumerate(dist_freq):
            if f and d:
                extra += f * (d - 1)
        symbits = sum(lit_freq[i] * self.lit.lens[i] for i in range(_NLIT) if lit_freq[i])
        symbits += sum(dist_freq[i] * self.dist.lens[i] for i in range(dist_nsym) if dist_freq[i])
        self.bits = 16 + self.lit.bits + self.dist.bits + symbits + extra

    def write(self, bw):
        bw.write(len(self.tokens), 16)
        self.lit.write(bw)
        self.dist.write(bw)
        for s, d, e in self.tokens:
            self.lit.emit(bw, s)
            if d >= 0:
                self.dist.emit(bw, d)
                if d:
                    bw.write(e, d - 1)

    def cost_tables(self):
        """(lit_cost[sym], dist_cost[dsym]) in bits, for the optimal parser."""
        big = 40                       # penalty for a symbol the table cannot code
        if self.lit.degen:             # degenerate table: its one symbol is free
            lc = [0 if i == self.lit.sym else big for i in range(len(self.lit.lens))]
        else:
            lc = [l if l else big for l in self.lit.lens]
        if self.dist.degen:
            dc = [(0 if d == self.dist.sym else big) + ((d - 1) if d else 0)
                  for d in range(len(self.dist.lens))]
        else:
            dc = [(l if l else big) + ((d - 1) if d else 0)
                  for d, l in enumerate(self.dist.lens)]
        return lc, dc


# ------------------------------------------------------------- match finding --
def _find_matches(data, max_dist, max_chain):
    """Per position: the longest match (mlen/mdist) and the nearest one (nlen/ndist)."""
    n = len(data)
    mlen = [0] * n
    mdist = [0] * n
    nlen = [0] * n
    ndist = [0] * n
    if n < _MIN_MATCH:
        return mlen, mdist, nlen, ndist
    head = {}
    prev = [-1] * n
    last = n - _MIN_MATCH
    di = data
    for i in range(n):
        if i > last:
            break
        h = (di[i] << 16) | (di[i + 1] << 8) | di[i + 2]
        j = head.get(h, -1)
        prev[i] = j
        head[h] = i
        if j < 0:
            continue
        lim = i - max_dist
        if lim < 0:                       # -1 also terminates the chain
            lim = -1
        maxl = _MAX_MATCH
        if maxl > n - i:
            maxl = n - i
        best = 0
        bdist = 0
        near = 0
        neard = 0
        chain = max_chain
        while j > lim and chain:
            chain -= 1
            if best:
                if di[j + best] != di[i + best] or di[j:j + best] != di[i:i + best]:
                    j = prev[j]
                    continue
                l = best
            else:
                l = 0
            while l < maxl and di[j + l] == di[i + l]:
                l += 1
            if l > best:
                if not near and l >= _MIN_MATCH:
                    near = l
                    neard = i - j
                best = l
                bdist = i - j
                if l >= maxl:
                    break
            j = prev[j]
        if best >= _MIN_MATCH:
            mlen[i] = best
            mdist[i] = bdist
            nlen[i] = near
            ndist[i] = neard
    return mlen, mdist, nlen, ndist


def _tok_lit(b):
    return (b, -1, 0)


def _tok_match(length, dd):
    d = _dist_sym(dd)
    return (length + 0xFD, d, (dd - (1 << (d - 1)) - 1) if d else 0)


def _parse_greedy(data, mlen, mdist, lazy=True):
    n = len(data)
    toks = []
    i = 0
    while i < n:
        L = mlen[i]
        if L >= _MIN_MATCH:
            if lazy and i + 1 < n and mlen[i + 1] > L:
                toks.append(_tok_lit(data[i]))
                i += 1
                continue
            toks.append(_tok_match(L, mdist[i]))
            i += L
        else:
            toks.append(_tok_lit(data[i]))
            i += 1
    return toks


def _parse_optimal(data, matches, litcost, distcost):
    """Shortest-path parse under the given per-symbol bit costs."""
    mlen, mdist, nlen, ndist = matches
    n = len(data)
    INF = float("inf")
    cost = [INF] * (n + 1)
    prevpos = [0] * (n + 1)
    prevlen = [0] * (n + 1)
    prevdd = [0] * (n + 1)
    cost[0] = 0.0
    nlit = len(litcost)
    ndc = len(distcost)
    for i in range(n):
        ci = cost[i]
        if ci == INF:
            continue
        c = ci + litcost[data[i]]
        if c < cost[i + 1]:
            cost[i + 1] = c
            prevpos[i + 1] = i
            prevlen[i + 1] = 0
        L = mlen[i]
        if L < _MIN_MATCH:
            continue
        opts = ((L, mdist[i]),)
        if nlen[i] and ndist[i] != mdist[i]:
            opts = ((nlen[i], ndist[i]), (L, mdist[i]))
        for ol, dd in opts:
            d = 0 if dd == 1 else (dd - 1).bit_length()
            if d >= ndc:
                continue
            base = ci + distcost[d]
            for l in range(_MIN_MATCH, ol + 1):
                s = l + 0xFD
                if s >= nlit:
                    break
                c = base + litcost[s]
                if c < cost[i + l]:
                    cost[i + l] = c
                    prevpos[i + l] = i
                    prevlen[i + l] = l
                    prevdd[i + l] = dd
    out = []
    p = n
    while p > 0:
        q = prevpos[p]
        l = prevlen[p]
        if l:
            out.append(_tok_match(l, prevdd[p]))
        else:
            out.append(_tok_lit(data[q]))
        p = q
    out.reverse()
    return out


# ------------------------------------------------------------------ top level
_BLOCK_MAX = 0xFFFF


def _split_blocks(toks, dist_nsym, dist_nbits, depth):
    """Recursively split a token run where two tables beat one."""
    whole = _Block(toks, dist_nsym, dist_nbits)
    if depth <= 0 or len(toks) < 512:
        return [whole]
    n = len(toks)
    best = None
    for k in range(1, 8):
        cut = n * k // 8
        if cut < 64 or n - cut < 64:
            continue
        a = _Block(toks[:cut], dist_nsym, dist_nbits)
        b = _Block(toks[cut:], dist_nsym, dist_nbits)
        tot = a.bits + b.bits
        if best is None or tot < best[0]:
            best = (tot, cut, a, b)
    if best is None or best[0] >= whole.bits:
        return [whole]
    _tot, cut, _a, _b = best
    return (_split_blocks(toks[:cut], dist_nsym, dist_nbits, depth - 1) +
            _split_blocks(toks[cut:], dist_nsym, dist_nbits, depth - 1))


def compress_real(data, typ=0x0c, effort=2):
    """Compress `data` into a complete type-0x08/0x0c entry (header + stream)."""
    if typ not in (0x08, 0x0c):
        raise ValueError("typ must be 0x08 or 0x0c")
    data = bytes(data)
    window = 0x10 if typ == 0x0c else 0x0d
    dist_nsym = window + 1
    dist_nbits = (window + 1 - 10) & 5
    max_dist = 1 << window
    header = bytes([typ]) + _emit_varint(len(data))
    if not data:
        return header
    chain = (16, 64, 256, 1024)[min(effort, 3)]
    matches = _find_matches(data, max_dist, chain)
    mlen, mdist = matches[0], matches[1]
    split_depth = (0, 3, 4, 5)[min(effort, 3)]

    def build(toks, depth=0):
        blocks = []
        i = 0
        while i < len(toks):
            part = toks[i:i + _BLOCK_MAX]
            blocks.extend(_split_blocks(part, dist_nsym, dist_nbits, depth))
            i += len(part)
        return blocks

    best_toks = _parse_greedy(data, mlen, mdist, lazy=True)
    best_blocks = build(best_toks, split_depth)
    best_bits = sum(b.bits for b in best_blocks)
    rounds = (0, 3, 5, 8)[min(effort, 3)]
    for _ in range(rounds):
        # cost model from one table over the whole token stream, so that a file
        # split into several blocks is not parsed against its first block only
        lc, dc = _Block(best_toks[:_BLOCK_MAX * 4], dist_nsym, dist_nbits).cost_tables()
        toks = _parse_optimal(data, matches, lc, dc)
        blocks = build(toks, split_depth)
        bits = sum(b.bits for b in blocks)
        if bits >= best_bits:
            break
        best_bits, best_blocks, best_toks = bits, blocks, toks
    bw = _BW()
    for b in best_blocks:
        b.write(bw)
    return header + bw.getbytes()


if __name__ == "__main__":
    import os as _os
    import random as _random
    from . import huffman as _h                     # python -m culdcept.hufreal
    _r = _random.Random(0)
    for _n in (0, 1, 2, 5, 100, 1000, 0x8000, 70000):
        for _d in (_os.urandom(_n),
                   b"\x41" * _n,
                   (b"the quick brown fox " * (_n // 20 + 1))[:_n]):
            for _t in (0x08, 0x0c):
                assert _h.decompress(compress_real(_d, _t)) == _d, (_n, _t)
    for _n in (300, 5000, 40000):
        _d = bytes(_r.choice(b"abcdefgh ") for _ in range(_n))
        for _t in (0x08, 0x0c):
            _e = compress_real(_d, _t)
            assert _h.decompress(_e) == _d
            assert len(_e) < _n // 2
    print("compress_real round-trip OK")
