# Magma 벤치

[Magma](https://github.com/HexHive/magma)는 C/C++ 프로그램의 한 리비전에 실제 버그를 다시 넣어 둔 퍼저 벤치다. 대상마다 스캔 한 번으로 라벨을 여러 개 얻는다. 여기서는 1차와 2차 구성이 버그 함수에 닿는지 재는 데 쓴다. 2026-09-29에 받은 Magma 저장소 기본 브랜치에는 9개 대상, `patches/bugs`의 버그 138개가 있다.

## 준비

1. `targets/magma`에 Magma를 받고, 대상마다 `targets/magma/targets/<대상>/fetch.sh`가 고정한 리비전을 `targets/magma-src/<대상>`에 받는다(`.git` 포함).
2. `uv run --project boilerplate python bench/magma/prepare.py <대상>...`
   - `targets/magma-src/<대상>-base`에 원본 사본을, `<대상>-bugs`에 모든 버그 패치를 적용한 사본을 만든다(`%MAGMA_BUG%`는 버그 ID로 바꾼다).
   - **수정 코드와 카나리를 지운다.** Magma 패치는 원래 수정을 `#ifdef MAGMA_ENABLE_FIXES`에, 도달·발동 검사를 `#ifdef MAGMA_ENABLE_CANARIES`의 `MAGMA_LOG`에 둔다. 카나리가 남으면 Jev에 정답 위치가 새고, 조건 매크로를 켜고 끄는 추출은 수정 코드까지 평가한다. `unifdef -UMAGMA_ENABLE_FIXES -UMAGMA_ENABLE_CANARIES -UENABLE_MAGMA_FIXES`로 지우고(lua의 패치 하나가 `ENABLE_MAGMA_FIXES`로 잘못 적었다), 남은 `MAGMA` 문자열이 없는지 확인한다.
   - `patches/setup`은 빌드 파일과 퍼저 하네스만 고치므로 적용하지 않는다.
3. `data/magma/db/<대상>/compile_commands.json`을 만든다. configure만 하면 된다(`uvx cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON`). 대상별로 겪은 것:
   - libpng: `-DCMAKE_POLICY_VERSION_MINIMUM=3.5`, 빌드 중 생성되는 `pnglibconf.h`는 `scripts/pnglibconf.h.prebuilt`를 빌드 디렉터리에 둔다.
   - libxml2: `-DLIBXML2_WITH_PYTHON=OFF -DLIBXML2_WITH_LZMA=OFF -DLIBXML2_WITH_ICONV=OFF`.
   - poppler: freetype 헤더(저장소 사본)를 `FREETYPE_INCLUDE_DIR_*`로, 빈 파일을 `FREETYPE_LIBRARY`로 주고, 항상 실패하는 가짜 `pkg-config`를 `PKG_CONFIG_EXECUTABLE`로 준다. 선택 의존성은 모두 끈다.
   - lua: Makefile뿐이라 `*.c`마다 `cc -std=c99 -DLUA_COMPAT_5_3 -DLUA_USE_LINUX -I <root> -c` 명령으로 직접 만든다.
4. `uv run --project boilerplate python bench/magma/scan.py <대상> [--estimate] [--max-requests N]`
   - libclang으로 스캔하고, 합의한 범위 밖(`OUT_OF_SCOPE`: 테스트, contrib, 예제, 퍼저, 문서, 플랫폼 포트) 함수는 `unanalyzed`에 "outside the agreed scope"로 적는다.
   - **라벨:** 버그 패치 하나만 원본에 적용해 바뀐 줄을 구하고, 모든 버그를 넣은 트리의 줄로 옮긴 뒤, 그 줄을 담은 가장 작은 함수 유닛을 라벨로 삼는다. 검사를 지워서 만든 버그도 지운 자리의 줄로 잡힌다. `data/magma/labels-<대상>.json`에 쓴다. `prepare.py`가 출력하는 tree-sitter 기반 이름 목록은 참고용이다.
   - `--estimate` 없이 실행하면 1차(`review_worth_plain`, 0.60 + 15%)를 `data/magma/runs/<대상>/`에 기록한다. 같은 디렉터리로 다시 실행하면 재개된다. 끝나면 대상의 글자당 토큰 비율을 `ratio.json`에 남긴다.

5. `uv run --project boilerplate python bench/magma/recall.py <대상>... [--data DIR]`
   - 1차 점수 순서를 코드 양 10~30%까지 읽을 때 닿는 버그 수를, 긴 함수부터 읽는 순서와 무작위 순서(200회 평균)와 비교한다. 유닛은 통째로 읽고, 다음 유닛이 예산을 넘으면 멈춘다.
   - 합계에 ADR 0018의 합격선·도전 목표 도달 여부를 표시한다. `--data`는 `labels-<대상>.json`과 `runs/<대상>/`가 있는 디렉터리이고, 기본값은 `data/magma`다.

`.env`는 셸로 불러오지 않는다. 값에 셸 특수문자가 있으면 명령으로 실행돼 출력에 새어 나온다. 저장소 루트에서 실행하면 `sift.jev.api_key()`가 `.env`를 직접 읽는다.

## 알려진 한계

- libsndfile의 SND006·SND007·SND024는 `src/flac.c`에 있다. 본문이 `#if HAVE_EXTERNAL_XIPH_LIBS` 안에 있고 설정 헤더가 이 매크로를 `0`으로 정의해, 명령줄 `-D`로 켜도 덮인다. 추출은 "inactive in every configuration"으로 보고한다. 외부 FLAC 헤더를 주고 다시 configure해야 닿는다.
- 버그는 공개된 과거 CVE를 옮겨 넣은 것이다. 모델이 알아볼 수 있으므로 구현·구성 개발과 같은 조건 사이의 비교에 쓴다. 새 취약점 발견 효과의 판정군으로 쓰지 않는다([ADR 0021](../../docs/adr/0021-prospective-cases-for-novel-discovery.md)).
- 대상 리비전은 2021년 중반이다.

결과는 [실험 요약](../../experiments/README.md)에 있다.
