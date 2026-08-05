# 처음부터 직접 패치하기 (HOWTO)

이 문서 하나로 **본인의 게임 파일 + 이 저장소만으로** 한글패치를 다시 만들 수 있게
하는 것이 목표입니다. 새 번역을 추가하거나 다른 화면을 한글화하는 방법도 함께 적었습니다.

> 저장소에는 게임 데이터가 없습니다. 아래 모든 과정은 **본인이 소유한 게임에서 추출한
> 파일**로 진행합니다.

---

## 0. 준비물

| 항목 | 설명 |
|---|---|
| `CULDCEPT.DAT` | 본인 게임(일본판, 타이틀 ID `00040000000F5700`)의 RomFS 에서 추출 |
| 파이썬 3 | `pip install pillow numpy` |
| 한글 TTF | 릴리즈와 동일하게 하려면 **나눔스퀘어 네오 Bold** → `fonts/NanumSquareNeo-cBd.ttf` ([배포처](https://hangeul.naver.com/font)) |
| (선택) xdelta3 | 배포용 diff 패치를 만들 때 |

### CULDCEPT.DAT 추출

에뮬레이터(Azahar/Lime3DS/Citra 계열)에서 게임을 우클릭 → **Dump RomFS**.
`dump/romfs/00040000000F5700/CULDCEPT.DAT` 가 생깁니다. (실기 유저는 GodMode9 등으로 추출.)

---

## 1. 한 줄로 빌드하기

```bash
pip install pillow numpy
python build.py 원본/CULDCEPT.DAT 출력/CULDCEPT.DAT --font fonts/NanumSquareNeo-cBd.ttf
```

단계별로 이렇게 진행됩니다.

| 단계 | 스크립트 | 내용 | code.bin 필요? |
|---|---|---|---|
| 1 | `apply_korean_full.py` | 스토리 대사·카드DB·캐릭터 대사·UI + 한글 폰트 글리프 | ✕ |
| 2 | `apply_ui_images.py` | 메뉴/필터/커맨드 **버튼 이미지** (ETC1 텍스처) | ✕ |
| 3 | `apply_narration.py` | 양피지 가이드 **나레이션 텍스처** | **○** |

**1·2 단계는 이 저장소만으로 완결**됩니다. 3 단계만 제약이 있습니다(아래 §4).

배포용 xdelta 도 같이 만들려면:

```bash
python build.py 원본/CULDCEPT.DAT 출력/CULDCEPT.DAT \
    --font fonts/NanumSquareNeo-cBd.ttf \
    --xdelta culdcept-korean.xdelta --xdelta-bin xdelta3
```

### 결과 넣기 (LayeredFS)

```
<에뮬레이터 사용자 폴더>/load/mods/00040000000F5700/romfs/CULDCEPT.DAT
```

정상 적용 시 로그에 `LayeredFS replacement file in use for /CULDCEPT.DAT` 가 뜹니다.
실기는 이 파일로 RomFS 를 재빌드해 ROM/CIA 를 만드세요.

---

## 2. 재현성 검증

빌드 결과가 릴리즈와 같은지 확인하려면 UI 아틀라스를 픽셀 비교합니다.

```bash
python - <<'PY'
import struct, json, numpy as np
from culdcept import huffman
from apply_ui_images import decode_rgb
def get(p, e):
    d = open(p, 'rb').read()
    o = struct.unpack_from('<I', d, e*8)[0]; s = struct.unpack_from('<I', d, e*8+4)[0]
    return huffman.decompress(d[o:o+s])
A_PATH = "출력/CULDCEPT.DAT"        # 내가 빌드한 것
B_PATH = "릴리즈/CULDCEPT.DAT"      # 비교 대상
for a in json.load(open("ui_images_ko.json", encoding="utf-8"))["atlases"]:
    A = decode_rgb(get(A_PATH, a["entry"]), a["ts"], a["w"], a["h"], a["fmt"])
    B = decode_rgb(get(B_PATH, a["entry"]), a["ts"], a["w"], a["h"], a["fmt"])
    d = np.abs(A.astype(int) - B.astype(int)).max()
    print(f"{a['name']:16s} {'일치' if d == 0 else f'차이 {d}'}")
PY
```

같은 폰트를 썼다면 세 아틀라스 모두 **완전 일치**해야 합니다.
(이 방식으로 v1.8 툴이 배포본을 픽셀 단위로 재현함을 확인했습니다.)

코덱 자체 검증:

```bash
python culdcept/etc1.py     # 디코더 골든 벡터 + 유형별 왕복오차
```

---

## 3. 번역 고치기 / 추가하기

### 3.1 텍스트 (대사·카드·UI)

JSON 을 고치고 다시 빌드하면 됩니다.

| 파일 | 내용 |
|---|---|
| `dialogue_ko.json` | 스토리 대사 (섹션·이벤트·페이지 인덱스) |
| `cards_ko.json` | 카드 능력·설명·플레이버 |
| `block_ko.json` | 캐릭터 전투 대사 |
| `missed_ko.json` | 중간 텍스트·한자 라벨 |
| `opening_ko.py` | 오프닝 대사 + UI/시작설정 라벨 |

⚠️ **길이 제약**: 게임이 대사를 **절대 오프셋**으로 참조하므로 번역문은 원문 바이트
길이 이하여야 합니다(부족분은 자동 공백 패딩). 카드 텍스트도 포인터 참조라 동일합니다.
raw(0x00) 섹션의 세그먼트 주의사항은 [`FORMAT.md` §8](FORMAT.md#8-비압축raw-type-0x00-텍스트-섹션-주의) 참고.

### 3.2 UI 버튼 이미지

`ui_images_ko.json` 의 `text` 만 고쳐도 되고, 새 아틀라스를 통째로 추가할 수도 있습니다.

```jsonc
{
  "name": "내_아틀라스",
  "entry": 962,          // DAT 엔트리 번호
  "ts": 32,              // 압축 해제 후 텍스처 시작 오프셋
  "w": 64, "h": 696,     // 픽셀 크기(저장 폭 기준, 패딩 포함)
  "fmt": "etc1a4",       // 또는 "etc1"
  "labels": [
    { "erase": [4, 10, 44, 25],   // 원문을 지울 영역
      "draw":  [4, 10, 44, 25],   // (생략 가능) 한글을 중앙정렬할 영역
      "text": "영지", "size": 13,
      "color": [38, 34, 42],
      "align": "c",               // c(기본)/l/r
      "mode": "row_pct",          // row_pct | row_fill | white_only
      "clean_x": [14, 26] }       // row_pct/row_fill 의 배경 표본 x 구간(선택)
  ]
}
```

`mode` 선택 기준은 [`FORMAT.md` §9.5](FORMAT.md#95-원문-지우고-한글-그리기) 참고
(잔상이 남으면 `row_pct` → `row_fill`).

### 3.3 새 아틀라스 찾기 (좌표 알아내기)

1. **덤프 켜기** — 에뮬레이터의 텍스처 덤프 기능으로 해당 화면을 띄우면
   `tex1_<W>x<H>_<HASH>_<fmt>_mip0.png` 가 쌓입니다 (`fmt` 12=ETC1, 13=ETC1A4, 4=RGBA4).
2. **DAT 안 위치 찾기** — [`FORMAT.md` §9.4](FORMAT.md#94-아틀라스-찾는-법--바이트-검색이-실패하면-rgb-근사-매칭)
   의 두 방법(알파 바이트 정확 일치 / RGB 근사 매칭). 대략 이런 식입니다.

```python
import struct, numpy as np
from culdcept import huffman
from culdcept.etc1 import decode_all_blocks
from PIL import Image

dump = np.array(Image.open("tex1_64x1024_XXXX_13_mip0.png").convert("RGB"))
target = dump[0:4, 4:8]                       # 특징적인(분산 큰) 4×4 블록
d = open("CULDCEPT.DAT", "rb").read()
n = struct.unpack("<I", d[:4])[0] // 8
for i in range(n):
    o = struct.unpack_from("<I", d, i*8)[0]; s = struct.unpack_from("<I", d, i*8+4)[0]
    if s < 4096: continue
    if (struct.unpack("<I", d[o:o+4])[0] & 0xff) not in (0x08, 0x0c): continue
    dec = decode_all_blocks(huffman.decompress(d[o:o+s])).astype(int)
    hit = np.abs(dec - target).mean(axis=(1, 2, 3)) < 12
    if hit.any():
        print("후보 엔트리", i, "블록", np.where(hit)[0][:5])
```

3. **TS 역산** — 매칭 블록 인덱스 `k` 와 그 블록의 텍스처 좌표 `(bx,by)` 로부터
   `TS = k*8 - color_off(0,bx,by)`. 렌더해서 눈으로 확인합니다.

```python
from apply_ui_images import decode_rgb
Image.fromarray(decode_rgb(raw, TS, W, H, "etc1a4")).save("check.png")
```

---

## 4. 나레이션 텍스처 (code.bin 이 필요한 부분)

양피지 가이드 나레이션(`narration_ko.json`)은 **0x0d/0x8d(커스텀 LZMA)** 엔트리 안에 있어서
푸는 데 게임 실행코드(`code.bin`)가 필요합니다. `code.bin` 은 저작권상 배포하지 않으므로
**본인 롬에서 직접 추출**하면 됩니다 — 저장소에 추출 툴이 들어 있습니다.

```bash
# ① 본인 롬에서 code.bin 추출 (복호화된 .3ds/.cci 필요)
python extract_code.py "Culdcept Revolt (Japan).3ds" code.bin

# ② 나레이션까지 포함해 빌드
python build.py 원본.DAT 출력.DAT --font fonts/NanumSquareNeo-cBd.ttf     --narration-decoder narration_decoder.py
```

`code.bin` 이 저장소 폴더에 없으면 환경변수 `CULDCEPT_CODE_BIN` 으로 경로를 지정하세요.

### 어떻게 푸는가

`culdcept/lzma0d.py` 가 게임의 디컴프레서 함수(`0x00275080`)를 **Unicorn 으로 에뮬레이션**
합니다. 이 압축은 비트 디코더만 표준 LZMA(11비트 확률·move 5·top 1<<24)이고 심볼 구조가
달라서 표준 LZMA 라이브러리로는 풀리지 않습니다. 자세한 내용은
[`FORMAT.md` §11](FORMAT.md) 참고.

직접 만든 디코더를 쓰고 싶다면 인터페이스만 맞추면 됩니다.

```python
def decompress(entry_bytes: bytes) -> bytes:
    """0x0d/0x8d 엔트리(타입 바이트 포함) → 압축 해제된 바이트"""
```

주입할 때는 **0x08 무압축으로 재인코딩**하므로 커스텀 LZMA **압축기는 필요 없습니다**
(해제만 필요).

## 5. 자주 겪는 문제

| 증상 | 원인 / 해결 |
|---|---|
| `unknown secondary compressor` | 오래된 xdelta. 최신 xdelta3 또는 DeltaPatcher 사용. 만들 때는 `-S djw`. |
| 패치가 반영되지 않음 | LayeredFS 경로/타이틀 ID 확인. 로그에 `LayeredFS replacement file in use` 가 떠야 함. |
| 글자 모양이 릴리즈와 다름 | 폰트가 다름. `fonts/NanumSquareNeo-cBd.ttf` 로 두거나 `--font` 지정. |
| 버튼에 원문 잔상이 남음 | 해당 라벨 `mode` 를 `row_pct` → `row_fill` 로. `erase` 영역도 조금 넓히기. |
| 한글 대신 한자가 보임 | 아직 번역하지 않은 화면. 완성형(wansung) 방식의 알려진 특성([`FORMAT.md` §6](FORMAT.md#6-완성형wansung-한글-인코딩-culdceptwansungpy)). |
| 대사가 잘림 | 번역문이 원문 바이트 한도를 넘음. 더 짧게. |

---

## 6. 아직 안 된 것 (기여 환영)

- **카드 이름 / 일부 스펠 설명이 원문으로 보인다는 제보** — 원인 미확정. 전 엔트리를
  0x0d/0x8d 까지 모두 풀고 컨테이너 섹션까지 재귀 검색한 결과, 카드명은 **엔트리 1190
  에만** 있고 그곳은 이미 한글로 바뀝니다. 재현되면 사용 중인 패치 버전과 화면을 함께
  이슈로 올려주세요.
- 하단 상태 라벨(32×16 RGBA4) — 바이트 검색으로 DAT 위치를 못 찾음. §9.4 의 RGB 근사
  매칭으로 재시도해 볼 만함.
- 소형 라벨(128×32), 퀘스트 배너(128×128), 키보드 라벨 등 나머지 텍스처.
- 0x0d 의 **순수 파이썬 디코더**(현재는 code.bin 에뮬레이션). 있으면 롬 없이도 재현 가능.
