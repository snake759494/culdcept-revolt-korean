#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""한글패치 통합 빌드 — 본인의 CULDCEPT.DAT 하나로 패치본을 만든다.

    python build.py <원본 CULDCEPT.DAT> <출력 CULDCEPT.DAT> [--font TTF]

단계:
  1) 텍스트   apply_korean_full.py  — 스토리 대사·카드DB·캐릭터 대사·UI + 한글 폰트 글리프
  2) UI 이미지 apply_ui_images.py    — 메뉴/필터/커맨드 버튼 (ETC1 텍스처)
  3) 나레이션 apply_narration.py     — 양피지 가이드 텍스처 **(선택, code.bin 필요)**

1·2 단계는 이 저장소의 툴만으로 완결된다. 3 단계는 0x0d(커스텀 LZMA) 엔트리를
풀어야 해서 게임 code.bin 기반 디코더가 필요하다(저작권상 미배포, docs/HOWTO.md 참고).
--narration-decoder 로 디코더 모듈을 주면 자동으로 3단계까지 수행한다.

xdelta 패치를 만들려면 --xdelta 를 주면 된다(xdelta3 실행파일 필요).
"""
import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _load(path):
    spec = importlib.util.spec_from_file_location("narr_decoder", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser(description="컬드셉트 리볼트 한글패치 통합 빌드")
    ap.add_argument("infile", help="본인의 원본 CULDCEPT.DAT")
    ap.add_argument("outfile", help="출력 경로")
    ap.add_argument("--font", default=None, help="한글 TTF (fonts/README.md 참고)")
    ap.add_argument("--narration-decoder", default=None, metavar="PY",
                    help="0x0d 디코더 모듈(.py). decompress(bytes)->bytes 를 제공해야 함")
    ap.add_argument("--skip-images", action="store_true", help="UI 이미지 단계 건너뛰기")
    ap.add_argument("--xdelta", metavar="OUT.xdelta", default=None,
                    help="원본 대비 xdelta 패치도 생성")
    ap.add_argument("--xdelta-bin", default="xdelta3", help="xdelta3 실행파일 (기본: xdelta3)")
    a = ap.parse_args()

    if not os.path.exists(a.infile):
        sys.exit(f"원본을 찾을 수 없습니다: {a.infile}")

    tmpd = tempfile.mkdtemp(prefix="culdcept_build_")
    try:
        stage_in = a.infile
        # ── 1) 텍스트 ────────────────────────────────────────────────
        print("[1/3] 텍스트(대사·카드·UI) + 한글 폰트 …")
        stage_out = os.path.join(tmpd, "s1.DAT")
        cmd = [sys.executable, os.path.join(HERE, "apply_korean_full.py"), stage_in, stage_out]
        if a.font:
            cmd += ["--font", a.font]
        subprocess.run(cmd, check=True)
        stage_in = stage_out

        # ── 2) UI 이미지 ─────────────────────────────────────────────
        if not a.skip_images:
            print("[2/3] UI 버튼 이미지(ETC1 텍스처) …")
            stage_out = os.path.join(tmpd, "s2.DAT")
            cmd = [sys.executable, os.path.join(HERE, "apply_ui_images.py"), stage_in, stage_out]
            if a.font:
                cmd += ["--font", a.font]
            subprocess.run(cmd, check=True)
            stage_in = stage_out
        else:
            print("[2/3] UI 이미지 — 건너뜀")

        # ── 3) 나레이션(선택) ────────────────────────────────────────
        if a.narration_decoder:
            print("[3/3] 나레이션 텍스처 …")
            dec = _load(a.narration_decoder)
            if not hasattr(dec, "decompress"):
                sys.exit("디코더 모듈에 decompress(bytes)->bytes 가 없습니다.")
            if a.font:                       # 빈 문자열을 넣으면 기본 경로가
                os.environ["KR_FONT"] = a.font   # 무력화되므로 지정됐을 때만 설정
            import apply_narration
            stage_out = os.path.join(tmpd, "s3.DAT")
            apply_narration.main(stage_in, stage_out, dec.decompress)
            stage_in = stage_out
        else:
            print("[3/3] 나레이션 — 건너뜀 (code.bin 디코더 미지정, docs/HOWTO.md 참고)")

        shutil.copyfile(stage_in, a.outfile)
        print(f"\n완료 → {a.outfile}  ({os.path.getsize(a.outfile):,} 바이트)")

        if a.xdelta:
            print("xdelta 패치 생성 …")
            subprocess.run([a.xdelta_bin, "-e", "-f", "-S", "djw",
                            "-s", a.infile, a.outfile, a.xdelta], check=True)
            print(f"xdelta → {a.xdelta}  ({os.path.getsize(a.xdelta):,} 바이트)")
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)

    print("\nLayeredFS 사용법: 에뮬레이터의")
    print("  load/mods/00040000000F5700/romfs/CULDCEPT.DAT")
    print("경로에 결과 파일을 두세요.")


if __name__ == "__main__":
    main()
