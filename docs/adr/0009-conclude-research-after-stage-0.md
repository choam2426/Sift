# ADR 0009: Stage 0까지의 결과로 연구를 마친다

- 날짜: 2026-11-08
- 상태: 채택. 이 ADR이 연구의 최종 결론이다. ADR 0001~0008과 [제품 결정 메모](../jev-package-decision-memo.md)는 여기까지의 경과 기록으로 남는다.
- 관련: [ADR 0001](0001-jev-collaboration-research-charter.md), [ADR 0006](0006-logic-bug-ranker-experiment.md), [ADR 0007](0007-three-arm-ranker-evaluation-after-independent-review.md), [ADR 0008](0008-held-out-case-pool-and-route-coverage-gate.md)

## 맥락

이 연구의 질문은 **Jev(SystemOne)를 코딩 에이전트에 붙이면 실제 취약점 발견의 비용 대비 성과가 좋아지는가**였다([ADR 0001](0001-jev-collaboration-research-charter.md)). 경과는 다음과 같다.

1. **C/C++ 메모리 안전성 파일럿**: CyberGym·OSS-Fuzz 사례로 testbed를 만들고, 학습 기준일 이후 사례 3건을 고정 소스 빌드로 준비했다. 단독 소비량을 두 번 측정했다([ADR 0002](0002-cybergym-images-as-shared-testbed.md)~[0005](0005-pinned-source-build-for-post-cutoff-cases.md)).
2. **Go 인가 로직 버그로 전환**: Jev를 검증자가 아니라 후보 순위기로 쓰기로 하고, 개발 사례 4개(Kite, Vikunja, Pocket ID, Arcane)를 고정했다([ADR 0006](0006-logic-bug-ranker-experiment.md)).
3. **route 단위 3-arm 파일럿**: `vanilla`/`route-index`/`jev`를 비교했다([ADR 0007](0007-three-arm-ranker-evaluation-after-independent-review.md)).
4. **held-out 사례 탐색**: confirmatory용 사례 8개를 찾았으나 기준을 모두 통과한 사례가 하나뿐이었다([ADR 0008](0008-held-out-case-pool-and-route-coverage-gate.md)).
5. **제품 질문으로 재정의**: 독립 리뷰와 논의 끝에 primary 비교를 `vanilla` vs `vanilla + Jev package` 2-arm으로 바꾸고, 평가 목표를 정답 위치 찾기가 아니라 **탐색 비용 감소**로 정했다([제품 결정 메모](../jev-package-decision-memo.md)).
6. **Stage 0**: 개발 사례 4개에서 file 단위 unit bundle + Jev를 arm당 3회 실행했다.

## 결정

**Stage 0까지의 결과로 연구를 마친다.** Stage 1(held-out 8개 decision pilot)과 Stage 2(24개 confirmatory)는 실행하지 않는다.

이유:

- 탐색적 수준에서 연구 질문에 대한 답의 방향과 조건이 나왔다. 아래 결론이 그것이다.
- confirmatory로 가려면 학습 기준일 이후의 독립 사례가 8개 이상 필요한데, 기준을 모두 통과한 사례는 OpenList 하나였다. 사례 공급 자체가 별도 연구 과제다.
- Stage 0에서 드러난 병목(에이전트의 test 작성·검증)은 Jev ranking과 별개의 문제다. 이를 고치는 일은 이 연구의 질문 밖이다.

## 결론

**Jev 기반 탐색 보조는 탐색이 긴 문제에서 에이전트의 탐색 비용을 줄였다. 하지만 이미 짧게 끝나는 문제에서는 overhead가 되었고, 발견을 검증 가능한 test로 만드는 단계의 실패가 비용 이득을 대부분 상쇄했다.**

모든 수치는 개발 사례 4개, arm당 1~4회의 탐색적 결과다. 일반 효과로 주장하지 않는다.

### 1. Jev는 정답보다 탐색의 입구를 잘 찾았다

Stage 0에서 Jev는 네 사례 모두 수정 파일이나 진입점 파일을 상위 4위 안에 올렸다.

| 사례 | 수정 파일 순위 | 진입점 파일 순위 |
| --- | ---: | ---: |
| Pocket ID | **1/127** | — |
| Vikunja | **2–4/507** | — |
| Arcane | 39–41/264 | **1/264** (`api/handlers/diagnostics.go`) |
| Kite | 59–77/112 | **3/112** (`pkg/proxy/handler.go`) |

Arcane에서는 수정 파일 순위가 중간이었지만, 진입점이 1위여서 에이전트가 그 경로를 따라 수정 지점에 도달했다. 정답 함수의 순위는 Jev의 가치를 재는 지표로 적합하지 않다.

진입점 파일은 결과를 본 뒤 사람이 지정한 진단용 표시다.

### 2. 이득은 vanilla의 탐색이 길수록 컸다

Stage 0(file 단위 unit bundle + Jev, arm당 3회, Claude·Jev 비용 포함):

| 사례 | vanilla 평균 | unit-Jev 평균 | 비용 비율 | 턴 (vanilla → Jev) | valid |
| --- | ---: | ---: | ---: | ---: | --- |
| Pocket ID | $3.823 | $2.513 | **0.657** | 49.0 → 32.0 | 3/3 → 2/3 |
| Arcane | $2.602 | $2.101 | **0.808** | 35.0 → 27.3 | 3/3 → 3/3 |
| Vikunja | $2.213 | $2.045 | 0.924 | 28.0 → 25.0 | 3/3 → 2/3 |
| Kite | $1.658 | $1.710 | 1.031 | 17.7 → 22.3 | 3/3 → 3/3 |

- 비용 비율의 기하평균은 **0.843**이다.
- 이득의 순서는 vanilla 평균 턴 수의 순서와 같다. 탐색이 49턴 걸리던 Pocket ID는 34% 줄었고, 18턴에 끝나던 Kite는 3% 늘었다.
- Jev 호출 비용은 Jev arm 총비용의 **1.1%**였다. 비용 차이는 Jev 요금이 아니라 에이전트의 턴 수에서 나왔다.
- 경과 시간은 Pocket ID에서만 줄었다. Vikunja는 507개 unit을 채점하는 시간 때문에 26% 늘었다.

### 3. 검증 실패가 비용 이득을 상쇄했다

- valid finding: vanilla **12/12**, unit-Jev **10/12**
- 전체 시도 비용을 valid finding 수로 나누면 vanilla **$2.574**, unit-Jev **$2.511**로 차이는 **2.5%**다.
- unit-Jev의 실패 2건은 탐색 실패가 아니었다.
  - Pocket ID r3: 대상 결함을 찾았지만, 수정판에서도 통과해야 할 positive control이 실패하는 test를 제출했다.
  - Vikunja r2: 에이전트가 호스트 Docker를 직접 호출해 실행 경계를 넘었다.
- route 단위 파일럿에서도 같은 양상이 있었다. Pocket ID의 Jev arm은 4회 중 2회만 재현에 성공했고, 감사까지 통과한 것은 1회였다.

따라서 이 방식이 제품이 되려면 **탐색 보조보다 test 작성·검증 지원이 먼저**다.

### 4. route 단위 index만으로도 효과가 날 수 있다

route 단위 3-arm 파일럿(arm당 1~2회, 사례별 결과는 [ADR 0007](0007-three-arm-ranker-evaluation-after-independent-review.md)):

| 사례 | 결함 모양 | vanilla | route-index | jev | 관측 |
| --- | --- | ---: | ---: | ---: | --- |
| Kite | 국소 proxy path 검사 | $1.719 | $1.664 | $1.980 | 차이 없음 |
| Vikunja | URL·body 객체 인가 | $4.549 | **$2.820** | $2.777 | index가 주된 이득 |
| Pocket ID | service 내부 상태 재확인 | $7.837 | $8.758 | **$2.181**¹ | Jev 이득, 재시도 필요 |
| Arcane | middleware gate | **$2.006** | $3.049 | $3.041 | overhead |

¹ 4회 시도 중 감사를 통과한 유효 실행 1회. 4회 총비용은 $9.740이다.

Vikunja에서는 Jev 없이 route 목록만 줘도 비용이 38% 줄었다. Jev ranking 자체의 증분 효과는 이 연구에서 분리하지 못했다.

### 5. 평가 방법에서 얻은 것

- **학습 기준일 이후의 Go 인가 사례는 드물다.** 공개 advisory에서 후보 20건을 추출했으나 수정 커밋이 기준일(2026-06-30) 이후이고, 동작 오라클이 있고, bundle이 오라클 함수를 포함하는 사례는 OpenList 하나였다.
- **AST만으로 만든 route bundle은 인가 결정을 놓친다.** 결정 함수가 패키지 경계 뒤에 있으면 bundle에 들어오지 않았다. SSA call graph 보강(`extract_calls`)으로 OpenList의 오라클 함수를 포함시킬 수 있었다.
- **target coverage를 사례 선정 기준으로 쓰면 결과가 Jev에 유리하게 편향된다.** 제품 비교에서는 coverage를 결과 변수로 기록해야 한다.
- **평가 harness의 결함이 결과를 뒤집을 수 있다.** Arcane에서는 테스트 복사 경로 버그 하나로 정상 발견이 기각됐다. decoy 트리, 의미 검토(semantic adjudication), 감사 위반 무효화, Claude·Jev 통합 비용 상한을 단계적으로 추가했다.
- **C/C++ 파일럿**: 단독 실행 소비량은 libzip $6.13(발견 재현)에서 libhevc $28.30(발견 없음, 경계 위반 표시)까지 벌어졌다. 사례 난이도에 따라 비용 상한이 실제로 걸린다([ADR 0003](0003-cost-as-matched-budget-and-first-run-measures-consumption.md)).

## 주장하지 않는 것

- Jev가 에이전트의 취약점 탐색 비용을 일반적으로 줄인다.
- Jev ranking이 route·unit index보다 낫다.
- Go 인가 버그 전반이나 다른 언어·결함 유형으로의 일반화.
- 알려진 결함의 재발견을 넘어선 신규 취약점 발견 능력.

## 한계

- 개발 사례 4개로 extractor·가이드·harness를 개발했고, 같은 사례로 Stage 0를 측정했다. 독립 held-out 결과가 아니다.
- 반복이 arm당 1~4회라 실행 간 변동이 사례 간 차이와 비슷한 크기다. 예: route 파일럿의 Vikunja vanilla는 $3.73~$5.36이었다.
- 사례 선정·task scope·질문은 결함을 아는 사람이 정했다.
- 모든 사례는 공개된 결함이다. 학습 기준일 이후 사례만 써도 모델이 프로젝트 코드를 학습했을 가능성은 남는다.
- 의미 검토는 연구자 한 명이 arm을 알고 수행했다.
- 비용은 Claude Code의 정가 기준 추정치다.

## 후속 연구를 한다면

이 연구의 결론을 confirmatory로 확인하거나 넓히려면 다음이 필요하다. 이 목록은 미해결 과제가 아니라, 새 연구를 설계할 때의 출발 조건이다.

1. 학습 기준일 이후의 **독립 프로젝트 사례 공급**. 사례 1개당 동작 오라클과 오프라인 빌드가 필요하다.
2. 에이전트가 호스트 Docker에 접근하지 못하는 **실행 broker**와, finding 단위로 기술 판정과 의미 검토를 묶는 평가기.
3. **test 작성·검증 지원**을 별도 처리군으로 두는 설계. Stage 0의 병목이 여기 있었다.
4. Jev ranking의 증분 효과를 보려면 같은 unit bundle을 순서 고정으로 주는 index-only arm.
5. 표본 크기: 독립 통계 리뷰는 Stage 0 수준의 사례 간 변동에서 비용 30% 절감을 검정력 80%로 보려면 약 24개 사례 × arm당 5회가 필요하다고 추정했다. [제품 결정 메모](../jev-package-decision-memo.md) §4의 Stage 2 계획이 이 규모다.

## 산출물

| 산출물 | 위치 |
| --- | --- |
| Go 로직 버그 e2e harness (`vanilla`/`route-index`/`jev`/`jev-unit`, 격리 컨테이너, 취약·수정·decoy 판정, 감사, 통합 비용 상한) | `experiments/logic-ranker/e2e/` |
| route 추출기 (Gin/Echo/Huma/gorilla-mux, helper 등록) | `experiments/logic-ranker/extract_routes/` |
| SSA call graph 보강 | `experiments/logic-ranker/extract_calls/` |
| 함수·file 단위 unit 추출기 | `experiments/logic-ranker/extract_units/` |
| C/C++ 메모리 안전성 testbed | `testbed/` |
| 실행별 결과 (46회)와 Stage 0 Jev 순위 | `results/` |
| 결정 기록 | `docs/adr/`, `docs/jev-package-decision-memo.md` |

에이전트 전사, 서드파티 소스를 포함한 원자료, 독립 리뷰 원문은 저장소 밖(`~/sift-runs/`)에 두었고 공개하지 않는다.

## 출처

- 실행별 수치: `results/runs.csv`. Stage 0 순위: `results/stage0-jev-file-ranks.csv`
- 단계별 근거: [ADR 0003](0003-cost-as-matched-budget-and-first-run-measures-consumption.md), [ADR 0006](0006-logic-bug-ranker-experiment.md), [ADR 0007](0007-three-arm-ranker-evaluation-after-independent-review.md), [ADR 0008](0008-held-out-case-pool-and-route-coverage-gate.md), [제품 결정 메모](../jev-package-decision-memo.md)
