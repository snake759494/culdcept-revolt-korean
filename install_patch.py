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
import hashlib
import os
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_TID = "00040000000F5700"
UPDATE_TID = "0004000e000f5700"
DLC_TID = "0004008c000f5700"
UPDATE_IPS = "update_code_ko.ips"
# 게임 업데이트(ver 1.2) 실행코드를 BLZ 해제한 것의 해시. 이 IPS 는 이 코드에만 맞는다.
UPDATE_CODE_SHA256 = "4b21f19242488e28b68dffdf29b65f8af32be2a58431a5031edaa8e8c74af6e1"
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


def clean_previous_install(az: Path, dry_run: bool = False) -> list[str]:
    """이전 설치 흔적을 **처음부터 다시 깔 수 있게** 지운다(이슈 #17).

    지우는 것은 우리가 만든 오버레이뿐이다.

    * `load/mods/<DLC 타이틀>/`      — DLC 오버레이 전체(카탈로그 + IPS)
    * `mods/<타이틀>/`               — `load/` 없이 쓰던 옛 경로의 잔재

    사용자의 본편 패치 파일(`load/mods/<본편>/romfs/CULDCEPT.DAT`)은 본인이 xdelta
    로 만든 것이라 다시 만들 수 없으므로 **절대 지우지 않는다.**
    """
    removed: list[str] = []
    targets = [az / "load" / "mods" / DLC_TID,
               az / "mods" / BASE_TID,
               az / "mods" / DLC_TID]
    for target in targets:
        if target.is_dir():
            if not dry_run:
                shutil.rmtree(target)
            removed.append(str(target))
    return removed


def find_installed_update(az: Path) -> Path | None:
    """가상 SD 에 설치된 게임 업데이트(0004000e000f5700)의 .app 을 찾는다."""
    sd = az / "sdmc" / "Nintendo 3DS"
    if not sd.is_dir():
        return None
    for id0 in sd.iterdir():
        if not id0.is_dir():
            continue
        for id1 in id0.iterdir():
            content = id1 / "title" / "0004000e" / "000f5700" / "content"
            if not content.is_dir():
                continue
            apps = sorted(p for p in content.rglob("*.app") if p.is_file())
            if apps:
                return max(apps, key=lambda p: p.stat().st_size)
    return None


def install_update_code(az: Path) -> str:
    """업데이트 실행코드 안의 **카드 DB** 를 한글로 바꿔 ExeFS 오버라이드로 깐다.

    v1.2 업데이트에는 RomFS 가 없고 `.code` 만 있는데, 그 안에 카드 이름·능력·설명이
    통째로 들어 있다. 업데이트를 깔면 게임은 카드 텍스트를 CULDCEPT.DAT 이 아니라
    이 실행코드에서 읽으므로, DAT 만 한글화하면 **카드만 원문으로 남는다**(이슈 #17).

    업데이트가 없으면 오버라이드도 두지 않는다. 업데이트 없이 업데이트용 코드를
    얹으면 실행 이미지가 어긋난다.
    """
    exefs = az / "load" / "mods" / BASE_TID / "exefs"
    target = exefs / "code.bin"
    app = find_installed_update(az)
    if app is None:
        if target.is_file():
            target.unlink()
            try:
                exefs.rmdir()
            except OSError:
                pass
            return "게임 업데이트가 없어 실행코드 오버라이드를 제거했습니다."
        return "게임 업데이트: 설치되어 있지 않음 — 실행코드 패치 불필요"

    ips_path = HERE / UPDATE_IPS
    if not ips_path.is_file():
        return f"게임 업데이트를 찾았지만 {UPDATE_IPS} 가 패키지에 없습니다 — 건너뜀"

    try:
        import apply_update_code as upd
        code = upd.extract_code(app)
    except Exception as exc:                     # noqa: BLE001 - 사용자에게 이유를 보여준다
        return f"업데이트 실행코드를 읽지 못했습니다: {exc}"

    digest = hashlib.sha256(code).hexdigest()
    if digest != UPDATE_CODE_SHA256:
        cont = chr(92)                       # 줄 이음 문자
        hint = [
            "설치된 게임 업데이트가 이 패치가 아는 판(ver 1.2)과 다릅니다.",
            "     본인 파일로 직접 만들려면:",
            "       python apply_update_code.py --dat 원본/CULDCEPT.DAT " + cont,
            '           --update "%s" ' % app + cont,
            '           --out "%s"' % target,
        ]
        return chr(10).join(hint)

    patched = upd.apply_ips_patch(code, ips_path.read_bytes())
    exefs.mkdir(parents=True, exist_ok=True)
    target.write_bytes(patched)
    return f"업데이트 실행코드 카드 DB 한글화 → {target} ({len(patched):,}바이트)"


def main() -> int:
    ap = argparse.ArgumentParser(description="컬드셉트 리볼트 한글패치 설치기")
    ap.add_argument("--azahar", help="Azahar 사용자 폴더 (미지정 시 자동 탐색)")
    ap.add_argument("--skip-dlc", action="store_true", help="DLC 오버레이를 설치하지 않음")
    ap.add_argument("--remove-dlc", action="store_true", help="DLC 오버레이만 제거")
    ap.add_argument("--keep-old", action="store_true",
                    help="이전 설치를 지우지 않고 덮어쓰기만 함(기본은 깨끗이 다시 설치)")
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

    # ── 이전 설치 정리(기본 동작) ───────────────────────
    # 버전을 거듭하며 폴더가 뒤섞여 무엇이 적용 중인지 알 수 없게 되는 일이
    # 반복됐다(이슈 #17). 기본적으로 우리가 깐 오버레이를 먼저 싹 지우고 새로
    # 깐다. 본편 CULDCEPT.DAT 은 사용자 자산이므로 건드리지 않는다.
    if not a.keep_old:
        wiped = clean_previous_install(az)
        if wiped:
            print("이전 설치 정리:")
            for item in wiped:
                print(f"  - {item}")
        else:
            print("이전 설치: 없음")

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

    # ── 게임 업데이트(ver 1.2) 실행코드 ─────────────────
    print(install_update_code(az))

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
