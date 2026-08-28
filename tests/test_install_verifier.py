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
