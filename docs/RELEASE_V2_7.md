# v2.7 — Azahar 프리징 분리용 호환 패키지

이 릴리즈는 이슈 #12에서 v2.6 전체 DLC 모드를 적용한 뒤 다시 프리징된 환경을
분리 진단하기 위한 호환 패키지입니다.

- `ContentInfoArchive_JPN_ja.bin` 카탈로그 108개만 포함합니다.
- `romfs_ext` 직접 리소스 IPS 108개는 제외합니다.
- 본편 카드·대사 번역은 본편 모드 폴더의 `CULDCEPT.DAT`를 계속 사용합니다.
- 직접 리소스 제목(다이스·맵·퀘스트·북·아바타)은 이 패키지에서 원문으로 남습니다.
- 원본 DLC와 본편 게임 데이터는 포함하지 않습니다.

## 적용

1. Azahar와 게임을 완전히 종료합니다.
2. 기존 `load\mods\0004008c000f5700` DLC 모드 폴더를 삭제하지 말고 다른 곳으로 옮깁니다.
3. `culdcept-dlc-korean-v2.7-safe.zip`의 `load` 폴더를 Azahar 사용자 폴더에 병합합니다.
4. 본편 패치가 `load\mods\00040000000F5700\romfs\CULDCEPT.DAT`에 있는지 확인합니다.
5. 게임을 다시 실행합니다.

v2.7 호환 패키지에서도 `SD카드를 확인 중입니다...`에서 멈추면 번역 직접 IPS가
원인이 아닐 가능성이 높습니다. 저장소의 `verify_install.cmd`를 실행해 결과를 확인하고,
`config\qt-config.ini`의 사용자 지정 `sdmc_directory`와 `log\azahar_log*.txt`를
함께 이슈에 첨부해 주세요.
