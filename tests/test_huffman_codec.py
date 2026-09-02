"""타입 0x08 / 0x0c 코덱 컴프레서(compress_real) 회귀 테스트.

게임 데이터가 없어도 도는 자립 테스트만 둔다. 실제 .dlq/.DAT 대조는
_scratch/hz/t_full.py, t_dat.py 참고.
"""
import os
import random
import unittest

from culdcept import huffman


class HuffmanCodecTests(unittest.TestCase):
    TYPES = (0x08, 0x0C)

    def _roundtrip(self, data, typ, effort=2):
        entry = huffman.compress_real(data, typ, effort=effort)
        self.assertEqual(entry[0], typ)
        self.assertEqual(huffman.decompress(entry), data)
        return entry

    def test_round_trip_edge_shapes(self):
        cases = [
            b"",
            b"\x00",
            b"A",
            b"AB",
            b"AAA",
            bytes(range(256)),
            b"A" * 70000,                      # one long run -> distance 1
            bytes(range(256)) * 300,           # periodic, distance 256
            b"\x00\x01" * 20000,               # two-symbol alphabet
            b"\xff" * 3 + b"\x00" * 100000,    # > 65535 tokens after the run
        ]
        for data in cases:
            for typ in self.TYPES:
                for effort in (0, 1, 2):
                    with self.subTest(n=len(data), typ=typ, effort=effort):
                        self._roundtrip(data, typ, effort)

    def test_round_trip_random_and_structured(self):
        rng = random.Random(20260902)
        for i in range(60):
            n = rng.randint(0, 4000)
            mode = i % 4
            if mode == 0:
                data = os.urandom(n)
            elif mode == 1:
                data = bytes(rng.randrange(4) for _ in range(n))
            elif mode == 2:
                data = bytes(rng.choice(b"abcdefgh ") for _ in range(n))
            else:
                seed = os.urandom(max(1, n // 8))
                data = (seed * 9)[:n]
            for typ in self.TYPES:
                with self.subTest(i=i, typ=typ):
                    self._roundtrip(data, typ)

    def test_compresses_repetitive_data_hard(self):
        data = (b"the quick brown fox jumps over the lazy dog. " * 400)
        for typ in self.TYPES:
            entry = self._roundtrip(data, typ)
            # 전부 리터럴 인코더 대비 한 자리수 배 이상 작아야 한다
            self.assertLess(len(entry) * 10, len(huffman.compress(data, typ)))
            self.assertLess(len(entry), len(data) // 20)

    def test_never_worse_than_all_literal_by_much(self):
        """압축 불가 데이터라도 팽창은 아주 작아야 한다(테이블 오버헤드만)."""
        data = os.urandom(20000)
        for typ in self.TYPES:
            entry = self._roundtrip(data, typ)
            self.assertLess(len(entry), len(data) * 101 // 100)

    def test_matches_decoder_table_forms(self):
        """축약(단일 심볼) 테이블 경로도 실제로 타는지 확인."""
        entry = self._roundtrip(b"Z" * 5000, 0x0C)
        self.assertLess(len(entry), 40)

    def test_type_validation(self):
        with self.assertRaises(ValueError):
            huffman.compress_real(b"x", 0x0D)


if __name__ == "__main__":
    unittest.main()
