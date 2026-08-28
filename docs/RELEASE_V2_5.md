# v2.5 — Azahar 프리징 호환 DLC 패키지

이 릴리즈는 이슈 #10의 `SD카드를 확인 중입니다...` 프리징을 분리 진단하기 위한
카탈로그 전용 호환 패키지입니다. 따라서 이 패키지만 적용하면 부팅은 되더라도 DLC
직접 리소스 제목이 바뀌지 않습니다. DLC 화면까지 번역하려면 [v2.6 전체 패키지](https://github.com/snake7594/culdcept-revolt-korean/releases/tag/v2.6)를
사용하세요.

- `ContentInfoArchive_JPN_ja.bin` 카탈로그만 포함합니다.
- v2.4에서 추가한 직접 리소스 `romfs_ext` IPS 108개는 포함하지 않습니다.
- 따라서 다이스·맵·퀘스트 등의 직접 리소스 제목은 원문으로 남을 수 있지만, v2.4
  직접 IPS가 프리징에 영향을 주는지 확인할 수 있습니다.
- 패키지는 DLC 본체를 포함하지 않습니다. 실제 DLC는 Azahar 가상 SD에 별도로
  설치되어 있어야 합니다.

적용 전에 기존 v2.4 DLC 모드 폴더를 삭제하지 말고 다른 위치로 옮겨 보관한 다음,
이 ZIP의 `load` 폴더를 Azahar 사용자 폴더에 병합하세요. 같은 증상이 계속되면
`verify_install.cmd`를 더블클릭하거나 `verify_install.py` 출력과 Azahar 로그를 이슈 #10에
남겨 주세요.

자산 SHA-256: `D0B1D8238D0D1B79E7C325D093E9948AE8C4D1A0BA571E584AC44D0CDAD736E2`
