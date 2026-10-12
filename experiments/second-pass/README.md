# 호출지점 경계 실험

상태: 2026-10-03 **구조 준비와 개발 표본 구현, M1 문맥과 Jev 호출 전**.

[ADR 0026](../../docs/adr/0026-prioritize-callsite-candidates-and-adaptive-expansion.md)의 첫 단계로, 1차에서 선택된 caller의 소스 호출지점을 공통 원자로 만들고 P·R·C 경계별 후보 목록을 생성한다. 공통 추출과 병합은 `boilerplate/sift/candidates.py`에 있고 이 디렉터리는 실행 조합만 맡는다.

> 2026-10-08: 기존 묶음과 P·R·C 경계를 배제하고 다시 생각한 2차 구조 후보는 [stage2-structure-proposals.md](stage2-structure-proposals.md)에 제안으로 있다. 아직 합의되지 않았다.

`prepare_boundaries.py`는 모델이나 네트워크를 호출하지 않는다. 입력 1차 실행의 manifest, 호출 관계와 선택 목록 해시를 출력 manifest에 기록한다.

```sh
cd boilerplate
uv run python ../experiments/second-pass/prepare_boundaries.py \
  --run /path/to/stage1-run \
  --output /path/to/boundary-run
```

이전 실행의 `calls.jsonl`에 호출 범위가 없으면 대상과 compile DB를 다시 읽는다. 1차 Jev 결과는 재사용한다.

```sh
cd boilerplate
uv run python ../experiments/second-pass/prepare_boundaries.py \
  --run /path/to/stage1-run \
  --target /path/to/target \
  --compile-db /path/to/compile_commands.json \
  --output /path/to/boundary-run
```

compile DB가 이전 컨테이너의 절대 경로를 담고 있으면 `--relocate-compile-db-from /old/root`를 추가한다. 원본과 재배치한 DB의 해시를 모두 기록한다.

출력:

- `manifest.json`: 입력 해시, 호출 종류, 소스·제어영역 누락과 정책별 후보 수
- `callsites.jsonl`: 구성별 해석을 합친 소스 호출지점 원자
- `candidates-p.jsonl`: caller-callee 병합
- `candidates-r.jsonl`: 어휘적 제어영역 병합
- `candidates-c.jsonl`: 개별 호출지점

이 단계는 후보 수와 입력 자료의 누락을 확인한다. M0·M1·MX 문맥, 결함 근거 라벨 판정과 Jev 점수는 아직 만들지 않는다.

## 개발 표본

세 정책 전수를 곧바로 모델에 보내지 않는다. `sample_boundaries.py`는 호출지점이 둘 이상인 P 그룹을 모집단으로 삼고 호출 수, R 분할 수, M0 크기 근사와 1차 점수로 층화한다. 각 층 안에서는 규칙 이름과 후보 ID의 해시로 순서를 고정한다. 200개 표본은 누적 800개 표본에 포함된다.

알려진 개발 결함과 연결된 P 그룹은 후보 생성이 끝난 뒤 `--required` 입력으로 포함한다. 이 파일의 추가 필드는 무시하며 출력 표본에는 필수 포함 여부나 결함 ID를 쓰지 않는다. 따라서 이 정보는 Jev 입력이나 순위 신호가 아니다.

```sh
cd boilerplate
uv run python ../experiments/second-pass/sample_boundaries.py \
  --boundaries /path/to/boundary-run \
  --stage1-run /path/to/stage1-run \
  --target /path/to/target \
  --required /path/to/evaluator-required.jsonl \
  --output /path/to/boundary-samples
```

`--required`의 각 JSONL 행에는 `p_candidate_id`가 있어야 한다. 개발 결함 연결표가 없으면 이 옵션을 생략한다.

출력:

- `sample-200.jsonl`, `sample-800.jsonl`: P 그룹과 이에 대응하는 P·R·C 후보 ID
- `manifest.json`: 입력 해시, 모집단과 층별 수, 표본별 후보·고유 패킷 수와 M0 크기 근사

M0 크기 근사는 caller의 호출 표현과 고유 callee 본문 문자 수다. 조건부 컴파일 때문에 같은 함수 ID에 서로 다른 본문이 있으면 가장 긴 본문을 사용한다. 토큰 근사는 기존 1차 실행에서 관측한 소스 문자당 토큰 비율 1.8을 사용한다. 실제 M1 입력 토큰과 모델 사용량은 실행 결과로 별도 기록한다.

## `arvo:10400` 구조 준비 결과

2026-10-03, 기존 1차 절제 실행의 3,424개 고유 선택 caller를 같은 CyberGym 이미지 `sha256:3621f3b5820539e187ad9e7e1c6d566a1cdd364851d31c9bfa3ea715205e5646`에서 다시 추출했다. 원래 1차 실행과 파싱 14,638회, 실패 0회, 오류 진단 92,164개가 일치했다. 추출은 562.894초, 원자 병합은 1.121초였다. 원시 결과와 입력 해시는 Git에서 제외된 `data/cybergym/sift-smoke-001/stage2-boundaries-v3/`에 있다.

| 항목 | 결과 |
|---|---:|
| 선택 caller 안의 구성별 호출 해석 | 68,569 |
| 직접 / 외부 / 간접 | 51,615 / 14,573 / 2,381 |
| 소스 호출지점 원자 | 59,679 |
| 소스 표현을 얻지 못한 원자 | 369 |
| 어휘적 제어영역이 없는 원자 | 15,924 |
| P 후보 | 18,846 |
| R 후보 | 38,438 |
| C 후보 | 43,586 |

`ReadMNGImage → mng_get_long`의 소스 호출 24개를 모두 서로 다른 원자로 보존했다. P는 24개를 후보 하나로, R은 11개 후보(구성원 수 8·3·2·2·2·2·1·1·1·1·1)로, C는 24개 후보로 만들었다. 이는 세 정책이 의도한 서로 다른 병합을 만든다는 구조 확인이다. 어떤 정책이 관련 문맥과 Jev에서 더 좋은지는 아직 측정하지 않았다.

호스트에서 직접 실행한 v1은 compile DB의 `/task/build/gm` 경로를 찾지 못했고, 경로만 재배치한 v2는 호스트 시스템의 libpng 헤더 때문에 3,988행의 전체 `ReadMNGImage` 대신 6,173행의 fallback 구현을 활성화했다. 두 실행은 비교에서 제외한다. 정확한 시스템 헤더와 빌드 환경도 호출지점 원자 추출의 재현 입력이다.

## `arvo:10400` 표본 규모

세 정책 후보를 각각 전수 실행하면 총 100,870회 요청이 필요하다. 호출지점 구성원 집합이 같은 후보를 한 번만 평가해도 52,018개 고유 패킷과 약 4,570만 M0 근사 토큰이 남는다. P 그룹 18,846개 중 12,362개는 호출지점 하나뿐이어서 경계 차이를 알려주지 않는다. 나머지 6,484개가 경계 선택 모집단이다.

| 실행 범위 | P 그룹 | P 후보 | R 후보 | C 후보 | 중복 제거 패킷 | M0 근사 토큰 |
|---|---:|---:|---:|---:|---:|---:|
| 정책별 전수 | 18,846 | 18,846 | 38,438 | 43,586 | 52,018 | 45,702,413 |
| 첫 층화 표본 | 200 | 200 | 849 | 1,085 | 1,367 | 2,311,129 |
| 누적 확대 표본 | 800 | 800 | 3,366 | 3,875 | 4,881 | 5,147,524 |

200개 표본에는 `ReadMNGImage → mng_get_long` 개발 결함군을 평가기에서 필수 포함했다. 첫 표본 뒤 명백한 열세 정책은 중단하므로, 800개 단계의 실제 요청 수는 표의 세 정책 합계보다 작을 수 있다. 우승 정책의 M0·MX 대조와 M1의 실제 문맥 크기는 아직 이 수치에 포함되지 않았다. 원시 표본과 manifest는 Git에서 제외된 `data/cybergym/sift-smoke-001/stage2-boundary-samples-v1/`에 있다.

## 데이터플로우 라이브러리 (ADR 0027) 구현 상태

2026-10-11 기준. `sift/dataflow.py`(CFG·도달 정의·제어 의존·별칭 클래스·SCC 요약)와 `sift/slices.py`(싱크·슬라이스·예산 절단·렌더링·오염 추적)를 구현하고 독립 리뷰를 두 번 거쳤다. 1차 리뷰의 치명 7건·주요 5건, 2차 리뷰의 별칭 재작성 회귀 6건과 부분 수정 2건을 모두 고쳤고 각각 수정 전 실패하는 테스트가 있다(`tests/test_dataflow.py`, 81개 통과). `b6df134`로 커밋했고 3차 리뷰 전이다. 구현 비용이 커서 남은 일은 실험에 필요해질 때까지 미룬다(2026-10-11).

별칭은 과대 포함으로 닫는다(복사본은 원본 메모리 전체를 가리키고, 지역 별칭을 통한 쓰기는 출처에 대한 약한 쓰기로 수출하며, 호출로 탈출한 지역 주소는 이후 모든 호출이 쓸 수 있다고 본다). 2차 수정 직후에는 호출이 돌려준 포인터를 인자 객체의 시작과 합쳐 lua의 `lua_State`와 `CallInfo` 필드가 뒤섞였고 고정점이 7배 넘게 느려졌다(lua 1,832초, GraphicsMagick 71분 미완료). 3차 수정에서 반환 포인터를 실제로 들어갈 수 있는 멤버와만 합치고, 같은 변형 본문은 한 번만 요약하며, 큰 호출 입력은 필드별로 색인해 lua는 회복했다. 모두 macOS 호스트 측정이며 컨테이너 충실 수치가 아니다.

| 측정 | 1차 수정 후 | 2차 수정 후 | 3차 수정 후 |
|---|---:|---:|---:|
| png.c 단일 TU: 싱크 / `p[3]` 전체 슬라이스 | 953 / 107k 토큰 | 1,007 / 124k | 999 / 124k |
| png.c 8,000토큰 절단 | 24개 호출지점, `length<16`, `length>=28`, TERM, 할당, `p=chunk` | `length<16` 밀려남 | 같음 |
| png.c 16,000토큰 절단 | 전부 | 전부 | 전부 (길이 정의 포함) |
| GraphicsMagick 스캔(데이터플로우 켬) | 1,211초 / 3.37 GB | 1,117초 / 3.31 GB | 1,242초 / 3.39 GB |
| GraphicsMagick 요약 고정점 | 408초 / 5.1 GB | 71분 미완료 중단 | 1,377초 / 6.43 GB |
| GraphicsMagick 싱크 | 72,672 | — | 74,157 (103초) |
| GraphicsMagick 8,000토큰 슬라이스 201개 | 중앙값 0.23초, p90 1.19초 | — | 중앙값 0.26초, p90 1.27초, 8.2 GB |
| lua 프로그램 구성 | 257초 | 1,832초 | 204~239초 / 1.03 GB |
| lua 8,000토큰 슬라이스 | 중앙값 1.65초 | 3.88초 | 0.96초, 최대 2.5초 |

**3차 수정이 제안한 정밀도 규칙(미합의).** `void *`·`char *` 반환값은 `void`/`char` 인자 메모리나 구조체의 배열 멤버(버퍼)와만 별칭으로 본다. 구조체 시작이나 스칼라 멤버와 합치면 lua 구성 시간이 두 배가 된다. 이 규칙이 놓치는 것은 `(char *)s`나 `&s->scalar_char`를 untyped 포인터로 돌려주는 함수다.

남은 일: (1) GraphicsMagick 고정점이 2차 수정 전보다 3.4배 느린 원인(libxml 재귀 파서군 270개 함수가 1,093초, P2 "호출이 중단될 수 있음"이 1.4배, assert 때문에 libxml 거의 전부가 "중단 가능"), (2) 예산 절단 우선순위에서 실제 정의·가드를 모델 없는 외부 호출의 약한 쓰기보다 앞세울지, (3) 무한 루프를 가드로 취급(`after_loop_until`), (4) 3차 리뷰, (5) CyberGym 이미지 안의 충실한 전체 실행.

## 첫 실험: Magma 변경 줄 재현율 (1단계, 계획)

2026-10-12 기준 계획이며 스크립트는 아직 없다. Jev 없이 슬라이스 자체가 버그 줄을 담는지 먼저 확인하고, 그 결과로 2단계(Jev로 슬라이스 순위 매기기, 1차 순서와 코드 비율 기준 비교)를 사전 등록한다.

**질문.** 범위 안 싱크의 역방향 슬라이스를 4,000·8,000·16,000토큰으로 절단했을 때, 버그별 변경 줄(`bench/magma/scan.py::changed_lines`)을 하나라도 담는 슬라이스가 있는가. 없다면 Jev를 불러도 그 버그는 2차에서 찾을 수 없으므로 상한이 된다.

**입력.** 전체 버그 트리 `targets/magma-src/<대상>-bugs`, compile DB `data/magma/db/<대상>/compile_commands.json`, 범위 안 유닛 `data/magma-2026-09-29/runs/<대상>/functions.jsonl`, 1차 점수 `triage.jsonl`. 대상은 libpng(버그 7), libtiff(14), libxml2(17).

**절차.** `cfamily.scan(root, [db], dataflow=True)` → `dataflow.program` → `slices.sinks`에서 범위 안 함수의 싱크만 남긴다. 싱크마다 `slice_of(p, sink, 16000)`을 한 번 만들고 `cut`을 세 예산에 적용해 span이 덮는 `(path, line)` 집합을 얻는다. 버그 × 예산마다 변경 줄을 담는 슬라이스 수와 싱크가 라벨 함수 안에 있는지 기록한다. 예산별로 `render` 결과를 해시로 중복 제거해 고유 패킷 수와 토큰 합(`slices.tokens`)을 내고, 이것을 2단계 Jev 비용 추정치로 쓴다.

**출력.** 버그 × 예산 표, 싱크 수, 고유 패킷 수와 토큰 합, 실행 시간. 스크립트는 이 디렉터리에 두고 프로세스 풀 때문에 `__main__` 가드가 필요하다. libpng(유닛 517개)으로 먼저 확인하고 libtiff·libxml2는 백그라운드로 돌린다.

**미결.** (1) 포인터 별칭의 untyped 규칙(위 절), (2) 절단 우선순위. 두 값은 1단계 결과가 나온 뒤 결정해도 되며, 바뀌면 1단계를 다시 돌린다.

