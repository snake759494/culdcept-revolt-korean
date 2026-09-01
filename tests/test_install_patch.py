# -*- coding: utf-8 -*-
"""설치기가 기존 파일을 지우지 않는지 검증한다(이슈 #14 재발 방지)."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install_patch", ROOT / "install_patch.py")
install_patch = importlib.util.module_from_spec(spec)
sys.modules["install_patch"] = install_patch
spec.loader.exec_module(install_patch)


def test_copy_tree_keeps_existing_files(tmp_path):
    """복사 대상에 이미 있던 파일은 남아 있어야 한다."""
    src = tmp_path / "src"
    (src / "romfs").mkdir(parents=True)
    (src / "romfs" / "new.bin").write_bytes(b"new")

    dst = tmp_path / "dst"
    (dst / "keep").mkdir(parents=True)
    (dst / "keep" / "base.DAT").write_bytes(b"base")

    n = install_patch.copy_tree_no_delete(src, dst)

    assert n == 1
    assert (dst / "romfs" / "new.bin").read_bytes() == b"new"
    # 기존 파일이 그대로 살아 있어야 한다 — v2.9 사고의 핵심
    assert (dst / "keep" / "base.DAT").read_bytes() == b"base"


def test_copy_tree_overwrites_same_name(tmp_path):
    """같은 이름은 덮어쓴다(구버전 손상 IPS 교체용)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.ips").write_bytes(b"fixed")
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "a.ips").write_bytes(b"broken")

    install_patch.copy_tree_no_delete(src, dst)

    assert (dst / "a.ips").read_bytes() == b"fixed"
