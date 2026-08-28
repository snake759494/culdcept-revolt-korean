import struct
import tempfile
import unittest
from pathlib import Path

from verify_install import inspect_install


class InstallVerifierTests(unittest.TestCase):
    def _make_user_dir(self, full_mode=False):
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
        config = root / "config"
        config.mkdir()
        (config / "qt-config.ini").write_text("use_virtual_sd=true\n", encoding="utf-8")
        log = root / "log"
        log.mkdir()
        (log / "azahar_log.txt").write_text(
            "LayeredFS replacement file in use for /CULDCEPT.DAT\n"
            "LayeredFS patched file /dice.dld\n",
            encoding="utf-8",
        )
        content = root / "sdmc" / "Nintendo 3DS" / "id0" / "id1" / "title" / "0004008c" / "000f5700" / "content" / "00000000"
        content.mkdir(parents=True)
        (content / "00000000.app").write_bytes(b"app")
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


if __name__ == "__main__":
    unittest.main()
