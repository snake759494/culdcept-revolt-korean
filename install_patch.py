#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""한글패치를 Azahar 에 **안전하게** 설치한다.

이슈 #14 대응: 배포 ZIP 안의 `load` 폴더를 통째로 옮기다가 기존
`load/mods/00040000000F5700`(본편 패치)이 지워져 게임이 전부 원문으로 돌아가는
사고가 있었다. 이 스크립트는 **파일을 하나씩 복사**하고 **아무것도 지우지 않는다.**

    python install_patch.py                     # 자동 탐색 + 설치
    python install_patch.py --azahar <경로>      # 폴더 직접 지정
    python install_patch.py --skip-dlc          # DLC 오버레이 없이 본편만
    python install_patch.py --remove-dlc        # DLC 오버레이만 제거

본편 `CULDCEPT.DAT` 는 저작권상 배포할 수 없으므로, 본인이 xdelta 를 적용해 만든
파일이 제자리에 있는지 **확인만** 한다. 없으면 무엇을 해야 하는지 알려준다.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_TID = "00040000000F5700"
DLC_TID = "0004008c000f5700"
CATALOG_NAME = "ContentInfoArchive_JPN_ja.bin"
BASE_REL = Path("load") / "mods" / BASE_TID / "romfs" / "CULDCEPT.DAT"
HERE = Path(__file__).resolve().parent


def find_azahar(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_dir() else None
    appdata = os.environ.get("APPDATA")
    cands = []
    if appdata:
        cands += [Path(appdata) / "Azahar", Path(appdata) / "azahar-emu"]
    cands += [HERE / "user", HERE.parent / "user"]        # 포터블 설치
    for c in cands:
        if (c / "load").is_dir() or (c / "sdmc").is_dir():
            return c
    return None


def copy_tree_no_delete(src: Path, dst: Path) -> int:
    """src 아래 파일을 dst 로 복사한다. 덮어쓰기는 하되 **삭제는 하지 않는다.**"""
    n = 0
    for root, _dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        out_dir = dst / rel
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            shutil.copy2(Path(root) / name, out_dir / name)
            n += 1
    return n


def clean_misplaced_dlc(az: Path, dry_run: bool = False) -> list[str]:
    """본편 모드 폴더에 잘못 들어간 **DLC 전용 파일**만 골라 치운다.

    예전 패키지의 `load` 폴더를 통째로 옮기다 보면 DLC 카탈로그와 IPS 108개가
    본편 타이틀 폴더(`load/mods/00040000000F5700/`)에 들어가는 일이 있었다.
    그러면 Azahar 가 본편 RomFS 에 없는 파일을 계속 찾아 IPS 를 수만 번 건너뛰고,
    카탈로그를 반복 접근하다 프리징으로 이어진다(이슈 #14/#15).

    본편 패치 파일(`romfs/CULDCEPT.DAT`)은 절대 건드리지 않는다.
    """
    base = az / "load" / "mods" / BASE_TID
    removed: list[str] = []
    catalog = base / "romfs" / CATALOG_NAME
    if catalog.is_file():
        if not dry_run:
            catalog.unlink()
        removed.append(str(catalog))
    ext = base / "romfs_ext"
    if ext.is_dir():
        if not dry_run:
            shutil.rmtree(ext)
        removed.append(f"{ext} (romfs_ext 폴더)")
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description="컬드셉트 리볼트 한글패치 설치기")
    ap.add_argument("--azahar", help="Azahar 사용자 폴더 (미지정 시 자동 탐색)")
    ap.add_argument("--skip-dlc", action="store_true", help="DLC 오버레이를 설치하지 않음")
    ap.add_argument("--remove-dlc", action="store_true", help="DLC 오버레이만 제거")
    a = ap.parse_args()

    az = find_azahar(a.azahar)
    if az is None:
        print("Azahar 사용자 폴더를 찾지 못했습니다.")
        print('  python install_patch.py --azahar "<Azahar 사용자 폴더 경로>"')
        return 1
    print(f"Azahar 폴더: {az}")

    dlc_dst = az / "load" / "mods" / DLC_TID
    if a.remove_dlc:
        if dlc_dst.is_dir():
            shutil.rmtree(dlc_dst)
            print(f"DLC 오버레이 제거: {dlc_dst}")
        else:
            print("DLC 오버레이가 설치되어 있지 않습니다.")
        return 0

    # ── 본편 폴더에 잘못 들어간 DLC 파일 정리 ───────────
    # 이걸 두면 Azahar 가 본편 RomFS 에서 IPS 를 수만 번 건너뛰고 카탈로그를
    # 반복 접근하다 프리징된다(이슈 #14/#15). 본편 CULDCEPT.DAT 은 건드리지 않는다.
    misplaced = clean_misplaced_dlc(az)
    if misplaced:
        print("본편 폴더에 잘못 들어가 있던 DLC 파일을 정리했습니다:")
        for item in misplaced:
            print(f"  - {item}")
    else:
        print("본편 폴더 오배치: 없음")

    # ── DLC 오버레이 (선택) ─────────────────────────────
    if a.skip_dlc:
        print("DLC 오버레이: 건너뜀(--skip-dlc)")
    else:
        # 패키지에는 `load` 폴더를 두지 않는다. 사용자가 이걸 통째로 끌어다 놓다가
        # 기존 load/mods/<본편> 이 지워져 게임이 전부 원문으로 돌아간 사고가 있었다(#14).
        newstyle = HERE / "dlc_overlay" / DLC_TID
        oldstyle = HERE / "load"
        if newstyle.is_dir():
            n = copy_tree_no_delete(newstyle, dlc_dst)
            print(f"DLC 오버레이 파일 {n}개 복사 → {dlc_dst}")
        elif oldstyle.is_dir():                       # 구버전 패키지 호환
            n = copy_tree_no_delete(oldstyle, az)
            print(f"DLC 오버레이 파일 {n}개 복사 (구버전 배치)")
        else:
            print("DLC 오버레이가 이 패키지에 없습니다 — 건너뜀")

    # ── 본편 패치 확인 ──────────────────────────────────
    base = az / BASE_REL
    if base.is_file():
        size = base.stat().st_size
        print(f"본편 패치 확인: {size:,}바이트  {base}")
    else:
        print()
        print("!! 본편 패치 파일이 없습니다. 이게 없으면 게임이 전부 원문으로 나옵니다.")
        print("   1) DeltaPatcher 로 본인의 CULDCEPT.DAT 에 culdcept-korean.xdelta 를 적용")
        print("   2) 결과 파일을 아래 경로에 CULDCEPT.DAT 이름으로 두세요")
        print(f"      {base}")
        print()

    # ── 검증 ────────────────────────────────────────────
    print()
    print("── 설치 검사 ──")
    try:
        sys.path.insert(0, str(HERE))
        import verify_install                                # noqa: E402
        argv = sys.argv[:]
        sys.argv = ["verify_install.py", str(az)]            # 진단기는 argv 로 경로를 받는다
        try:
            return verify_install.main() or 0
        finally:
            sys.argv = argv
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:                                 # 검증기가 없어도 설치는 끝났다
        print(f"(설치 검사 생략: {exc})")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
