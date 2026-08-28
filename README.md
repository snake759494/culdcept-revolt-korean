# 컬드셉트 리볼트 (3DS) — 한글 패치 & CULDCEPT.DAT 툴

**컬드셉트 리볼트**(カルドセプト リボルト, 닌텐도 3DS 일본판, 타이틀 ID
`00040000000F5700`)의 **전체 스토리 대사 + 카드 데이터베이스 + 캐릭터 전투 대사
한글 패치**와, 그것을 만들기 위해 `CULDCEPT.DAT` 아카이브를 처음부터 리버스
엔지니어링한 툴 모음입니다.

오프닝부터 각 스테이지의 스토리 이벤트(13개 시나리오 컨테이너 / 약 4,500개 대화
이벤트)까지 게임 진행 중 등장하는 대화를 한국어로 표시합니다. **카드 데이터베이스
(엔트리 1190)의 카드 능력·설명·플레이버 텍스트 약 4,300개 문자열**, **대전 상대·아군
등 캐릭터 전투 대사(엔트리 1849~1945, 약 12,000개 이벤트 / 상점·UI 도움말 포함)**,
시작 설정 화면 UI, 전투 HUD·카드명 라벨까지 포함합니다. 한글은 **나눔스퀘어 네오
Bold**로 렌더링합니다.

**v1.7부터는 양피지 가이드 나레이션(시작화면·튜토리얼·덱선택·배틀중단)까지 게임
파일에 한글화**합니다. 이 나레이션들은 폰트로 렌더하는 텍스트가 아니라 **ETC1A4
텍스처**(시나리오 컨테이너 안에 저장)여서, 3DS 텍스처 포맷을 규명해 한글을 직접
렌더·주입했습니다(에뮬레이터 텍스처 교체가 아니라 DAT 자체를 수정 — 실기에서도 동작).

**v1.8부터는 UI 버튼 이미지까지 한글화**합니다 — 타이틀/맵 세로 메뉴(퀘스트·혼자서
대전·북·상점·설정·종료 등), 덱 편집 카드 필터(크리처·아이템·스펠·전부·자동 선택),
배틀/맵 커맨드 버튼(영지·지도·정보·설정·종료·뒤로·아이템 없음·설명서·중단·사령·비술).
이 버튼들은 글자까지 통째로 그려진 **ETC1 텍스처**라 색까지 다시 인코딩해야 해서,
3DS ETC1 디코더·인코더를 직접 구현했습니다(`culdcept/etc1.py`).

**v2.4부터는 DLC(타이틀 ID `0004008c000f5700`)의 실제 화면 제목까지 한글화**합니다.
v2.3에서 카탈로그만 바뀌고 다이스·퀘스트 화면이 그대로였던 이슈 #8을 해결하기 위해,
108개 카탈로그 레코드와 각 DLC 직접 리소스(`.dld`·`.dlm`·`.dlq`·`.dlb`·`.dlj`·`.dla`)
헤더를 함께 패치합니다. 원본 DLC나 게임 데이터는 저장소에 포함하지 않습니다.

**이 저장소만으로 처음부터 직접 빌드할 수 있습니다** — 본인의 `CULDCEPT.DAT` 하나만
있으면 `python build.py` 한 줄로 텍스트·UI 이미지 패치가 전부 재현됩니다.
자세한 절차·새 번역 추가·새 아틀라스 찾는 법은 **[`docs/HOWTO.md`](docs/HOWTO.md)** 참고.

## ⚠️ 먼저 읽어주세요

- **게임 콘텐츠는 포함되어 있지 않습니다.** ROM, `CULDCEPT.DAT`, 실행 파일, 스토리
  대사, 카드 텍스트, 이미지·오디오 자산은 없습니다. 다만 UI를 제자리 교체하기 위한
  **검색 키**로, 짧은 기능성 UI/HUD/카드명 라벨(예: `ラウンド`, `手札`) 약 17개의 원문
  SJIS 문자열이 `opening_ko.py`에 들어 있습니다 — 스토리 텍스트가 아니라 위치를 찾기
  위한 라벨입니다. 게임을 정식으로 소유한 상태에서 **본인의 파일**로 사용하세요.
  한글 글리프는 시스템 폰트(맑은 고딕 등)에서 그려지고, 대사 원문은 전부 본인의
  `CULDCEPT.DAT`에서 읽어옵니다.
- **한국어 번역은 `dialogue_ko.json`(스토리 대사)·`cards_ko.json`(카드 텍스트)·
  `block_ko.json`(캐릭터 전투 대사)에 있습니다** — 한국어만 담기며, 일본어 원문은
  포함하지 않습니다(적용 시 본인 파일에서 읽음). 카드·대사는 위치(인덱스)로만
  매핑되고, 아이콘·제어코드·이름삽입 코드 등 원문 바이트는 적용 시 본인 파일에서
  다시 읽어 보존합니다. 완성형 2350자 폰트를 쓰므로 대부분의 한글이 표시됩니다.
- **아직 번역하지 않은 화면**(일부 텍스처 라벨·미크랙 나레이션 등)에서는, 한글 표시를
  위해 재활용한 한자 자리에 한글 글리프가 보일 수 있습니다(완성형 방식의 알려진 특성).
- **카드 이름이 원문으로 보인다는 제보**가 있습니다. 전 엔트리를 0x0d/0x8d 까지 모두 풀어
  재귀 검색한 결과 카드명은 **엔트리 1190 에만** 있고 그곳은 이미 한글로 바뀝니다. 원인을
  아직 특정하지 못했으니, 재현되면 패치 버전과 화면을 이슈로 올려주세요.
- **길이 제약**으로 일부 대사·카드 텍스트는 원문 바이트 한도에 맞춰 간결하게 축약되어
  있습니다. 카드 능력 키워드 `巻物`(두루마리) 계열은 좁은 능력창에 맞추려고 압축형
  `권물`(卷物)로 통일했습니다.
- 연구·개인용. 게임의 저작권을 존중하세요.

## 적용 방법

두 가지 방법이 있습니다. 같은 한글 폰트를 쓰면 결과가 동일합니다 — xdelta 패치는
**나눔스퀘어 네오 Bold**로 만든 것이므로, 방법 A에서 그 폰트를 `fonts/`에 두거나
`--font`로 지정하면 릴리즈와 똑같이 나옵니다(다른 TTF면 글리프 모양만 달라짐).

### 가장 쉬운 적용 — 릴리즈 파일만 복사

일반 사용자는 **plaintext DLC 덤프나 파이썬을 준비할 필요가 없습니다.** 먼저 본편 v2.2
패치가 적용된 상태에서 [v2.6 릴리즈의 `culdcept-dlc-korean-v2.6.zip`](https://github.com/snake7594/culdcept-revolt-korean/releases/download/v2.6/culdcept-dlc-korean-v2.6.zip)을
받습니다. v2.5는 프리징 원인을 분리하기 위해 DLC 직접 리소스를 일부러 제외한 진단용
패키지였기 때문에, v2.5만 적용하면 다이스·맵·퀘스트 제목이 바뀌지 않는 것이 정상입니다.

1. ZIP을 압축 해제합니다.
2. 압축 해제된 `load` 폴더를 Azahar 사용자 폴더(보통
   `C:\Users\<윈도우 계정>\AppData\Roaming\Azahar\`)에 **폴더째 병합**합니다.
   `load` 폴더 안의 파일만 따로 꺼내 현재 모드 폴더에 넣지 마세요.
3. 다음 두 경로가 각각 존재하는지 확인합니다.

   ```text
   Azahar\load\mods\00040000000F5700\romfs\CULDCEPT.DAT
   Azahar\load\mods\0004008c000f5700\romfs\ContentInfoArchive_JPN_ja.bin
   Azahar\load\mods\0004008c000f5700\romfs_ext\dice_simple_blue.dld.ips
   ```

   `CULDCEPT.DAT`는 본편 ID `00040000000F5700`에 두고, DLC 파일은 DLC ID
   `0004008c000f5700`에 둡니다. `ContentInfoArchive_JPN_ja.bin`을 본편 폴더에 넣으면
   적용되지 않습니다.
4. 게임과 에뮬레이터를 완전히 종료한 뒤 다시 실행합니다. 기존 세이브 상태를 바로
   재개하지 말고 게임을 새로 부팅하세요.

### 새 이슈(#11) 대응 — v2.5에서 부팅되지만 DLC·카드가 그대로일 때

이슈 #11의 현상은 v2.5 패키지의 목적과 일치합니다. v2.5는 `ContentInfoArchive_JPN_ja.bin`
카탈로그만 넣고 `romfs_ext` 직접 리소스 IPS를 제외했으므로, 프리징은 피할 수 있지만
다이스·맵·퀘스트·북·아바타 화면의 직접 제목은 원문으로 남습니다. DLC 제목까지 바꾸려면
[v2.6 전체 패키지](https://github.com/snake7594/culdcept-revolt-korean/releases/download/v2.6/culdcept-dlc-korean-v2.6.zip)를
받아 v2.5 DLC 모드 폴더와 교체하세요.

카드 설명은 DLC에 들어 있지 않고 본편 `CULDCEPT.DAT`의 카드 DB(엔트리 1190)에서
읽습니다. 따라서 v2.6 DLC ZIP만으로 카드 설명이 바뀌지 않으며, 본편 패치 파일이 아래
경로에 있어야 합니다.

```text
Azahar\load\mods\00040000000F5700\romfs\CULDCEPT.DAT
```

기존 v2.5 또는 v2.4 DLC 폴더는 삭제하지 말고 먼저 다른 곳으로 옮긴 후 v2.6의 `load`
폴더를 Azahar 사용자 폴더에 병합하세요. 적용 후 게임과 에뮬레이터를 완전히 종료하고
다시 실행합니다. 설치 여부를 어려운 명령어 없이 확인하려면 저장소의
`verify_install.cmd`를 더블클릭하세요. 기본적으로 `%APPDATA%\Azahar`를 검사하며,
다른 사용자 폴더를 쓰면 그 폴더를 인자로 끌어다 놓아도 됩니다.

### 프리징 제보(#10) 대응 — v2.5 호환 패키지

제보 영상은 3D 부팅까지 진행된 뒤 `SD카드를 확인 중입니다...` 화면에서 0 FPS로
멈추는 증상입니다. v2.4의 패치 데이터는 원본 DLC에서 카탈로그 108개와 직접 리소스
IPS 108개가 모두 재현되지만, 직접 리소스 IPS는 화면 제목을 위한 부가 기능입니다.
Azahar 2126.0에서 이 증상을 겪으면 먼저 [v2.5 호환 패키지](https://github.com/snake7594/culdcept-revolt-korean/releases/download/v2.5/culdcept-dlc-korean-v2.5-compat.zip)를
사용하세요. 이 패키지는 `ContentInfoArchive_JPN_ja.bin`만 넣는 카탈로그 전용 모드라서,
직접 리소스 IPS를 제외한 상태로 실행을 분리해 확인할 수 있습니다. v2.4의 DLC 모드
폴더는 삭제하지 말고 다른 곳으로 잠시 옮긴 뒤 v2.5 `load` 폴더를 병합하세요.

v2.4/v2.5/v2.6 ZIP은 **DLC 본체를 포함하거나 설치하지 않습니다.** 본인 소유 DLC가 Azahar
가상 SD에 먼저 설치되어 있어야 하며, 다음 형태의 파일이 있어야 합니다.

```text
Azahar\sdmc\Nintendo 3DS\<ID0>\<ID1>\title\0004008c\000f5700\content\00000000\*.app
```

또한 Azahar에서 `use_virtual_sd=true`인지 확인하고, 2126.0의 실험 기능인
`Graphics > Simulate 3DS GPU timings`가 켜져 있다면 끈 뒤 완전히 재시작하세요.
설치 경로를 바꾸기 전에 저장소의 읽기 전용 진단기를 실행하면 원인을 구분할 수
있습니다.

```bash
python verify_install.py "C:\Users\<윈도우 계정>\AppData\Roaming\Azahar"
```

또는 `verify_install.cmd`를 더블클릭하세요.

v2.5 호환 패키지에서도 같은 화면에 멈추면 번역 오버레이만으로는 원인을 설명할 수
없습니다. 진단기 출력과 `Azahar\log\azahar_log.txt`의 마지막 부분을 이슈에 함께
올려 주세요.

`plaintext DLC 덤프`는 개발자가 번역 패치를 다시 만들 때만 필요한 자료입니다. 압축을
푼 폴더 안에 `content\00000000\00000000.app` 같은 `.app` 파일이 있는 형태이며,
게임의 `.3dsx` 파일이나 v2.4 패치 ZIP을 뜻하지 않습니다.

### 방법 A — 파이썬 툴 (권장, 어떤 판본이든 구조가 같으면 동작)

필요: 파이썬 3, [Pillow](https://pypi.org/project/Pillow/), 한글 TTF.
릴리즈 패치는 **나눔스퀘어 네오 Bold**로 렌더링합니다 — 릴리즈와 똑같은 모양을
원하면 그 폰트를 `fonts/NanumSquareNeo-cBd.ttf` 로 두세요([`fonts/README.md`](fonts/README.md),
[네이버 배포처](https://hangeul.naver.com/font)). 없으면 시스템 폰트(맑은 고딕 등)로
대체됩니다.

```bash
pip install pillow numpy
# 통합 빌드(권장) — 텍스트 + UI 버튼 이미지를 한 번에:
python build.py 원본/CULDCEPT.DAT 출력/CULDCEPT.DAT --font fonts/NanumSquareNeo-cBd.ttf

# 단계별로 하고 싶다면:
python apply_korean_full.py 원본/CULDCEPT.DAT 중간.DAT   # 대사·카드·UI 텍스트
python apply_ui_images.py   중간.DAT        출력/CULDCEPT.DAT  # UI 버튼 이미지
# (오프닝만 원하면 apply_korean_opening.py)
```

`build.py` 에 `--xdelta out.xdelta` 를 주면 배포용 diff 패치도 만듭니다.
나레이션 텍스처까지 재현하려면 `--narration-decoder` 가 필요합니다
([`docs/HOWTO.md` §4](docs/HOWTO.md) — 게임 `code.bin` 이 필요한 유일한 단계).

`apply_korean_full.py` 는 본인 파일에서 대사·UI 위치를 찾아, `dialogue_ko.json`(한국어
번역만 담김, 일본어 원문 없음)의 번역으로 교체합니다. 게임이 대사를 절대 오프셋으로
참조하므로 각 대화창의 한국어는 원문 바이트 한도에 맞춰져 있습니다(부족분은 공백 패딩).

### DLC 한글화 — 이슈 #8 / v2.6 (v2.4에서 직접 리소스 기능 추가)

위의 릴리즈 ZIP 복사는 완성된 오버레이를 적용하는 일반 사용자용 방법입니다. 본인이
소유한 DLC로 패치를 **다시 생성하거나 번역을 수정할 때만** 아래처럼 plaintext DLC
덤프를 준비합니다.

본인이 소유한 DLC `DLC-000f5700.zip`을 압축 해제한 뒤, 아래 명령을 실행합니다.
스크립트는 `.app`의 plaintext RomFS에서 카탈로그와 직접 DLC 리소스를 읽습니다. 카탈로그는
같은 길이의 한국어 파일로 만들고, 다이스·맵·퀘스트·북·책 표지·아바타의 화면 제목은
`romfs_ext` IPS 패치로 생성합니다. v2.2 본편 패치의 한글 폰트가 필요합니다.

```bash
python apply_dlc_korean.py DLC-000f5700 \
    --base-dat patched/CULDCEPT.DAT --output dlc-mod
```

`dlc-mod/load/` 전체를 에뮬레이터 사용자 폴더에 병합하세요. 생성되는 구조는 다음과
같습니다.

```
dlc-mod/load/mods/0004008c000f5700/romfs/ContentInfoArchive_JPN_ja.bin
dlc-mod/load/mods/0004008c000f5700/romfs_ext/dice_simple_blue.dld.ips
dlc-mod/load/mods/0004008c000f5700/romfs_ext/dlc_batsdays.dlq.ips
...
```

적용 후 게임을 완전히 종료했다가 다시 실행하세요. 본편 카드 설명은 DLC 파일이 아니라
본편 `CULDCEPT.DAT`에 있으므로, 먼저 본편 패치를 적용한 뒤 DLC 오버레이를 추가해야
합니다. 적용 여부는 원본 DLC를 보유한 상태에서 아래처럼 재현 검증할 수 있습니다.

```bash
python verify_dlc_patch.py DLC-000f5700 \
    --base-dat patched/CULDCEPT.DAT --overlay dlc-mod
```

### 방법 B — xdelta 패치 (빠름, 원본이 정확히 일치할 때)

[릴리즈](../../releases)의 `culdcept-korean.xdelta`는 일본판(Rev 2) RomFS의
`CULDCEPT.DAT`에 대한 **차이(diff)**입니다. 원본 파일 없이는 사용할 수 없습니다.

- **DeltaPatcher**(GUI): Original = 본인 `CULDCEPT.DAT`, Patch = `.xdelta` → Apply
- **명령줄**:
  ```
  xdelta3 -d -s CULDCEPT.DAT culdcept-korean.xdelta out_CULDCEPT.DAT
  ```
  (일부 xdelta 빌드는 `xdelta` 로 실행. `unknown secondary compressor` 오류가 나면
  최신 xdelta3 또는 DeltaPatcher를 쓰세요.)

### 적용됐는지 확인

```bash
python verify_patch.py "<에뮬>/load/mods/00040000000F5700/romfs/CULDCEPT.DAT"
```

항목별로 O/X 를 보여줍니다. 화면이 그대로인데 전부 O 라면 파일이 아니라 **적용 경로** 문제입니다.

### 적용 결과 넣기 — LayeredFS

패치된 파일을 `CULDCEPT.DAT` 이름 그대로 아래 경로에 넣고 게임을 새로 실행:

```
<에뮬레이터 사용자 폴더>/load/mods/00040000000F5700/romfs/CULDCEPT.DAT
```

정상 적용 시 에뮬 로그에 `LayeredFS replacement file in use for /CULDCEPT.DAT`
가 출력됩니다. (실기는 이 파일로 RomFS를 재빌드해 ROM/CIA를 만드세요.)

## 무엇을 분석했나

- **`CULDCEPT.DAT` 컨테이너** — `(u32 오프셋, u32 크기)` 레코드 테이블 뒤에 엔트리
  데이터. 엔트리 개수 = `첫_오프셋 / 8`.
- **코덱** — `0x08`/`0x0c` = DEFLATE 계열 **canonical Huffman + LZ**(텍스트·폰트).
  이 타입은 디컴프레서·컴프레서 모두 순수 파이썬으로 구현(`culdcept/huffman.py`).
  `0x0d`/`0x8d` = 커스텀 **LZMA 레인지 코더**(572개). 비트 디코더는 표준 LZMA 와 같지만
  초기화·심볼 구조가 달라 표준 라이브러리로는 풀리지 않는다. `culdcept/lzma0d.py` 가 게임
  실행코드를 Unicorn 으로 에뮬레이션해 해제한다(본인 롬에서 `extract_code.py` 로 code.bin
  추출 필요).
- **비트맵 폰트** — CMAP(글리프 인덱스 → SJIS/ASCII 코드) + 여러 크기 섹션의 고정 셀
  **A4(4비트 알파)** 글리프. 위치 = `섹션 + 0xCE + 인덱스*bpg`.
- **시나리오 컨테이너** — 스토리 대사가 있는 곳. 코덱 엔트리가 아니라 자체
  `(섹션 오프셋, 크기)` 헤더로 시작하는 컨테이너이며, 각 섹션은 `0x08` 압축.
  대사 섹션은 `[스크립트][텍스트]` 구조, 텍스트는 null 종료 이벤트의 연속
  (`0x07`=페이지, `0x0a`=줄바꿈, `03 30 2f`=이름 삽입).
- **UI 버튼 아틀라스 (v1.8)** — 메뉴·필터·커맨드 버튼은 글자까지 통째로 그려진
  **ETC1/ETC1A4 텍스처**(엔트리 711·608·962). 3DS 는 ETC1 블록을 **u64 리틀엔디언**
  (=표준의 바이트 역순)으로 저장한다는 점을 규명해 디코더·인코더를 구현하고
  (`culdcept/etc1.py`), 원문을 지운 뒤 한글을 렌더해 **바뀐 블록만** 재인코딩한다.
  세 엔트리 모두 huffman 이라 `code.bin` 없이 완전 재현된다.
- **나레이션 텍스처 (v1.7)** — 양피지 가이드 나레이션은 시나리오 컨테이너 안에
  헤더 없이 저장된 **256×64/256×128 ETC1A4 텍스처**. 3DS 스위즐(8×8 타일 morton) +
  ETC1A4(알파 A4 + 색 ETC1) 구조를 규명해, 알파만 한글로 교체하고 색은 균일 진회색으로
  설정해 원본과 같은 스타일로 렌더한다. 겹쳐 저장된 다른 텍스처를 깨지 않도록 한글
  잉크가 있는 행까지만 덮고, 각 줄은 원본 잉크의 가로 중심에 맞춰 배치한다.

포맷 상세는 [`docs/FORMAT.md`](docs/FORMAT.md), 직접 빌드·번역 추가 방법은
[`docs/HOWTO.md`](docs/HOWTO.md) 참고.

## 라이브러리

```python
from culdcept import huffman, dat, font, scen, wansung, etc1
d = dat.Dat(open("CULDCEPT.DAT", "rb").read())
raw = huffman.decompress(d.entry(1054))     # -> 압축 해제된 폰트 리소스
```

## 번역 데이터

- `dialogue_ko.json` — **전체 스토리 대사**의 한국어(섹션·이벤트·페이지 인덱스 기준).
- `cards_ko.json` / `block_ko.json` / `missed_ko.json` — 카드 텍스트 / 캐릭터 전투 대사 /
  놓쳤던 중간 텍스트·한자 라벨의 한국어.
- `opening_ko.py` — 오프닝 대사(다듬은 버전) + UI/시작설정 라벨 한국어.
- `cards_extra_ko.json` — 카드 텍스트 열거 필터가 놓친 문자열의 한국어(오프셋 기준).
  선택창 '예' 등. 항목마다 원문 길이를 함께 적어 오프셋이 틀리면 건너뛴다.
- `ui_images_ko.json` — **UI 버튼 이미지**의 한국어 + 좌표(아틀라스별 엔트리·TS·크기,
  라벨별 지울 영역·그릴 위치·폰트 크기·색·지우기 방식). `apply_ui_images.py` 로 주입.
- `narration_ko.json` — **양피지 가이드 나레이션**의 한국어(엔트리·오프셋·크기별,
  256×64 35종 + 256×128 12종). `apply_narration.py`로 텍스처에 렌더·주입.
  (0x0d 엔트리 디코드에 게임 `code.bin`이 필요 — 저작권상 미배포, 각자 롬에서 추출.)
- `dlc_ko.json` — DLC 카탈로그 108개 고정 레코드의 한국어 제목·설명.
  `apply_dlc_korean.py`가 본인 DLC 덤프에서 원본을 읽고 카탈로그와 직접 리소스 제목을
  함께 교체합니다. `verify_dlc_patch.py`로 출력 IPS의 재현성을 검사할 수 있습니다.
- `verify_install.py` — Azahar의 본편/DLC 모드 경로, 실제 DLC 설치, 가상 SD 설정과
  LayeredFS 로그를 변경 없이 점검합니다(이슈 #10 진단용).

모두 한국어 번역만 담으며, 일본어 원문은 없습니다(적용 시 본인 파일에서 읽음).

> 참고: `apply_korean_font.py`(v0.1 발음 데모), `apply_korean_opening.py`(오프닝만),
> `apply_korean_full.py`(전체 대사). 최신 릴리즈는 전체 대사 패치입니다.

## 크레딧

컨테이너·코덱·폰트·시나리오 포맷을 처음부터 리버스 엔지니어링했습니다. 툴과 번역은
원저작물이며 MIT 라이선스입니다(`LICENSE` 참고). 컬드셉트 리볼트는
© Omiya Soft / Nintendo. 이 저장소에는 게임 코드나 데이터가 포함되어 있지 않습니다.
