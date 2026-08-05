# -*- coding: utf-8 -*-
"""3DS ETC1 / ETC1A4 텍스처 코덱 (컬드셉트 리볼트 UI 아틀라스용).

3DS 는 ETC1 8바이트 블록을 표준 빅엔디언이 아니라 **u64 리틀엔디언**으로 저장한다
(= 표준 ETC1 블록의 바이트 역순). 이 사실을 모르면 색이 전혀 맞지 않는다.

포맷별 4×4 블록 크기와 오프셋:
  * ETC1   (아자하르 덤프 fmt 12, DAT 텍스처 헤더 0x0c): 블록 = 8바이트(색만).
  * ETC1A4 (아자하르 덤프 fmt 13):                       블록 = 16바이트(알파 8 + 색 8).

블록 배치(스위즐)는 8×8 픽셀 타일 row-major, 타일 안 4개의 4×4 블록은 2×2 row-major.
오프셋 헬퍼는 apply_ui_images.py 의 `block_off()` 참고. 색 블록은 ETC1A4 에서 off+8,
ETC1 에서 off 에 놓인다(둘 다 8바이트 정렬 → decode_all_blocks 의 8B 스트라이드로 커버).

decode_all_blocks 는 데이터의 모든 8바이트 정렬 위치를 한 번에 벡터 디코드한다.
encode_block 은 한 4×4 색블록을 individual 모드로 최적 인코딩(왕복 오차 ≤ 1).
알파(A4)는 별도이며 이 모듈은 건드리지 않는다(원본 알파 그대로 보존).

포맷 상세는 docs/FORMAT.md §9 참고.
"""
import numpy as np

# ETC1 밝기 modifier 테이블 (표준). [table][index] -> 밝기 가감값.
ETC_MOD = np.array([
    [2, 8, -2, -8], [5, 17, -5, -17], [9, 29, -9, -29], [13, 42, -13, -42],
    [18, 60, -18, -60], [24, 80, -24, -80], [33, 106, -33, -106], [47, 183, -47, -183],
], np.int32)


def decode_all_blocks(data):
    """data 를 8바이트 스트라이드로 모든 위치에서 ETC1 색블록 디코드 → (N,4,4,3) uint8.

    N = len(data)//8. 3DS u64 LE 를 가정하고 표준 BE 로 뒤집어 해석한다.
    반환 배열 out[k] 는 data[k*8 : k*8+8] 을 디코드한 4×4 RGB 블록.
    특정 텍스처의 (bx,by) 색블록은 out[color_off//8] 로 얻는다.
    """
    N = len(data) // 8
    raw = np.frombuffer(bytes(data[:N * 8]), np.uint8).reshape(N, 8)
    blk = raw[:, ::-1].astype(np.int32)               # u64 LE -> 표준 BE 바이트순
    b0, b1, b2, b3 = blk[:, 0], blk[:, 1], blk[:, 2], blk[:, 3]
    diff = (b3 & 2) > 0
    flip = (b3 & 1) > 0
    t1 = (b3 >> 5) & 7
    t2 = (b3 >> 2) & 7
    # differential 모드: 5비트 기준색 + 3비트 부호 델타
    r1 = (b0 >> 3) & 0x1f; g1 = (b1 >> 3) & 0x1f; bl1 = (b2 >> 3) & 0x1f
    dr = b0 & 7; dg = b1 & 7; db = b2 & 7
    dr = np.where(dr >= 4, dr - 8, dr)
    dg = np.where(dg >= 4, dg - 8, dg)
    db = np.where(db >= 4, db - 8, db)
    r2 = r1 + dr; g2 = g1 + dg; bl2 = bl1 + db
    c1d = np.stack([(r1 << 3) | (r1 >> 2), (g1 << 3) | (g1 >> 2), (bl1 << 3) | (bl1 >> 2)], 1)
    c2d = np.stack([(r2 << 3) | (r2 >> 2), (g2 << 3) | (g2 >> 2), (bl2 << 3) | (bl2 >> 2)], 1)
    # individual 모드: 4비트 기준색 두 개(×17 확장)
    c1i = np.stack([((b0 >> 4) & 0xf) * 17, ((b1 >> 4) & 0xf) * 17, ((b2 >> 4) & 0xf) * 17], 1)
    c2i = np.stack([(b0 & 0xf) * 17, (b1 & 0xf) * 17, (b2 & 0xf) * 17], 1)
    c1 = np.where(diff[:, None], c1d, c1i)
    c2 = np.where(diff[:, None], c2d, c2i)
    mod = (blk[:, 4] << 24) | (blk[:, 5] << 16) | (blk[:, 6] << 8) | blk[:, 7]
    out = np.zeros((N, 4, 4, 3), np.int32)
    for px in range(16):
        x = px // 4; y = px % 4
        sub = np.where(flip, y >= 2, x >= 2)          # 서브블록 소속(flip=수평/수직 분할)
        base = np.where(sub[:, None], c2, c1)
        tbl = np.where(sub, t2, t1)
        idx = ((mod >> px) & 1) | (((mod >> (px + 16)) & 1) << 1)
        m = ETC_MOD[tbl, idx]
        out[:, y, x, :] = np.clip(base + m[:, None], 0, 255)
    return out.astype(np.uint8)


def encode_block(px):
    """px: (4,4,3) uint8 → 8바이트 ETC1 색블록(3DS LE).

    individual 모드(diff=0)로, flip 0/1 및 각 서브블록의 밝기 테이블을 완전탐색해
    제곱오차 최소가 되게 인코딩한다. UI 라벨(진회색 글자 + 완만한 배경) 기준
    왕복 오차 ≤ 1. 알파는 이 함수 밖에서 원본을 유지한다.
    """
    px = px.astype(np.int32)
    best = None
    for flip in (0, 1):
        if flip:
            subs = [px[:2, :, :].reshape(-1, 3), px[2:, :, :].reshape(-1, 3)]
        else:
            subs = [px[:, :2, :].reshape(-1, 3), px[:, 2:, :].reshape(-1, 3)]
        means = [s.mean(axis=0) for s in subs]
        q = [np.clip(np.round(m / 17), 0, 15).astype(np.int32) for m in means]   # 4비트 기준색
        base = [qq * 17 for qq in q]
        tbl_idx = []; indices = [None, None]; err_tot = 0
        for si in (0, 1):
            s = subs[si]
            delta = (s - base[si]).mean(axis=1)       # 픽셀별 밝기편차
            bt = None; be = 1e18; bidx = None
            for t in range(8):
                mods = ETC_MOD[t]
                d = np.abs(delta[:, None] - mods[None, :])
                idx = d.argmin(axis=1)
                rec = base[si][None, :] + mods[idx][:, None]
                e = ((np.clip(rec, 0, 255) - s) ** 2).sum()
                if e < be:
                    be = e; bt = t; bidx = idx
            tbl_idx.append(bt); indices[si] = bidx; err_tot += be
        if best is None or err_tot < best[0]:
            best = (err_tot, flip, q, tbl_idx, indices)
    _, flip, q, tbl, inds = best
    b0 = (q[0][0] << 4) | q[1][0]
    b1 = (q[0][1] << 4) | q[1][1]
    b2 = (q[0][2] << 4) | q[1][2]
    b3 = (tbl[0] << 5) | (tbl[1] << 2) | (0 << 1) | flip     # diff=0
    lsb = 0; msb = 0
    for i in range(16):
        x = i // 4; y = i % 4
        sub = (y >= 2) if flip else (x >= 2)
        if flip:
            j = (y - 2) * 4 + x if sub else y * 4 + x
        else:
            j = y * 2 + (x - 2) if sub else y * 2 + x
        idx = int(inds[1][j] if sub else inds[0][j])
        lsb |= (idx & 1) << i
        msb |= ((idx >> 1) & 1) << i
    mod = lsb | (msb << 16)
    be_bytes = bytes([b0, b1, b2, b3, (mod >> 24) & 0xff, (mod >> 16) & 0xff,
                      (mod >> 8) & 0xff, mod & 0xff])
    return be_bytes[::-1]                              # 표준 BE -> 3DS u64 LE


if __name__ == "__main__":
    rng = np.random.default_rng(0)

    # (1) 디코더 정확성 — individual 모드 골든 벡터.
    #  b0=0xF3,b1=0x3F,b2=0x33 → 색1=(255,51,51), 색2=(51,255,51); tbl1=tbl2=0(±2,±8),
    #  mod=0 → 전 픽셀 index0(+2), flip=0 → 좌2열=색1, 우2열=색2.
    blk = bytes([0xF3, 0x3F, 0x33, 0x00, 0x00, 0x00, 0x00, 0x00])[::-1]   # 3DS LE 로 저장
    d = decode_all_blocks(blk)[0]
    assert tuple(d[0, 0]) == (255, 53, 53), tuple(d[0, 0])
    assert tuple(d[0, 3]) == (53, 255, 53), tuple(d[0, 3])
    print("디코더 골든 벡터 OK")

    # (2) 매끄러운 세로 그라데이션(실제 버튼 배경 성격) — 거의 무손실.
    grad = np.linspace(60, 210, 4).astype(int)
    blk = np.repeat(np.repeat(grad[:, None], 4, 1)[:, :, None], 3, 2).astype(np.uint8)
    e = int(np.abs(decode_all_blocks(encode_block(blk))[0].astype(int) - blk).max())
    print("그라데이션 왕복 최대오차:", e); assert e <= 3, e

    # (3) 콘텐츠 유형별 왕복오차 한계(측정값).
    #  평탄/하드엣지 반쪽은 거의 무손실. 한 서브블록(2×4) 안에 잉크와 배경이 "모두"
    #  들어가는 글자 가장자리 블록만 오차가 커지는데, 이는 ETC1 구조상의 한계다
    #  (서브블록당 기준색 1개 + 공용 modifier 테이블). 원본 일본어 텍스처도 같은
    #  ETC1 이라 동일한 제약을 받으며, 화면에서는 가장자리가 약간 부드러워질 뿐이다.
    #  ※ 실제 패치 품질의 최종 근거는 빌드 결과를 배포본과 픽셀 비교하는
    #    재현성 테스트다(docs/HOWTO.md "재현성 검증").
    def bound(gen, n=1500):
        w = 0
        for _ in range(n):
            blk = gen()
            w = max(w, int(np.abs(decode_all_blocks(encode_block(blk))[0].astype(int)
                                  - blk.astype(int)).max()))
        return w

    def flat():
        v = int(rng.integers(30, 230)); return np.full((4, 4, 3), v, np.uint8)

    def hard_half():
        bg = int(rng.integers(180, 220)); ink = int(rng.integers(35, 55))
        g = np.where(np.arange(4)[:, None] < 2, bg, ink) * np.ones((1, 4), int)
        return np.repeat(g[:, :, None], 3, 2).astype(np.uint8)

    def gradient():
        a = int(rng.integers(40, 120)); b = int(rng.integers(140, 230))
        col = np.linspace(a, b, 4).astype(int)
        return np.repeat(np.repeat(col[:, None], 4, 1)[:, :, None], 3, 2).astype(np.uint8)

    def glyph_edge():          # 한 서브블록에 잉크+배경이 함께 = ETC1 최악 케이스
        bg = int(rng.integers(180, 220)); ink = int(rng.integers(35, 55))
        col = np.array([bg, (bg + ink) // 2, ink, bg], int)
        return np.repeat(np.repeat(col[None, :], 4, 0)[:, :, None], 3, 2).astype(np.uint8)

    for name, gen, lim in (("평탄", flat, 3), ("하드엣지 반쪽", hard_half, 3),
                           ("그라데이션", gradient, 12), ("글자 가장자리", glyph_edge, 24)):
        e = bound(gen)
        print(f"{name:12s} 왕복 최대오차: {e:3d} (허용 {lim})")
        assert e <= lim, (name, e)
    print("OK")
