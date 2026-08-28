import unittest

from verify_cards import (
    contains_fixed_hangul,
    discover_card_records,
    japanese_char_count,
    null_offsets,
)


def card_record(english):
    jp = "カード".encode("shift_jis")
    return [jp, jp, english, jp, jp, jp, b""]


class CardVerifierTests(unittest.TestCase):
    def test_discovers_unique_cards_and_excludes_repeated_internal_records(self):
        segments = [b"", b""]
        segments += card_record(b"First Card")
        segments += card_record(b"Ring of the \nSuccubus")
        for _ in range(5):
            segments += card_record(b"Puppy Dragon")

        collectible, all_candidates = discover_card_records(segments)

        self.assertEqual(len(all_candidates), 7)
        self.assertEqual(len(collectible), 2)
        self.assertEqual(
            [segments[index] for index in collectible],
            [b"First Card", b"Ring of the \nSuccubus"],
        )

    def test_japanese_counter_uses_real_shift_jis_lead_ranges(self):
        self.assertEqual(japanese_char_count(b"ASCII\xA6text"), 0)
        self.assertGreater(japanese_char_count("日本語".encode("shift_jis")), 0)

    def test_fixed_hangul_slot_detection_preserves_character_boundaries(self):
        self.assertTrue(contains_fixed_hangul(b"A\x88\x9fB", {0x889F}))
        self.assertFalse(contains_fixed_hangul(b"A\x88\x9eB", {0x889F}))

    def test_null_offsets_compare_exact_positions(self):
        self.assertEqual(null_offsets(b"a\0bc\0"), [1, 4])
        self.assertNotEqual(null_offsets(b"a\0bc\0"), null_offsets(b"a\0b\0c"))


if __name__ == "__main__":
    unittest.main()
