# Jev package 제품 결정 메모

- 날짜: 2026-10-21
- 상태: **초안, 결정 전**. 이 문서는 실행 승인이 아니라 결정 기준을 맞추기 위한 메모다.
- 관련: [ADR 0007](adr/0007-three-arm-ranker-evaluation-after-independent-review.md), [ADR 0008](adr/0008-held-out-case-pool-and-route-coverage-gate.md)

## 1. 이번에 결정할 것

다음 중 하나를 고른다.

| 선택 | 의미 |
| --- | --- |
| **A. Jev package 채택** | `unit bundle + Jev CLI + frozen guide`를 제품 기본 workflow에 넣는다. |
| **B. index만 채택** | bundle/extraction은 남기고 Jev ranking은 뺀다. |
| **C. verification에 투자** | ranking보다 test 작성·검증 지원을 제품의 핵심으로 둔다. |
| **D. 보류/중단** | 현재 범위에서는 제품화하지 않는다. |

이 메모는 “Jev가 좋은가?”가 아니라 **“다음 개발 사이클에 무엇을 넣을 것인가”**를 결정하기 위한 것이다.

## 2. 지금까지의 증거

- 개발 사례 4개(Kite, Vikunja, Pocket ID, Arcane)는 결과가 이질적이다.
  - Vikunja: route-index가 vanilla보다 쌌고, Jev는 route-index와 거의 같았다.
  - Pocket ID: Jev가 가장 쌌지만 4회 중 clean valid는 1회였고, 전체 시도 비용은 $9.740이었다.
  - Kite/Arcane: vanilla가 이미 빠르거나 가장 빨랐다.
- 3-arm의 route-index는 **제품 비교 대상이 아니라 ablation**이다. Primary는 `vanilla` vs `vanilla + Jev package`로 둔다.
- 새 `unit bundle + Jev package`는 아직 end-to-end로 실행된 적이 없다. 개발 사례는 route bundle 기준이다.
- post-cutoff + oracle + oracle-function coverage를 통과한 사례는 현재 OpenList 1개다.

## 3. Treatment 정의 (동결 대상)

### vanilla
- source, task, `tb` test/exec 도구
- Jev 없음, 사전 생성 bundle 없음

### jev
- vanilla와 같은 source/task/tools
- **generic unit bundle**: vulnerable source만 입력으로 생성, fix/oracle/advisory 미사용
- Jev CLI, 고정 질문, top-K, 고정 guide
- bundle 생성 비용과 Jev 비용을 포함한 all-in cost

### 비용 회계
- **Primary: cold-start**. bundle 생성 + agent + Jev + 검증을 모두 포함한다.
- **Secondary: warm-cache**. 재사용 횟수 가정을 명시한 경우만.
- 실패·reject·audit 위반 run의 비용도 남긴다. 성공 run만 골라 평균하지 않는다.

### Eligibility
- post-cutoff, offline build, behavior oracle(취약 FAIL / 수정 PASS / decoy FAIL), 독립 project.
- **oracle coverage는 eligibility가 아니라 diagnostic**으로 기록한다. bundle이 target 함수를 놓친 것도 제품 결과다.
- 한 project의 여러 bug는 독립 사례로 세지 않는다.

## 4. 실험 순서

### Stage 0 — treatment 개발 (held-out 사용 금지)
- 개발 사례 4개에서 새 package를 arm당 3회 실행
- 확인할 것:
  - Pocket ID의 이득이 유지되는가
  - Vikunja에서 route-index에 준하는가
  - Kite/Arcane에서 overhead가 얼마인가
  - rejection/verification burden이 악화되는가
- 결과가 나쁘면 held-out을 쓰지 않고 treatment를 수정한다.
- 이 단계의 결과는 exploratory이며 confirmatory에 재사용하지 않는다.

### Stage 1 — 8-case decision pilot
- 독립 project 8개, post-cutoff, behavior oracle
- arm당 5회, 순서 무작위화
- primary: case별 all-in cost-to-first-validated-finding의 geometric mean ratio
- guardrail: valid-find rate, rejection rate, wall time
- **confirmatory가 아니라 decision pilot**이다. 8개는 큰 일관된 효과 또는 futility만 판정한다.

### Stage 2 — 확장 (Stage 1이 조건을 통과할 때만)
- 24 cases × 5 runs × 2 arms를 목표로 한다.
- Stage 1 결과를 보고 blinded variance로 표본 수를 다시 계산한다.
- Stage 1에서 efficacy claim을 하지 않는다.

## 5. 결정 규칙 (초안)

Stage 1 결과에 대해:

| 결과 | 결정 |
| --- | --- |
| geometric mean cost ratio ≤ 0.70, valid-find rate 악화 ≤ 10pp, rejection 악화 ≤ 10pp, 8개 중 7개 이상 Jev 우세 | **A 검토** — Stage 2로 |
| ratio < 0.85, 5~6/8 Jev 우세, guardrail 통과 | **Stage 2 확장** — efficacy claim은 Stage 2까지 보류 |
| ratio ≥ 1.0, 또는 4/8 이하 Jev 우세, 또는 Jev arm의 0-valid가 더 많음 | **futility stop** — B/C/D 재검토 |
| interval이 넓고 방향이 갈림 | **inconclusive** — 사례 pool 또는 질문을 바꾸기 전에 결정 보류 |

- 8개에서 p-value만으로 “성공”을 선언하지 않는다.
- 최종 confirmatory 판정은 Stage 2의 exact Wilcoxon one-sided test와 실질적 threshold를 함께 쓴다.
- 가장 유리한 project를 제거해도 결론이 유지되는지 sensitivity analysis를 한다.

## 5b. Stage 0 결과 (2026-10-25)

개발 사례 4개에서 `vanilla` vs `unit-Jev`를 arm당 3회 실행했다. File-level unit bundle, Jev cost 포함, semantic acceptance 기준.

| 사례 | vanilla | unit-Jev | all-in ratio | valid |
| --- | ---: | ---: | ---: | --- |
| Kite | $1.658 | $1.710 | 1.031 | 3/3 vs 3/3 |
| Vikunja | $2.213 | $2.045 | 0.924 | 3/3 vs 2/3 |
| Pocket ID | $3.823 | $2.513 | 0.657 | 3/3 vs 2/3 |
| Arcane | $2.602 | $2.101 | 0.808 | 3/3 vs 3/3 |

- all-in geometric mean ratio: **0.843** (unit-Jev가 약 15.7% 낮음)
- valid-only geometric mean ratio: **0.866**
- 전체 시도 비용 / valid finding: vanilla **$2.574**, unit-Jev **$2.511**
- 총 valid: vanilla **12/12**, unit-Jev **10/12**
- unit-Jev 실패 2건: Vikunja r2 Docker audit violation, Pocket ID r3 rejected test(positive control이 수정판에서 실패)
- target file의 unit rank: Pocket ID **1/127**, Vikunja **2–4/507**, Arcane **39–41/264**, Kite **76/112**
- Jev 자체 비용은 사례당 $0.009–$0.043로 작았다.

해석:

- 파일 단위 ranking이 좋은 hard case(Pocket ID, Vikunja)에서는 비용 이득이 크다.
- ceiling case(Kite)에서는 overhead가 발생한다.
- **비용 이득보다 validity 손실이 더 중요한 신호**다. Pocket ID r3는 test construction 실패, Vikunja r2는 Docker 경계 위반이다.
- Stage 0는 exploratory이며, treatment를 confirmatory에 바로 고정하지 않는다. Docker isolation/test reliability를 먼저 다룬다.

### 왜 이런 차이가 났나

1. **Jev 비용 자체는 원인이 아니다.** 사례당 Jev 비용은 $0.009–$0.043이고, 차이는 대부분 agent의 턴·tool call에서 나왔다.
2. **target file이 top-K에 있는가가 탐색 비용을 좌우했다.**
   - Pocket ID: `internal/service/oidc_service.go` **1/127**. 세 실행 모두 top-1. unit-Jev가 23~49턴으로 vanilla 40~56턴보다 짧았다.
   - Vikunja: `pkg/models/kanban_task_bucket.go` **2–4/507**. top-10 안. 비용은 7.6% 낮았지만 vanilla도 이미 빨라 차이가 작았다.
   - Kite: `pkg/kube/proxy.go` **59–77/112**. top-10 밖. unit-Jev는 `ls`/JEV/ranking을 읽는 overhead가 붙어 18~27턴으로 vanilla 15~21턴보다 많았다.
   - Arcane: fix file `internal/auth/middleware.go`는 **39–41/264**였지만, **route registration file `api/handlers/diagnostics.go`가 1/264**였다. Jev가 route 문맥을 먼저 노출했고 agent가 auth middleware로 따라가 16~35턴으로 vanilla 23~45턴보다 짧았다.
3. **Jev는 “정답 파일”보다 “결정 경로 입구”를 잘 찾았다.** Arcane이 대표적이다. fix file rank는 중간이었지만 pprof route/diagnostics가 top-1이라 탐색이 줄었다.
4. **validity 손실은 ranking 실패가 아니라 test construction/경계 문제다.**
   - Pocket ID r3: positive control이 수정판에서 실패했다. top-1 target을 빨리 찾은 대신 test의 positive control을 충분히 검증하지 않았다.
   - Vikunja r2: `docker`를 직접 호출해 audit violation이 났다. Jev ranking과 무관한 harness 경계 문제지만, 그 run은 invalid가 됐다.
5. **비용/valid는 거의 tie다.** vanilla는 12/12 valid, unit-Jev는 10/12 valid였다. 전체 시도 비용을 valid 수로 나누면 $2.574 vs $2.511로 차이가 2.5%뿐이다. “싸다”는 성공 run만 보면 크지만, 실패 비용을 포함하면 이득이 줄어든다.

따라서 Stage 0의 진짜 병목은 **ranker 비용이 아니라 verification/test authoring과 harness boundary**다. Stage 1 전에 이 두 가지를 고쳐야 한다.

## 6. 이 결과가 나오면 제품을 단순화할 것인가

다음 중 하나라도 관측되면 Jev를 기본 제품에서 빼는 것을 진지하게 검토한다.

- index-only가 package와 비슷한 성능을 낸다.
- 이득이 대부분 extraction에서 나오고 ranking은 증분이 없다.
- 쉬운 사례의 overhead가 어려운 사례의 이득을 상쇄한다.
- rejection/verification burden이 커져 사람의 시간이 줄지 않는다.
- unit bundle 생성 비용이 절감액을 잠식한다.

## 7. 아직 모르는 것

- generic unit bundle이 실제 repo 규모에서 얼마나 큰가. Jev 비용·latency가 제품화 가능한가.
- 사용자는 비용, 성공 확률, latency, 검토 부담 중 무엇을 가장 중요하게 보는가.
- 제품의 support boundary를 어디까지로 볼 것인가(Go version, framework, repo size).
- post-cutoff 독립 사례를 8개 이상 확보할 수 있는가.
- Docker isolation, finding-level adjudication, first-submission cost timestamp를 닫을 수 있는가.

## 8. 다음 행동

- [ ] 이 메모의 결정·threshold를 팀이 합의
- [ ] Stage 0: 새 package를 개발 사례에서 end-to-end 실행
- [ ] Stage 0 결과로 treatment freeze
- [ ] harness P0: Docker broker, finding-level adjudication, submission cost snapshot
- [ ] case supply: post-cutoff 8개 독립 사례 확보
- [ ] Stage 1 decision pilot
- [ ] Stage 2 필요 여부 결정

## 9. 하지 않을 것

- held-out case를 treatment 디버깅에 쓰지 않는다.
- oracle coverage를 eligibility로 쓰지 않는다.
- 8-case 결과를 confirmatory 또는 “Jev ranking의 효과”로 부르지 않는다.
- 8개를 맞추기 위해 cutoff·독립성·oracle 기준을 완화하지 않는다.
- reviewer가 P0를 더 찾는다는 이유로 결정을 무기한 미루지 않는다.
