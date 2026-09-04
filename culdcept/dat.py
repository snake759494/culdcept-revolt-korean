"""
CULDCEPT.DAT 아카이브 컨테이너 (컬드셉트 리볼트, 3DS).

구조
----
  헤더   : 엔트리마다 8바이트 레코드(u32 LE offset, u32 LE size)의 배열.
           엔트리 개수 = (첫 엔트리의 offset) / 8. 엔트리 데이터가 레코드 테이블
           바로 뒤에서 시작하기 때문입니다.
  엔트리 : DAT[offset : offset+size]. 엔트리의 첫 바이트는 코덱 타입입니다
           (huffman.py 참고 / 레인지 코더 타입 0x0d,0x8d). 타입 0x00은
           원시/중첩 컨테이너입니다.

이 모듈은 테이블을 파싱하고 파일을 재빌드할 뿐, 게임 데이터를 포함하지 않습니다.
"""
import struct


class Dat:
    def __init__(self, data: bytes):
        self.data = bytearray(data)
        first = struct.unpack_from("<I", self.data, 0)[0]
        self.count = first // 8
        self.table = [struct.unpack_from("<II", self.data, i * 8) for i in range(self.count)]

    def entry(self, i: int) -> bytes:
        off, size = self.table[i]
        return bytes(self.data[off:off + size])

    def entry_type(self, i: int) -> int:
        off, size = self.table[i]
        return self.data[off] if size else -1

    def replace_entry(self, i: int, new_entry: bytes) -> None:
        """레코드 i 를 `new_entry` 로 바꾼다. **들어가면 원래 자리에 그대로 쓴다.**

        원래 자리에 쓰는 이유: 뒤에 추가하고 헤더만 고치면 옛 바이트가 파일에
        그대로 남는데, 그 상태에서 게임이 **옛 자리를 읽어** 원문을 그대로
        보여 주는 일이 실제로 있었다(이슈 #26/#27 — 2장 "실력을보여라" 대사).
        헤더는 새 자리를 가리키는데 화면에는 원문이 나오는, 진단하기 어려운
        증상이다. 애초에 옛 바이트를 남기지 않으면 생기지 않는다.

        들어가지 않을 때만 뒤에 붙인다. 그 경우에도 옛 자리는 0으로 지워
        원문이 파일에 남지 않게 한다.
        """
        off, size = self.table[i]
        if len(new_entry) <= size:
            self.data[off:off + len(new_entry)] = new_entry
            if len(new_entry) < size:                      # 남는 꼬리는 0으로
                self.data[off + len(new_entry):off + size] = bytes(size - len(new_entry))
            self.table[i] = (off, len(new_entry))
            struct.pack_into("<II", self.data, i * 8, off, len(new_entry))
            return
        self.data[off:off + size] = bytes(size)            # 옛 바이트 제거
        new_off = len(self.data)
        self.data.extend(new_entry)
        self.table[i] = (new_off, len(new_entry))
        struct.pack_into("<II", self.data, i * 8, new_off, len(new_entry))

    def build(self) -> bytes:
        return bytes(self.data)


def write_entry(data: bytearray, index: int, blob: bytes) -> None:
    """`data`(파일 전체)의 엔트리 i 를 `blob` 으로 바꾼다.

    들어가면 **원래 자리에 덮어쓴다.** 안 들어가 파일 끝에 붙일 때는 **옛 바이트를
    0으로 지운다.** 헤더만 새 자리로 바꾸고 옛 바이트를 남겨 두면, 게임이 그쪽을
    읽어 원문을 그대로 보여 주는 일이 있다(이슈 #27/#28 — 카드 이름·퀘스트 대사).

    `Dat.replace_entry` 와 같은 규칙이지만, Dat 객체 없이 바이트열만 다루는
    도구(apply_ui_images.py·apply_narration.py)를 위한 것이다.
    """
    off, size = struct.unpack_from("<II", data, index * 8)
    if len(blob) <= size:
        data[off:off + len(blob)] = blob
        if len(blob) < size:
            data[off + len(blob):off + size] = bytes(size - len(blob))
        struct.pack_into("<II", data, index * 8, off, len(blob))
        return
    data[off:off + size] = bytes(size)                  # 옛 바이트 제거
    if len(data) % 16:
        data += b"\x00" * (16 - (len(data) % 16))       # 16바이트 정렬
    new_off = len(data)
    data += blob
    struct.pack_into("<II", data, index * 8, new_off, len(blob))
