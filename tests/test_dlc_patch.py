import unittest
from pathlib import Path

from apply_dlc_korean import (
    encode_resource_title,
    make_ips_patch,
    output_resource_path,
    patch_resource_title,
)
from verify_dlc_patch import apply_ips


class DlcPatchTests(unittest.TestCase):
    def test_ips_round_trip_preserves_resource(self):
        source = bytes(range(64))
        target = source[:0x10] + b"KOREAN" + source[0x16:]
        patch = make_ips_patch(source, target)
        self.assertTrue(patch.startswith(b"PATCH"))
        self.assertTrue(patch.endswith(b"EOF"))
        self.assertEqual(apply_ips(source, patch), target)

    def test_resource_title_uses_fixed_wansung_codes(self):
        mapping = {"글": 0x889F, "한": 0x88A0, "꽃": 0x88A1}
        encoded = encode_resource_title("한글·꽃", mapping)
        self.assertEqual(len(encoded), 8)
        self.assertEqual(encoded[:4], b"\x88\xA0\x88\x9F")
        self.assertEqual(encoded[4:6], "・".encode("shift_jis"))
        self.assertEqual(encoded[6:], b"\x88\xA1")

    def test_resource_patch_only_changes_title_field(self):
        source = bytearray(b"header" * 20)
        source[0x10:0x2B] = "日本語".encode("shift_jis").ljust(0x1B, b"\0")
        source[0x2B] = 0x30
        original_tail = bytes(source[0x2B:])
        mapping = {"한": 0x889F, "글": 0x88A0}
        target = patch_resource_title(bytes(source), "한글", mapping)
        self.assertEqual(target[0x2B:], original_tail)
        self.assertEqual(target[0x2B], 0x30)
        self.assertEqual(target[0x10:0x18], b"\x88\x9F\x88\xA0\0\0\0\0")

    def test_resource_title_cannot_reach_payload_offset(self):
        self.assertEqual(encode_resource_title("A" * 26, {}), b"A" * 26)
        with self.assertRaisesRegex(ValueError, "exceeds 26 bytes"):
            encode_resource_title("A" * 27, {})

    def test_resource_output_uses_romfs_ext_and_ips_suffix(self):
        path = output_resource_path(Path("overlay"), "/nested/dice.dld")
        self.assertEqual(str(path).replace("\\", "/"), "overlay/load/mods/0004008c000f5700/romfs_ext/nested/dice.dld.ips")


if __name__ == "__main__":
    unittest.main()
