# 호출지점 경계 실험

상태: 2026-10-03 **구조 준비와 개발 표본 구현, M1 문맥과 Jev 호출 전**.

[ADR 0026](../../docs/adr/0026-prioritize-callsite-candidates-and-adaptive-expansion.md)의 첫 단계로, 1차에서 선택된 caller의 소스 호출지점을 공통 원자로 만들고 P·R·C 경계별 후보 목록을 생성한다. 공통 추출과 병합은 `boilerplate/sift/candidates.py`에 있고 이 디렉터리는 실행 조합만 맡는다.

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
