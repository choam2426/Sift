# Go logic-bug e2e harness

2026-10-19 기준 3-arm harness. `vanilla` / `route-index` / `jev`를 같은 소스·도구·금전 상한에서 비교한다. 2-arm Kite 결과는 development pilot이며, confirmatory 프로토콜은 [ADR 0007](../../../docs/adr/0007-three-arm-ranker-evaluation-after-independent-review.md)을 따른다.

## 구성

- `prepare`: 취약 리비전 소스를 workspace에 풀고 Go 컨테이너를 띄운다. `tb test/build/exec` 래퍼를 만든다.
- `--arm vanilla`: 소스·도구·가이드만. route bundle 없음.
- `--arm route-index`: 같은 route bundle과 가이드, Jev 없이 고정 ID 순서.
- `--arm jev`: 같은 bundle과 가이드, Jev ranker CLI·고정 질문·top-K.
- `run`: Claude Code를 깨끗한 설정으로 실행하고 `findings/`를 평가한다.
- `teardown`: 컨테이너와 Jev proxy를 정리한다.
- `jev_proxy.py`: 호스트에서 API 키를 들고 Unix socket으로 Jev를 호출한다. key는 workspace 밖에 있고 agent는 읽지 못한다.
- `jev_cli.py`: workspace의 `./jev`가 된다. `ask`, `rank`, `stats`만 제공한다. Jev는 후보 ranker이며 검증자가 아니다.

## 준비

```bash
# 취약/수정 소스 (예: Kite)
mkdir -p ~/sift-runs/logic-e2e/sources
# source trees must not contain .git or the hidden test
# module cache
docker volume create sift-go-mod-cache
docker run --rm -v <vuln-source>:/src -w /src -v sift-go-mod-cache:/go/pkg/mod \
  -e GOPATH=/go golang:1.26 go mod download
```

## 실행

```bash
python3 experiments/logic-ranker/e2e/e2e.py prepare --case kite --arm vanilla --workspace ~/sift-runs/logic-e2e/kite-vanilla
python3 experiments/logic-ranker/e2e/e2e.py run --workspace ~/sift-runs/logic-e2e/kite-vanilla --max-budget-usd 30

python3 experiments/logic-ranker/e2e/e2e.py prepare --case kite --arm route-index --workspace ~/sift-runs/logic-e2e/kite-route-index
python3 experiments/logic-ranker/e2e/e2e.py run --workspace ~/sift-runs/logic-e2e/kite-route-index --max-budget-usd 30

python3 experiments/logic-ranker/e2e/e2e.py prepare --case kite --arm jev --workspace ~/sift-runs/logic-e2e/kite-jev
python3 experiments/logic-ranker/e2e/e2e.py run --workspace ~/sift-runs/logic-e2e/kite-jev --max-budget-usd 30

python3 experiments/logic-ranker/e2e/e2e.py teardown --workspace <workspace>
```

`route-index`와 `jev`에는 같은 `routes.jsonl`과 `ROUTES.md`가 추가된다. `jev`에는 고정 질문·top-K를 담은 `JEV.md`와 `./jev`가 추가된다. Jev 비용은 proxy 로그(`control/jev-calls.jsonl`)에 남고 `run.json`의 `jev.cost_usd`에 기록된다.

## 평가

에이전트는 `findings/<name>/test.go`를 제출한다. harness는 테스트 함수 이름만 `-run`으로 실행해 무관한 패키지 테스트 실패를 배제한다. **pristine 취약·수정·decoy 트리**에서 각 3회 실행하고, 취약판은 관련 assertion 실패, 수정판은 통과, decoy는 같은 실패여야 `reproduced`다. 컴파일 실패·timeout·무관한 panic은 reject다. `semantic_review`는 별도 수동 검토 항목이다.

## Kite 2-arm development pilot (ADR 0006, superseded for e2e)

| 항목 | 순정 | Jev ranker |
| --- | ---: | ---: |
| 판정 | reproduced | reproduced |
| Claude 비용 | $1.436 | $1.348 |
| Jev 비용 | — | $0.0245 (130요청, 582,973토큰) |
| 총비용 | **$1.436** | **$1.373** |
| 턴 | 16 | 18 |
| 소요 시간 | 171초 | 224초 |
| 도구 호출 | 15 | 17 |
| 감사 | docker 0, network 0, subagent 0, parent-path 2 | docker 0, network 0, subagent 0, parent-path 2 |

- 두 arm 모두 `buildProxyURL` 경로 탐색 결함을 찾고 테스트를 제출했다.
- Jev arm은 130개 라우트를 한 번 채점해 `/namespaces/.../proxy/*path`를 top 1로 올렸고, 그 경로를 조사했다.
- 총비용 차이는 **$0.063 (4.4%)**로 작았다. Kite는 국소적이고 명시적인 가드라 순정도 빠르게 찾은 ceiling case다.
- `parent-path` 2건은 `../../TASK.md`와 `scratch/proxy.go.orig`처럼 workspace 안의 상대 경로였다. 실제 경계 이탈은 없었다.
- 한 사례·한 번씩의 파일럿이므로 Jev의 일반 효과로 해석하지 않는다.

원자료: `~/sift-runs/measurements/logic-e2e-kite/`.

3-arm r1에서도 결론은 같았다. vanilla $1.719/21턴, route-index $1.664/25턴, jev r2 $1.980/24턴으로 모두 `reproduced`였고, Jev는 대상 route를 2/130에 올렸지만 비용 이득이 없었다. 국소 결함에서는 ranker overhead만 남는다. 원자료: `~/sift-runs/measurements/logic-e2e-kite-r1/`.

## Vikunja 3-arm pilot

| 항목 | vanilla | route-index | jev |
| --- | ---: | ---: | ---: |
| 판정 | reproduced | reproduced | reproduced |
| Claude 비용 | $5.363 | $2.984 | $2.679 |
| Jev 비용 | — | — | $0.341 |
| 총비용 | **$5.363** | **$2.984** | **$3.019** |
| 턴 | 56 | 33 | 47 |
| 소요 시간 | 609초 | 286초 | 359초 |
| 감사 | 경계 이탈 없음 | workspace 내부 상대 경로 2건 | 경계 이탈 없음 |

- route index가 vanilla 대비 비용 44%, 턴 41%를 줄였다.
- Jev는 route-index를 이기지 못했다. Jev 355요청·8,114,410토큰을 썼고, 총비용은 $0.035 더 높았다.
- 고정 generic 질문에서 대상 route는 r1 **32/355(9.0%)**, r2 **19/355(5.4%)**였고 둘 다 top10 밖이었다. r1 에이전트는 top10을 읽은 뒤 `pkg/routes`에서 bucket/task route를 직접 grep해 찾았다. Jev ranking은 탐색을 대상으로 유도하지 못했다.
- arm당 2회의 파일럿이다. r1+r2 평균은 vanilla $4.549, route-index $2.820, jev $2.777이었다. 원자료: `~/sift-runs/measurements/logic-e2e-vikunja/`.

## Pocket ID 3-arm pilot

| 항목 | vanilla | route-index | jev (clean r4) |
| --- | ---: | ---: | ---: |
| 판정 | reproduced | reproduced | reproduced |
| Claude 비용 | $7.837 | $8.758 | $2.133 |
| Jev 비용 | — | — | $0.048 |
| 총비용 | **$7.837** | **$8.758** | **$2.181** |
| 턴 | 71 | 120 | 30 |
| 소요 시간 | 820초 | 881초 | 230초 |
| 감사 | clean | clean | clean |

- Jev ranking은 대상 route `POST /oidc/token`을 4/110(top10)에 올렸다. 깨끗한 r4는 vanilla보다 비용·시간 72%, route-index보다 75% 적었다.
- route-index는 이 state-machine 사례에서 도움이 되지 않았다. 결함은 route 등록이 아니라 `internal/service`의 상태 재확인이었다.
- Jev는 4회 중 2회 유효, 1회만 감사까지 깨끗했다. r2는 수정판에서 고쳐지지 않는 그룹 변형, r3는 과도한 테스트 단언으로 reject됐다. 4회 시도 $9.740, 유효 발견 2건당 $4.87이다.
- vanilla/route-index는 arm당 1회뿐이다. 원자료: `~/sift-runs/measurements/logic-e2e-pocketid/`.

## Arcane 3-arm pilot

| 항목 | vanilla r1 | vanilla r2 | route-index | jev |
| --- | ---: | ---: | ---: | ---: |
| 판정 | reproduced | reproduced | reproduced* | reproduced |
| 총비용 | $1.800 | **$2.213** | $3.049 | $3.041 |
| 턴 | 15 | 33 | 40 | 39 |
| 시간 | 146초 | 185초 | 258초 | 274초 |
| 감사 | docker 1 | clean | clean | clean |

- `cases.json`의 `test_file_dir` 버그(`internal/auth` → `backend/internal/auth`)를 고쳤다. route-index는 경로 수정 후 재평가해 `reproduced`로 정정했다. 원자료: `~/sift-runs/measurements/logic-e2e-arcane/`.
- Jev는 `GET /debug/pprof/`를 30/147로 올렸고 top10에 넣지 못했다. vanilla가 가장 빨랐고 ranker 두 arm은 약 52% 더 비쌌다.
- Kite와 함께 **국소 gate 결함에서는 ranker overhead**라는 결과를 뒷받침한다.

## Held-out 준비 상태 (2026-10-21)

- 후보 13개를 `heldout-candidates.json`에 고정했다. 현재 3-arm에 바로 쓸 수 있는 사례는 Gotify 하나다.
- oracle 검증: OpenList, Gotify, Semaphore. 셋 다 취약판 실패·수정판 통과를 확인했다.
- route coverage: Gotify 37개(대상 포함), OpenList 162개(대상 `/share/create` 누락), Semaphore 1개(gorilla/mux 미지원).
- confirmatory 실행 전에 extractor를 mux·helper 등록까지 확장하거나 Gin/Echo 사례로 8개를 채워야 한다. 자세한 gate는 [ADR 0008](../../../docs/adr/0008-held-out-case-pool-and-route-coverage-gate.md).

## 다음

개발 사례 4개를 마쳤다. blind held-out 사례를 선정하고, 질문·K·run 수를 결과와 무관하게 pre-register한 뒤 confirmatory 규모를 정한다.
