import struct
import tempfile
import unittest
from pathlib import Path

from verify_install import inspect_install


class InstallVerifierTests(unittest.TestCase):
    def _make_user_dir(self, full_mode=False, custom_sdmc=False):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        base = root / "load" / "mods" / "00040000000F5700" / "romfs"
        dlc = root / "load" / "mods" / "0004008c000f5700" / "romfs"
        base.mkdir(parents=True)
        dlc.mkdir(parents=True)
        (base / "CULDCEPT.DAT").write_bytes(b"base")
        catalog = bytearray(21_808)
        struct.pack_into("<II", catalog, 0, 1, 108)
        (dlc / "ContentInfoArchive_JPN_ja.bin").write_bytes(catalog)
        if full_mode:
            ext = dlc.parent / "romfs_ext"
            ext.mkdir()
            for index in range(108):
                (ext / f"resource_{index:03d}.dld.ips").write_bytes(b"PATCHEOF")
        sdmc_root = root / ("custom-sd" if custom_sdmc else "sdmc")
        content = sdmc_root / "Nintendo 3DS" / "id0" / "id1" / "title" / "0004008c" / "000f5700" / "content" / "00000000"
        content.mkdir(parents=True)
        (content / "00000000.app").write_bytes(b"app")
        # .app 만으로는 Azahar 가 DLC 를 인식하지 못한다 — .tmd 와 티켓이 함께 있어야 한다.
        (content.parent / "00000000.tmd").write_bytes(b"tmd")
        tickets = root / "nand" / "dbs" / "ticket.db"
        tickets.mkdir(parents=True)
        (tickets / "0004008C000F5700.0004.tik").write_bytes(b"tik")
        config = root / "config"
        config.mkdir()
        settings = "use_virtual_sd=true\n"
        if custom_sdmc:
            settings += f"sdmc_directory={sdmc_root}\n"
        (config / "qt-config.ini").write_text(settings, encoding="utf-8")
        log = root / "log"
        log.mkdir()
        (log / "azahar_log.txt").write_text(
            "LayeredFS replacement file in use for /CULDCEPT.DAT\n"
            "LayeredFS patched file /dice.dld\n",
            encoding="utf-8",
        )
        return temp, root

    def test_dlc_in_base_folder_is_reported(self):
        temp, root = self._make_user_dir()
        try:
            wrong = root / "load" / "mods" / "00040000000F5700" / "romfs" / "ContentInfoArchive_JPN_ja.bin"
            wrong.write_bytes(b"wrong")
            checks = inspect_install(root)
            by_label = {check.label: check for check in checks}
            self.assertEqual(by_label["DLC의 본편 폴더 오배치"].status, "X")
        finally:
            temp.cleanup()

    def test_configured_sdmc_directory_is_scanned(self):
        temp, root = self._make_user_dir(custom_sdmc=True)
        try:
            checks = inspect_install(root)
            by_label = {check.label: check for check in checks}
            self.assertEqual(by_label["실제 DLC 설치"].status, "O")
        finally:
            temp.cleanup()

    def test_issue13_unmapped_loop_takes_priority_over_missing_resources(self):
        temp, root = self._make_user_dir()
        try:
            log = root / "log" / "azahar_log.txt"
            log.write_text(
                "LayeredFS original file for patch /unused.dld.ips not found\n"
                "HW.Memory <Error> unmapped Read32 @ 0x09E00000 at PC 0x00122204\n",
                encoding="utf-8",
            )
            checks = inspect_install(root)
            by_label = {check.label: check for check in checks}
            self.assertEqual(by_label["Azahar 로그"].status, "X")
            self.assertIn("#13", by_label["Azahar 로그"].detail)
        finally:
            temp.cleanup()

class DeepDiagnosticTests(unittest.TestCase):
    """이슈 #17: 파일은 다 있는데 게임에는 반영이 안 되는 상태를 잡아내는 검사."""

    def _dat_with_card_db(self, translated: bool) -> bytes:
        from culdcept import huffman
        from verify_install import CARD_DB_SECTIONS

        buf = bytearray(b"\x20" * 253_634)
        if not translated:
            # s0(카드 이름·능력)만 원문 가나로 채운다 = 카드 DB 미번역 상태
            label, start, length, _ = CARD_DB_SECTIONS[0]
            buf[start:start + length] = (b"\x82\xa0" * (length // 2))[:length]
        blob = huffman.compress(bytes(buf), typ=0x0c)
        count = 1200
        table = bytearray(count * 8)
        for index in range(count):
            struct.pack_into("<II", table, index * 8, count * 8, 0)
        struct.pack_into("<II", table, 1190 * 8, len(table), len(blob))
        return bytes(table) + blob

    def _user_dir(self, translated: bool):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        base = root / "load" / "mods" / "00040000000F5700" / "romfs"
        base.mkdir(parents=True)
        (base / "CULDCEPT.DAT").write_bytes(self._dat_with_card_db(translated))
        return temp, root

    def test_untranslated_card_db_is_reported(self):
        from verify_install import _check_card_db

        temp, root = self._user_dir(translated=False)
        with temp:
            check = _check_card_db(root)
        self.assertEqual(check.status, "X")
        self.assertTrue(check.blocking)
        self.assertIn("카드 이름", check.detail)

    def test_translated_card_db_passes(self):
        from verify_install import _check_card_db

        temp, root = self._user_dir(translated=True)
        with temp:
            check = _check_card_db(root)
        self.assertEqual(check.status, "O")

    def test_stale_save_state_is_flagged(self):
        import os
        import time
        from verify_install import _check_save_states

        temp, root = self._user_dir(translated=True)
        with temp:
            states = root / "states"
            states.mkdir()
            state = states / "00040000000F5700.01.cst"
            state.write_bytes(b"state")
            old = time.time() - 86_400
            os.utime(state, (old, old))
            check = _check_save_states(root)
        self.assertEqual(check.status, "!")
        self.assertIn("스테이트", check.detail)

    def test_missing_dlc_ticket_is_reported(self):
        from verify_install import _check_installed_dlc

        temp = tempfile.TemporaryDirectory()
        with temp:
            root = Path(temp.name)
            content = (root / "sdmc" / "Nintendo 3DS" / "id0" / "id1" / "title"
                       / "0004008c" / "000f5700" / "content" / "00000000")
            content.mkdir(parents=True)
            (content / "00000000.app").write_bytes(b"app")
            (content.parent / "00000000.tmd").write_bytes(b"tmd")
            check = _check_installed_dlc(root)
        self.assertEqual(check.status, "X")
        self.assertIn("티켓", check.detail)


class UpdateCodeTests(unittest.TestCase):
    """이슈 #17 진짜 원인: ver 1.2 업데이트 실행코드 안의 카드 DB."""

    def _user_dir(self, with_update: bool, override: bytes | None):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "load" / "mods" / "00040000000F5700" / "romfs").mkdir(parents=True)
        if with_update:
            content = (root / "sdmc" / "Nintendo 3DS" / "id0" / "id1" / "title"
                       / "0004000e" / "000f5700" / "content")
            content.mkdir(parents=True)
            (content / "00000001.app").write_bytes(b"update-app")
        if override is not None:
            exefs = root / "load" / "mods" / "00040000000F5700" / "exefs"
            exefs.mkdir(parents=True)
            (exefs / "code.bin").write_bytes(override)
        return temp, root

    def test_update_installed_without_korean_code_is_blocking(self):
        from verify_install import _check_update_code

        temp, root = self._user_dir(with_update=True, override=None)
        with temp:
            check = _check_update_code(root)
        self.assertEqual(check.status, "X")
        self.assertTrue(check.blocking)
        self.assertIn("카드", check.detail)

    def test_override_without_update_is_blocking(self):
        from verify_install import _check_update_code

        temp, root = self._user_dir(with_update=False, override=b"stray")
        with temp:
            check = _check_update_code(root)
        self.assertEqual(check.status, "X")

    def test_no_update_no_override_is_ok(self):
        from verify_install import _check_update_code

        temp, root = self._user_dir(with_update=False, override=None)
        with temp:
            check = _check_update_code(root)
        self.assertEqual(check.status, "O")

    def test_untranslated_card_db_in_override_is_reported(self):
        from verify_install import UPDATE_CARD_DB, _check_update_code

        start, length = UPDATE_CARD_DB
        code = bytearray(b"\x20" * (start + length))
        code[start:start + length] = (b"\x82\xa0" * (length // 2))[:length]
        temp, root = self._user_dir(with_update=True, override=bytes(code))
        with temp:
            check = _check_update_code(root)
        self.assertEqual(check.status, "X")
        self.assertIn("0%", check.detail)


class UpdateCodePatchTests(unittest.TestCase):
    def test_ips_round_trip(self):
        from apply_update_code import apply_ips_patch, make_ips_patch

        source = bytes(range(256)) * 40
        target = bytearray(source)
        target[100:110] = b"KOREANTEXT"
        target[9000:9004] = b"\xb0\xa1\xb0\xa1"
        patch = make_ips_patch(source, bytes(target))
        self.assertEqual(patch[:5], b"PATCH")
        self.assertEqual(patch[-3:], b"EOF")
        self.assertEqual(apply_ips_patch(source, patch), bytes(target))

    def test_ips_rejects_length_change(self):
        from apply_update_code import make_ips_patch

        with self.assertRaises(ValueError):
            make_ips_patch(b"abc", b"abcd")


class CatalogSjisSafeTests(unittest.TestCase):
    def test_to_sjis_safe_round_trips(self):
        from apply_dlc_korean import to_sjis_safe

        syllable_map = {"가": 0x889F, "나": 0x88A0}
        text = to_sjis_safe("가나", syllable_map)
        self.assertEqual(len(text), 2)
        text.encode("cp932")                      # 변환 가능해야 한다
        self.assertNotIn("가", text)

    def test_middle_dot_is_replaced(self):
        from apply_dlc_korean import to_sjis_safe

        to_sjis_safe("\u00b7", {}).encode("cp932")




class DlcResourceTests(unittest.TestCase):
    """이슈 #19~#22: DLC 리소스는 헤더 0x00 의 CRC 를 갱신해야 게임이 받아들인다."""

    TITLE = bytes([0x83, 0x72, 0x83, 0x8A, 0x83, 0x84, 0x81, 0x5B, 0x83, 0x68])  # ビリヤード
    BODY = bytes([0x93, 0xFA, 0x96, 0x7B, 0x8C, 0xEA, 0x00])                     # 日本語 + NUL
    KANJI = bytes([0x88, 0xA0])                                                   # 유효한 SJIS 한자

    def _resource(self):
        from culdcept import dlcres

        size = 0x30 + ((len(self.BODY) + 3) & ~3)
        raw = bytearray(size)
        struct.pack_into("<I", raw, 4, size)
        raw[9] = 1                                     # 암호화 플래그
        raw[0x10:0x10 + len(self.TITLE)] = self.TITLE
        raw[0x2B] = 0x30                               # 페이로드 오프셋
        raw[0x30:0x30 + len(self.BODY)] = self.BODY
        return dlcres.fix_crc(dlcres.encrypt(bytes(raw)))

    def test_generated_resource_is_accepted(self):
        from culdcept import dlcres

        self.assertTrue(dlcres.accepted(self._resource()))

    def test_title_change_without_crc_is_rejected(self):
        """DLC 가 통째로 사라지던 원인 — 제목만 바꾸고 CRC 를 갱신하지 않은 상태."""
        from culdcept import dlcres

        raw = bytearray(self._resource())
        raw[0x10:0x12] = self.KANJI                    # 유효한 일본어로만 바꿔도
        self.assertTrue(dlcres.title_ok(bytes(raw)))   # 글자 검사는 통과하지만
        self.assertFalse(dlcres.accepted(bytes(raw)))  # CRC 때문에 거부된다
        self.assertTrue(dlcres.accepted(dlcres.fix_crc(bytes(raw))))

    def test_encrypt_decrypt_round_trip(self):
        from culdcept import dlcres

        raw = self._resource()
        self.assertEqual(dlcres.encrypt(dlcres.decrypt(raw)), raw)

    def test_replace_strings_pads_with_space_and_fixes_crc(self):
        from culdcept import dlcres

        raw = self._resource()
        offset, original = dlcres.enum_strings(raw)[0]
        out = dlcres.replace_strings(raw, {offset: self.KANJI})
        self.assertEqual(len(out), len(raw))
        self.assertTrue(dlcres.accepted(out))
        plain = dlcres.decrypt(out)
        expected = self.KANJI + b" " * (len(original) - len(self.KANJI))
        # 널이 아니라 공백으로 채워야 뒤 문자열이 밀리지 않는다.
        self.assertEqual(plain[offset:offset + len(original)], expected)

    def test_too_long_replacement_is_refused(self):
        from culdcept import dlcres

        raw = self._resource()
        offset, original = dlcres.enum_strings(raw)[0]
        with self.assertRaises(ValueError):
            dlcres.replace_strings(raw, {offset: self.KANJI * (len(original) + 4)})

    def test_title_validator_matches_game_rules(self):
        from culdcept import dlcres

        raw = bytearray(self._resource())
        raw[0x10:0x2B] = self.KANJI * 13 + bytes(1)     # 26바이트 + NUL
        self.assertTrue(dlcres.title_ok(bytes(raw)))
        raw[0x10:0x2B] = self.KANJI * 14                # 28바이트, NUL 없음
        self.assertFalse(dlcres.title_ok(bytes(raw)))


class DlcOverlayCheckTests(unittest.TestCase):
    def test_missing_overlay_is_advisory(self):
        from verify_install import _check_catalog

        temp = tempfile.TemporaryDirectory()
        with temp:
            check = _check_catalog(Path(temp.name))
        self.assertEqual(check.status, "!")
        self.assertFalse(check.blocking)
