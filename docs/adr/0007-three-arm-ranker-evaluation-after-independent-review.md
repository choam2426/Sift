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
   - `bundles`: 같은 route bundle과 가이드, **Jev 없이 고정 순서**(사전 등록한 random/alphabetical order).
   - `jev`: 같은 route bundle과 가이드, Jev ranker CLI와 고정 질문·top-K.
   - `vanilla` vs `bundles`는 bundle/extraction의 효과, `bundles` vs `jev`는 ranking의 증분 효과를 뜻한다.
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
8. **추출 비용을 기록한다.** route extraction/bundle 생성은 사례 준비 비용으로 별도 기록하고, `bundles`·`jev`에 같은 bundle을 제공한다. 한쪽에만 무료로 주지 않는다.
9. **표본 계획을 단계화한다.** 먼저 3-arm × 2 cases × 2 runs 파일럿으로 분산을 잰다. confirmatory는 5~10 runs/arm/case, 8~12 blind cases를 목표로 하되, pilot 분산으로 power를 계산해 실행 전에 고정한다.
10. **판정 규칙을 미리 정한다.** Jev ranking은 `jev`가 `bundles`를 주 지표에서 이기고, 사례별 paired 분석의 신뢰구간이 0을 제외할 때만 효과가 있다고 주장한다. `bundles`가 `vanilla`를 이기면 extractor/bundle이 제품의 핵심이라는 결론을 허용한다.

## 현재 결과의 지위

- Stage 1 route rank(Kite 1/130, Pocket ID 2/110, Vikunja 28/355, Arcane 18/147)는 **oracle-informed ceiling**이다. 성능 주장에 쓰지 않는다.
- Kite e2e(순정 $1.436 vs Jev $1.373)는 **development pilot**이다. Jev ranking의 효과로 해석하지 않는다.
- 두 결과 모두 3-arm confirmatory의 가설 생성 자료로만 쓴다.

## 다음

1. `experiments/logic-ranker/e2e`를 `vanilla`/`bundles`/`jev` 3-arm과 case config로 일반화한다.
2. generic 질문·K·arms·metric·run count를 pre-register한다.
3. evaluator hardening과 contamination 통제를 구현한다.
4. 작은 3-arm 파일럿을 Vikunja 또는 Pocket ID에서 실행한다.
5. pilot 분산으로 confirmatory case 수와 run 수를 정하고, blind held-out 사례를 고른다.

## 한계

- 4개 development case는 서로 다른 bug subtype을 하나씩만 가진다. case 수가 늘어나도 within-class replication은 별도로 필요하다.
- Jev 1.14는 코드 triage에서 1.13보다 낫다고 가정하지 않는다.
- route extraction은 Gin/Echo/Huma의 일반 패턴만 다루며 dynamic route·interface call·truncation 누락이 있을 수 있다.
- 3-arm 파일럿도 confirmatory가 아니다. 결과를 본 뒤 질문·K·사례를 바꾸지 않는다.

## 출처

- 독립 리뷰: `~/sift-runs/notes/2026-10-19-design-review-synthesis.md`, `/tmp/swiftscanai-review-2026-10-19/{mythos-brief.md,astra.md}`
- Jev 1.14: https://docs.typesafe.ai/models
- Stage 1·Kite e2e: [ADR 0006](0006-logic-bug-ranker-experiment.md), `experiments/logic-ranker/`
