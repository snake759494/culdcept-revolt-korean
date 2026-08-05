# -*- coding: utf-8 -*-
"""0x0d / 0x8d (커스텀 LZMA) 엔트리 디코더 — 게임 code.bin 을 Unicorn 으로 에뮬레이션.

CULDCEPT.DAT 의 0x0d/0x8d 엔트리는 표준 LZMA 로 풀리지 않는 커스텀 변형이다.
비트 디코더 자체는 표준 LZMA(11비트 확률, move 5, top 1<<24)이지만 심볼 구조가
달라서, 가장 확실한 방법은 게임의 디컴프레서 함수를 그대로 실행하는 것이다.

  * 디컴프레서 함수 : 0x00275080 (vaddr)  — 코덱 함수 포인터 테이블 0x39bb8c 에 등록
  * 인자 : r0 = { u32 src; u32 src_end; u32 refill_fn; } 구조체 포인터
           r1 = 출력 버퍼 포인터
  * 헤더 : [varint 해제크기][2바이트 props][4바이트 BE 초기 code]

code.bin 은 게임 소유자가 본인 롬에서 추출해야 한다(저작권상 미배포).
추출 방법은 docs/HOWTO.md 참고.
"""
import os
import struct

from unicorn import *
from unicorn.arm_const import *

BASE = 0x00100000          # .code 로드 주소
FUNC = 0x00275080          # 디컴프레서
STACK = 0x70000000
STACK_SZ = 0x100000
SRC = 0x80000000
DST = 0x90000000
CTX = 0xA0000000
RET = 0xDEAD0000           # 복귀 감지용 매직


SRC_SZ = 0x400000          # 입력/출력 영역은 한 번만 매핑하고 재사용(속도)
DST_SZ = 0x1000000


class Decoder:
    """code.bin 을 한 번만 매핑해두고 여러 엔트리를 반복 해제한다."""

    def __init__(self, code_bin_path):
        self.code = open(code_bin_path, "rb").read()
        uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        # VFP 활성화 (함수가 s0/s1 을 스크래치로 쓴다)
        uc.reg_write(UC_ARM_REG_C1_C0_2, uc.reg_read(UC_ARM_REG_C1_C0_2) | (0xF << 20))
        uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        csz = (len(self.code) + 0xFFF) & ~0xFFF
        uc.mem_map(BASE, csz)
        uc.mem_write(BASE, self.code)
        uc.mem_map(STACK, STACK_SZ)
        uc.mem_map(SRC, SRC_SZ)
        uc.mem_map(DST, DST_SZ)
        uc.mem_map(CTX, 0x1000)
        self.uc = uc

    def decompress(self, entry: bytes, out_size: int = None) -> bytes:
        """0x0d/0x8d 엔트리 전체(타입 바이트 포함) → 압축 해제된 바이트."""
        if entry[0] not in (0x0D, 0x8D):
            raise ValueError(f"0x0d/0x8d 가 아님: 0x{entry[0]:02x}")
        if out_size is None:
            out_size = _varint(entry, 1)[0]
        src = entry[1:] + b"\x00" * 64                 # 타입 바이트 제외, 여유 패딩
        if len(src) > SRC_SZ or out_size > DST_SZ:
            raise ValueError("입출력이 매핑 크기를 초과")
        uc = self.uc
        uc.mem_write(SRC, src)
        # 컨텍스트 구조체: {src, src_end, refill_fn}
        uc.mem_write(CTX, struct.pack("<III", SRC, SRC + len(src), RET))
        uc.reg_write(UC_ARM_REG_R0, CTX)
        uc.reg_write(UC_ARM_REG_R1, DST)
        uc.reg_write(UC_ARM_REG_SP, STACK + STACK_SZ - 0x1000)
        uc.reg_write(UC_ARM_REG_LR, RET)
        try:
            uc.emu_start(FUNC, RET, timeout=0, count=0)
        except UcError as e:
            pc = uc.reg_read(UC_ARM_REG_PC)
            if pc != RET:
                raise RuntimeError(f"에뮬 오류 {e} @pc=0x{pc:08x}")
        return bytes(uc.mem_read(DST, out_size))


def _varint(d, i):
    """게임의 varint(부호 연장 종료 비트 방식) — 0x2747f8 구현과 동일."""
    b0 = d[i]; b1 = d[i + 1]
    v = ((b0 << 8) | b1) & 0xFFFFFFFF
    if not (b0 & 0x80):
        return v, i + 2
    v &= 0x7FFF
    b2 = d[i + 2]
    v |= (b2 & 0x7F) << 15
    if not (b2 & 0x80):
        return v, i + 3
    v &= 0x3FFFFF
    v |= d[i + 3] << 22
    return v, i + 4
