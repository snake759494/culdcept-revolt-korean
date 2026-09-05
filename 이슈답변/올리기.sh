#!/bin/sh
# 계정 정지가 풀린 뒤 실행한다. 이 폴더의 <이슈번호>.md 를 그 이슈에 댓글로 올린다.
#
#   sh 이슈답변/올리기.sh          # 전부
#   sh 이슈답변/올리기.sh 30 31    # 골라서
#
# 이미 올린 것을 또 올리지 않도록, 성공하면 올린기록.txt 에 남긴다.
set -e
cd "$(dirname "$0")"
LOG=올린기록.txt
touch "$LOG"

if [ $# -gt 0 ]; then
  LIST="$*"
else
  LIST=$(ls [0-9]*.md 2>/dev/null | sed 's/\.md$//' | sort -n)
fi

for n in $LIST; do
  f="$n.md"
  [ -f "$f" ] || { echo "  ! $f 없음 — 건너뜀"; continue; }
  if grep -qx "$n" "$LOG"; then
    echo "  - #$n 이미 올림 — 건너뜀"
    continue
  fi
  echo "#$n 올리는 중 …"
  if gh issue comment "$n" --body-file "$f"; then
    echo "$n" >> "$LOG"
  else
    echo "  ! #$n 실패 — 계정 상태를 먼저 확인하세요"
  fi
done
echo "끝났습니다."
