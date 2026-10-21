# ADR 0007: Jev ranker는 3-arm으로 평가하고, 질문·K·사례를 동결한다

- 날짜: 2026-10-19
- 상태: 채택. [ADR 0006](0006-logic-bug-ranker-experiment.md)의 2-arm e2e 계획을 대체한다.
- 관련: [ADR 0001](0001-jev-collaboration-research-charter.md), [ADR 0003](0003-cost-as-matched-budget-and-first-run-measures-consumption.md), [ADR 0006](0006-logic-bug-ranker-experiment.md)

## 맥락

Mythos 5.1과 GPT-6 Astra가 ADR 0006의 설계를 독립 리뷰했고, 둘 다 **REVISE**를 냈다. 핵심 지적은 다음과 같다.

- Jev arm만 route bundle·guide·ranking을 받아 **Jev ranking과 packaging이 뒤섞였다.**
- Stage 1의 사례별 질문은 fix를 아는 사람이 작성해 **ceiling 값**이다.
- arm당 1회, 사례 4개로는 효율을 주장할 수 없다. Kite의 4.4% 차이는 run noise 범위다.
- “취약판 실패”가 컴파일 실패·timeout·무관한 panic도 통과시킨다.
- $30 상한이 Kite에서 걸리지 않아 “상한 아래 비용”이 변별력을 갖지 못한다.
- 추출·bundle 비용이 Jev arm에 무료로 주어졌다.
- post-cutoff 공개만으로는 오염을 통제하지 못한다. 웹·git history·fix 설명을 차단해야 한다.
- 진짜 driver가 Jev가 아니라 **route extraction/bundle**일 수 있다.

## 결정

1. **3-arm으로 평가한다.**
   - `vanilla`: 소스·도구·조사/검증 가이드만. route bundle 없음.
   - `route-index`: 같은 route bundle과 가이드, **Jev 없이 고정 순서**(사전 등록한 random/alphabetical order).
   - `jev`: 같은 route bundle과 가이드, Jev ranker CLI와 고정 질문·top-K.
   - `vanilla` vs `route-index`는 bundle/extraction의 효과, `route-index` vs `jev`는 ranking의 증분 효과를 뜻한다.
2. **Jev는 ranker다.** 점수는 우선순위 신호이며 증거가 아니다. Jev에게 검증·설명·위치를 요구하지 않는다.
3. **질문과 K를 동결한다.** 사례별 oracle 질문은 ceiling 진단으로만 남기고, 실행 전에 bug-class별 generic 질문과 K를 고정한다. 실행 중 agent가 추가 질문을 하면 모두 기록하되, 사전 질문 결과와 분리해 보고한다.
4. **주 지표는 cap에서 censoring한 cost-to-first-validated-finding이다.** 성공 확률을 함께 보고한다. “상한 아래 총비용”만으로 우열을 주장하지 않는다. 보조 지표는 turns, wall time, Jev 요청·토큰, extraction 비용, false positive다.
5. **사례는 blind하게 고른다.** 현재 Kite·Pocket ID·Vikunja·Arcane은 development case다. confirmatory에는 Stage 1 순위를 보지 않은 사람이 고른 held-out Go authz 사례 8~12개를 쓴다. Kite는 ceiling/control, Vikunja는 informative hard case로 둔다.
6. **평가기를 강화한다.**
   - 제출 테스트는 취약·수정 트리 모두에서 컴파일되어야 한다.
   - 취약판 실패는 관련 assertion failure여야 한다. 컴파일 실패·timeout·무관한 panic은 reject.
   - 트리별 3회 반복해 모두 같은 결과여야 한다.
   - decoy tree(무관한 변경)에서도 같은 실패가 재현되어야 한다.
   - `.git`·fix 이력·advisory를 제거하고 네트워크를 차단한다.
   - report/test를 blind adjudication으로 검토해 대상 route/조건이 같은지 확인한다.
7. **오염을 통제한다.** agent와 Jev 모두 웹을 쓰지 않고, Jev artifact와 training exclusion을 기록한다. 공개 시점만으로 오염이 없다고 주장하지 않는다.
8. **추출 비용을 기록한다.** route extraction/bundle 생성은 사례 준비 비용으로 별도 기록하고, `route-index`·`jev`에 같은 bundle을 제공한다. 한쪽에만 무료로 주지 않는다.
9. **표본 계획을 단계화한다.** 먼저 3-arm × 2 cases × 2 runs 파일럿으로 분산을 잰다. confirmatory는 5~10 runs/arm/case, 8~12 blind cases를 목표로 하되, pilot 분산으로 power를 계산해 실행 전에 고정한다.
10. **판정 규칙을 미리 정한다.** Jev ranking은 `jev`가 `route-index`를 주 지표에서 이기고, 사례별 paired 분석의 신뢰구간이 0을 제외할 때만 효과가 있다고 주장한다. `route-index`가 `vanilla`를 이기면 extractor/bundle이 제품의 핵심이라는 결론을 허용한다.

## 현재 결과의 지위

- Stage 1 route rank(Kite 1/130, Pocket ID 2/110, Vikunja 28/355, Arcane 18/147)는 **oracle-informed ceiling**이다. 성능 주장에 쓰지 않는다.
- Kite e2e(순정 $1.436 vs Jev $1.373)는 **development pilot**이다. Jev ranking의 효과로 해석하지 않는다.
- 두 결과 모두 3-arm confirmatory의 가설 생성 자료로만 쓴다.

## Vikunja 3-arm 파일럿 (2026-10-19)

Vikunja 한 사례로 세 arm을 각 1회 실행했다. 세 arm 모두 `reproduced`였다.

| 항목 | vanilla | route-index | jev |
| --- | ---: | ---: | ---: |
| Claude 비용 | $5.363 | $2.984 | $2.679 |
| Jev 비용 | — | — | $0.341 |
| 총비용 | $5.363 | **$2.984** | $3.019 |
| 턴 | 56 | 33 | 47 |
| 소요 시간 | 609초 | 286초 | 359초 |
| 감사 | 경계 이탈 없음 | workspace 내부 상대 경로 2건 | 경계 이탈 없음 |

- route index를 제공한 `route-index`가 vanilla보다 비용 44%, 턴 41%를 줄였다.
- `jev`는 `route-index`를 이기지 못했다. Jev 355요청·811만 토큰을 썼고, 총비용은 $0.035 더 높았다.
- 이는 독립 리뷰의 경고와 일치한다. **구조화된 route extraction이 주된 driver일 수 있고, Jev ranking의 증분 효과는 아직 관측되지 않았다.**
- arm당 1회의 파일럿이므로 confirmatory 결과가 아니다.

## Vikunja에서 Jev 사용 방식 확인

Jev arm은 사전 고정한 generic 질문 하나로 `routes.jsonl` 355개를 모두 채점했다. `./jev rank ... --top 10`을 실행했고, 명령이 120초를 넘어 background로 넘어간 뒤 출력 파일을 읽었다.

- Jev 점수: 355개 scored, 5개 stats 호출(채점 오류 없음). 입력 8,114,410토큰, 비용 $0.341.
- 대상 route `PUT /projects/{project}/views/{view}/buckets/{bucket}/tasks`의 점수는 **0.45**, 순위 **32/355 (9.0%)**였다. Stage 1의 oracle 질문 순위 28/355와 비슷하거나 조금 나빴다.
- 상위 10개는 `/tasks/{projecttask}/labels`(0.83), `/tasks/:projecttask/labels`(0.63), `/tasks/:task/relations`(0.62) 등이었고, 대상 route는 top10에 없었다.
- 에이전트는 top10 출력을 읽었지만, 이후 `pkg/routes`에서 bucket/task route를 직접 grep해 대상을 찾았다. 즉 이 실행에서 Jev ranking은 탐색을 대상으로 유도하지 못했고, route index와 소스 검색이 발견을 이끌었다.
- 결과적으로 `route-index`($2.984)와 `jev`($3.019)의 차이는 Jev에 유리하지 않았다. Jev 비용 $0.341과 순위 계산 시간이 추가됐다.

이 한 번의 실행은 “generic 질문으로도 Jev가 유용한 ranking을 준다”는 가설을 지지하지 않는다. 다음 반복에서는 질문을 더 구체화하거나, top-K를 넓히거나, Jev를 후보 필터가 아닌 보조 신호로만 쓰는 방식을 비교해야 한다.

## Vikunja 반복 (r1 + r2)

같은 사례·같은 generic 질문·top-10으로 3-arm을 한 번 더 실행했다. r2 순서는 seed 20261020으로 vanilla → jev → route-index였다. 여섯 실행 모두 `reproduced`다.

| arm | r1 | r2 | 평균 비용 | 평균 턴 | 평균 시간 |
| --- | ---: | ---: | ---: | ---: | ---: |
| vanilla | $5.363 | $3.735 | **$4.549** | 51.0 | 506.8초 |
| route-index | $2.984 | $2.655 | **$2.820** | 43.5 | 289.5초 |
| jev | $3.019 | $2.535 | **$2.777** | 39.0 | 355.6초 |

- route-index는 vanilla 대비 평균 비용 38%, 시간 43%를 줄였다.
- jev는 route-index보다 평균 $0.042(1.5%) 싸고 턴이 4.5 적지만, 시간은 66초 길다. 2회 반복으로는 우연과 구분할 수 없다.
- generic 질문에서 대상 route는 r1 32/355(9.0%), r2 19/355(5.4%)였고 두 번 모두 top-10 밖이었다. r1 agent는 top-10을 읽은 뒤 소스 grep으로 대상을 찾았다.
- 현재까지 가장 강한 결론은 **구조화된 route extraction이 주된 driver**라는 것이다. Jev ranking의 증분 효과는 아직 관측되지 않았다.

## Pocket ID (state-machine 사례)

Pocket ID는 OIDC refresh token의 인가 상태를 다시 확인하지 않는 사례다. Vikunja와 달리 route path 자체가 아니라 `internal/service`의 상태 전이가 결함의 위치다.

| arm | 실행 | 총비용 | 턴 | 시간 | 판정 | 감사 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| vanilla | 1 | $7.837 | 71 | 820초 | reproduced | clean |
| route-index | 1 | $8.758 | 120 | 881초 | reproduced | clean |
| jev | r1 | $2.758 | 29 | 379초 | reproduced | docker 1 |
| jev | r2 | $2.446 | 24 | 265초 | rejected | parent-path 1 |
| jev | r3 | $2.355 | 24 | 261초 | rejected | clean |
| jev | r4 | **$2.181** | 30 | 230초 | **reproduced** | **clean** |

- 고정 generic 질문에서 대상 route `POST /oidc/token`은 **4/110 (top10 안)**이었다. Vikunja(32/355, 19/355)와 달리 Jev ranking이 대상 route를 top10에 올렸다.
- 깨끗한 유효 실행(r4)은 vanilla보다 비용 72%, 시간 72% 적고, route-index보다 비용 75%, 시간 74% 적다.
- **route-index는 이 사례에서 도움이 되지 않았다.** vanilla보다 비용·턴·시간이 모두 늘었다. 결함이 route 등록이 아니라 service 내부의 상태 재확인에 있었기 때문으로 보인다.
- **Jev의 비용 이득은 크지만 신뢰성이 낮다.** 4회 중 2회만 유효했고, 그중 감사까지 깨끗한 것은 1회다. r2는 수정판에서 고쳐지지 않는 그룹 변형을, r3는 대상 버그는 맞혔지만 수정판에서도 통과해야 할 테스트에 토큰 레코드 삭제 단언을 넣어 reject됐다.
- 4회 시도 비용을 모두 합치면 $9.740이고, 유효 발견 2건당 $4.87, 깨끗한 유효 발견 1건당 $9.74다. 전자는 vanilla보다 38% 싸지만, **한 번의 시도로 유효 발견을 보장하지는 못한다.**
- vanilla/route-index는 arm당 1회뿐이므로 이 절도 파일럿이다. 다만 효과 크기가 커서 “Pocket ID 같은 state-machine 사례에서는 route index보다 Jev가 더 유망하다”는 방향은 지지된다.

## Kite (ceiling case)

Kite는 국소적인 proxy path 검사 결함이라 vanilla도 빠르게 찾는 ceiling case다. 세 arm 모두 `reproduced`였다.

| arm | 실행 | 총비용 | 턴 | 시간 | 감사 |
| --- | --- | ---: | ---: | ---: | --- |
| vanilla | 1 | $1.719 | 21 | 169초 | parent-path 4(내부 경로) |
| route-index | 1 | $1.664 | 25 | 207초 | clean |
| jev | r1 | $1.858 | 26 | 256초 | docker 1 |
| jev | r2 | $1.980 | 24 | 273초 | parent-path 1(내부 경로) |

- Jev는 대상 route `GET /namespaces/:namespace/:kind/:name/proxy/*path`를 **2/130 (top10)**에 올렸다. 그런데도 비용 이득이 없었다.
- route-index는 vanilla보다 3.2% 쌌지만 턴이 4개, 시간이 38초 더 많았다. 사실상 차이 없음.
- Jev r2는 vanilla보다 15%, route-index보다 11% 비쌌다. Jev 비용 $0.0244(130요청, 582,063토큰)와 ranking 시간이 순수 overhead가 됐다.
- **vanilla가 이미 빠른 국소 결함에서는 ranker가 이득을 주지 않는다**는 ceiling 결과다. 이 사례를 Jev의 일반 효과 근거로 쓰지 않는다.

## 다음

1. `experiments/logic-ranker/e2e`를 `vanilla`/`route-index`/`jev` 3-arm과 case config로 일반화한다.
2. generic 질문·K·arms·metric·run count를 pre-register한다.
3. evaluator hardening과 contamination 통제를 구현한다.
4. 작은 3-arm 파일럿을 Vikunja 또는 Pocket ID에서 실행한다.
5. pilot 분산으로 confirmatory case 수와 run 수를 정하고, blind held-out 사례를 고른다.
6. Arcane에서 같은 3-arm을 실행한다. Pocket ID는 필요하면 vanilla/route-index를 반복한다.

## 한계

- 4개 development case는 서로 다른 bug subtype을 하나씩만 가진다. case 수가 늘어나도 within-class replication은 별도로 필요하다.
- Jev 1.14는 코드 triage에서 1.13보다 낫다고 가정하지 않는다.
- route extraction은 Gin/Echo/Huma의 일반 패턴만 다루며 dynamic route·interface call·truncation 누락이 있을 수 있다.
- 3-arm 파일럿도 confirmatory가 아니다. 결과를 본 뒤 질문·K·사례를 바꾸지 않는다.

## 출처

- 독립 리뷰: `~/sift-runs/notes/2026-10-19-design-review-synthesis.md`, `/tmp/swiftscanai-review-2026-10-19/{mythos-brief.md,astra.md}`
- Jev 1.14: https://docs.typesafe.ai/models
- Stage 1·Kite e2e: [ADR 0006](0006-logic-bug-ranker-experiment.md), `experiments/logic-ranker/`
