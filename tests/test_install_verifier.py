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

    def test_catalog_only_install_is_accepted(self):
        temp, root = self._make_user_dir()
        try:
            checks = inspect_install(root)
            by_label = {check.label: check for check in checks}
            self.assertEqual(by_label["DLC 카탈로그"].status, "O")
            self.assertEqual(by_label["DLC 직접 리소스 IPS"].status, "O")
            self.assertIn("호환(카탈로그 전용)", by_label["DLC 직접 리소스 IPS"].detail)
            self.assertEqual(by_label["실제 DLC 설치"].status, "O")
        finally:
            temp.cleanup()

    def test_full_install_requires_exactly_108_ips(self):
        temp, root = self._make_user_dir(full_mode=True)
        try:
            checks = inspect_install(root)
            by_label = {check.label: check for check in checks}
            self.assertEqual(by_label["DLC 직접 리소스 IPS"].status, "O")
            self.assertIn("전체 모드", by_label["DLC 직접 리소스 IPS"].detail)
        finally:
            temp.cleanup()

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

    def test_rotated_log_reports_repeated_catalog_loop(self):
        temp, root = self._make_user_dir()
        try:
            log = root / "log" / "azahar_log.old.txt"
            repeated = "".join(
                "LayeredFS replacement file in use for /ContentInfoArchive_JPN_ja.bin\n"
                for _ in range(60)
            )
            log.write_text(repeated + "Cleaning up process 11\n", encoding="utf-8")
            checks = inspect_install(root)
            by_label = {check.label: check for check in checks}
            self.assertEqual(by_label["Azahar 로그"].status, "!")
            self.assertIn("프리징 의심", by_label["Azahar 로그"].detail)
        finally:
            temp.cleanup()

    def test_malformed_ips_are_reported(self):
        temp, root = self._make_user_dir(full_mode=True)
        try:
            bad = root / "load" / "mods" / "0004008c000f5700" / "romfs_ext" / "resource_000.ips"
            bad.write_bytes(b"not-an-ips")
            checks = inspect_install(root)
            by_label = {check.label: check for check in checks}
            self.assertEqual(by_label["DLC 직접 리소스 IPS"].status, "X")
        finally:
            temp.cleanup()

    def test_legacy_ips_that_overwrites_payload_offset_is_reported(self):
        temp, root = self._make_user_dir(full_mode=True)
        try:
            bad = root / "load" / "mods" / "0004008c000f5700" / "romfs_ext" / "resource_000.dld.ips"
            bad.write_bytes(b"PATCH\x00\x00\x2b\x00\x01\x00EOF")
            checks = inspect_install(root)
            by_label = {check.label: check for check in checks}
            self.assertEqual(by_label["DLC 직접 리소스 IPS"].status, "X")
            self.assertIn("0x2B", by_label["DLC 직접 리소스 IPS"].detail)
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

    def test_missing_uninstalled_resource_is_not_a_patch_failure(self):
        temp, root = self._make_user_dir()
        try:
            log = root / "log" / "azahar_log.txt"
            log.write_text(
                "LayeredFS original file for patch /unused.dld.ips not found\n"
                "LayeredFS patched file /installed.dld\n",
                encoding="utf-8",
            )
            checks = inspect_install(root)
            by_label = {check.label: check for check in checks}
            self.assertNotEqual(by_label["Azahar 로그"].status, "X")
            self.assertIn("건너뜀", by_label["Azahar 로그"].detail)
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()


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


class CatalogEncodingTests(unittest.TestCase):
    """이슈 #19/#20: 한글을 그대로 쓴 카탈로그는 DLC 목록을 통째로 날린다."""

    def _catalog(self, text: str) -> bytes:
        from verify_install import (CATALOG_FIELDS, CATALOG_RECORD_BASE,
                                    CATALOG_RECORD_STRIDE, EXPECTED_CATALOG_SIZE)

        data = bytearray(EXPECTED_CATALOG_SIZE)
        struct.pack_into("<II", data, 0, 1, 108)
        for index in range(108):
            record = CATALOG_RECORD_BASE + index * CATALOG_RECORD_STRIDE
            for offset, size in CATALOG_FIELDS:
                encoded = text.encode("utf-8")[:size - 1]
                data[record + offset:record + offset + size] = encoded.ljust(size, b"\0")
        return bytes(data)

    def _check(self, text: str):
        from verify_install import _check_catalog

        temp = tempfile.TemporaryDirectory()
        with temp:
            root = Path(temp.name)
            romfs = root / "load" / "mods" / "0004008c000f5700" / "romfs"
            romfs.mkdir(parents=True)
            (romfs / "ContentInfoArchive_JPN_ja.bin").write_bytes(self._catalog(text))
            return _check_catalog(root)

    def test_hangul_catalog_is_rejected(self):
        check = self._check("브로드라인")
        self.assertEqual(check.status, "X")
        self.assertIn("Shift-JIS", check.detail)
        self.assertTrue(check.blocking)

    def test_sjis_representable_catalog_passes(self):
        # 한글 글리프가 들어앉은 한자로 적으면 변환에 성공한다.
        check = self._check("崎稽球虞昔")
        self.assertEqual(check.status, "O")


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
