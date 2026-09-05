#!/bin/sh
# 배포 패키지(pkg/) 를 저장소 최신 파일로 갱신한다. v2.21 zip 의 구성과 같다.
set -e
cd "$(dirname "$0")"
for f in apply_dlc_dialogue.py apply_dlc_korean.py apply_dlc_text.py apply_update_code.py \
         check_running_game.py check_scene.py check_structure.py install_patch.py \
         tools_blz.py unmap.py verify_cards.py verify_patch.py verify_install.py \
         trace_source.py \
         cards_extra_ko.json cards_ko.json dlc_dialogue_ko.json dlc_ko.json dlc_text_ko.json \
         update_extra_ko.json update_ui_ko.json update_code_ko.ips LICENSE \
         verify_install.cmd 게임검사.cmd 설치.cmd 장면검사.cmd 원문추적.cmd; do
  cp -f "$f" "pkg/$f"
done
cp -f 설치안내.txt pkg/README.txt          # 배포용 설치 안내(저장소에 원본을 둔다)
rm -rf pkg/culdcept pkg/docs pkg/dlc_overlay
cp -r culdcept pkg/culdcept
rm -rf pkg/culdcept/__pycache__
cp -r docs pkg/docs
cp -r dlc_overlay pkg/dlc_overlay
echo "pkg 갱신 완료 ($(find pkg -type f | wc -l) 파일)"
