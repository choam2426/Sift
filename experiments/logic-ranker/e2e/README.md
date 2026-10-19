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
- arm당 1회의 파일럿이다. 원자료: `~/sift-runs/measurements/logic-e2e-vikunja/`.

## 다음

Vikunja 3-arm을 반복해 route-index vs jev 차이가 우연인지 확인하고, Pocket ID 3-arm을 실행한다. 그 뒤 blind held-out 사례로 confirmatory 규모를 정한다.
