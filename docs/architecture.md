# Falsify — 아키텍처

> 파이프라인 설계 상세 (초안 2026-09-21 + 이후 결정 반영).
> 배경/동기/thesis → [제품](product.md).
> 관련: [평가](eval.md) · [결정 로그](decisions.md) · [문헌 조사](research/2026-09-21-pipeline-lit-review.md) · [Jev 실측](specs/jev.md)

## 1. 전제 (요약)

- Jev = recall 담당 triage (싼 판단), LLM = precision 담당 deep dive (비싼 추론).
  분업 근거는 [제품](product.md).
- Jev = TypeSafe System One 모델. `POST .../v1/systemone`에 state + typed
  질문 → 선택지/점수/확률 반환. 측정치: [Jev 실측](specs/jev.md).

## 2. 일반화된 분석 흐름 (인간 기준)

리버싱과 소스 정적분석은 입력만 다르고 인지 구조는 동일하다.

```text
1 Recon     — "뭐가 공격 가능한가" (attack surface 열거)
2 Triage    — "어디를 볼까" (냄새 기반 선별, recall 중시)
3 Deep dive — "이 코드가 뭘 믿고 있나" (암묵적 invariant 추출)
4 Violation — "전제를 깰 수 있나" (위반 시나리오 구성)
5 확증      — "진짜 깨지나" (PoC 실행)
```

두 흐름이 같은 방향이다: 정보는 넓고 얇게 → 좁고 깊게(funnel),
비용은 싼 판단 → 비싼 판단. 자동화 구조도 이 방향을 따른다.

### 자동화 지도 (갭 = 프로젝트 위치)

```text
1 Recon:    잘 됨 (정적 추출) — 기존 도구/가벼운 추출기
2 Triage:   룰 기반까지만, 의미 기반은 갭 ← Jev 자리
3 전제 추출: 갭 ← LLM 자리
4 위반 탐색: 갭 ← LLM + falsifier 자리
5 확증:     반자동 (PoC 구성 지원) ← harness 자리
```

## 3. 초안 구조

### 3.1 파이프라인

```text
[0 Recon] static extractor
  입력: 코드베이스
  출력: CodeDB {함수 + 껍질 metadata, entry points, call graph, sensitive sinks}
         │
         ▼
[1 Jev function] smell — 전수
  판단 대상: 함수 + 껍질 (decorator, 시그니처, 호출 목록)
  질문형: 탐지형 ("외부 입력이 닿나? 상태 쓰기가 있나?")
  출력: scored list {함수, risk vector} → generous cutoff로 후보
         │  audit sampling → recall 추정치 (필수)
         ▼
[Composer] unit 합성
  입력: CodeDB + 1차 scores + state inventory
  출력: ranked units (capped, deduped, flow-ordered)
         │
         ▼
[2 Jev unit] 흐름 위반 — 후보만
  판단 대상: unit (의미 단위, 아래 정의)
  질문형: 검증형 ("이 흐름의 전제가 지켜지는가?")
  출력: 수상 unit
         │
         ▼
[3 Jev cross-unit] 일관성 — 쌍/그룹
  판단 대상: unit 쌍/그룹
  질문형: 비교형 ("A는 체크하는데 B는 왜 안 하나?")
  출력: 불일치 후보
         │
         ▼
[4 LLM] deep dive
  입력: 2, 3의 출력 slice
  출력: Invariant IR + violation scenario (구조화 강제)
         │
         ▼
[5 Falsify] agentic loop
  step 0: 기존 테스트로 반박 시도 (거저면 여기서 끝)
  step 1+: PoC 생성 → 실행 → 관찰 → 반복 → verdict 확정
  출력: verdict {confirmed / refuted / inconclusive} + 증거 (PoC 포함)
  ※ confirmed = 기계 확증 (PoC로 위반 재현). 최종 취약점 판정은 연구원.
         │
         ▼ (confirmed만)
[Side loop] finding 증폭기 (B')
  finding → 패턴 일반화 (LLM 1회) → Jev 전수 sibling sweep
  → 추가 후보 → [4]로. Cold-start 가설후검증은 폐기.
```

### 3.2 설계 원리

1. **Funnel**: 뒤로 갈수록 집합은 좁아지고 판단은 비싸진다.
2. **Semantic ladder**: 단계마다 판단 대상이 달라진다
   (function → unit → cross-unit).
3. **Artifact contract**: 단계 사이 산출물 고정 —
   CodeDB → scored list → units → Invariant IR → verdict.
4. **측정 후크 내장**: 필터마다 audit sampling 슬롯. 재는 장치 없이
   파이프라인을 만들지 않는다.

### 3.3 타깃 범위

정적분석/리버싱으로 찾을 수 있는 모든 버그 종류 (D16).
버그 클래스별 분기 없음 — 파이프라인 공통, 유형별 차이는
프로필(질문셋 + 정답지 정의)로만 흡수 ([제품](product.md) Generic-by-type).

## 4. 컴포넌트별 방향

### 4.1 Review unit: 함수 중심 + 얇은 껍질

```text
review unit = named callable 본문 + 껍질 {decorator, 시그니처, 호출 이름 목록}
```

"함수 소스만"은 recall 구멍 (전제 관련 코드가 decorator에 있는 경우 등).
껍질은 토큰 2배 미만으로 신호 대부분 회수.

### 4.2 Jev ladder (function → unit → cross-unit)

- 1차 범위는 함수 전수와 entry 도달만 중 미결정 (§8.3 참조).
- 단계가 깊어질수록 질문형이 탐지형 → 검증형 → 비교형으로 바뀐다.
- N차로 열어두되 실제 설계는 3단에서 멈춤. 그 위는 아키텍처 리뷰 영역.

### 4.3 Composer: flow extraction + bundling (핵심)

Unit 정의: 하나의 보안 관련 동작을 함께 구현하는 함수 집합.
Invariant가 붙을 만한 덩어리.

핵심 통찰: 원하는 건 flow(세로: entry → … → sink)이지
module(가로: 패키지)이 아니다. Community detection(Louvain류),
embedding 클러스터링은 틀린 도구.

```text
Phase 1 — path extraction: entry → sensitive sink beam search, risky top-K
Phase 2 — bundling: prefix/suffix 공유 경로 병합 → flow bundle = unit
보조: (entry × state) cell 분할 + risk gate + size cap
```

- Edge 가중치: 공유 상태(강) > 데이터 흐름(중) > 양단 risk(약),
  high-indegree hub는 감점 (exclusivity).
- Transit vs membership: 유틸은 경로 통과는 허용, unit 멤버에서는 제외
  (또는 시그니처만). Hub 오염 방지.
- 표현: flow 순서(entry → sink)로 정렬. 본문 상위 K개 + 나머지 시그니처.
- 대안: seeded diffusion (PPR/heat) — 단순하나 blob 위험. Ablation 대상.
- Composer는 결정적 룰로 충분. 학습시키는 건 오버엔지니어링.

State inventory (최대 하위 난제): 휴리스틱(d)으로 후보를 싸게 뽑고
LLM 지명(b)으로 확정하는 조합이 유력. LLM은 프로젝트당 몇 회라 무시 가능.

### 4.4 LLM: invariant-first

"Invariant 명시 없이 취약하다는 주장 금지"가 원칙. 출력:

```text
1. Invariant 생성 (이 코드가 지켜야 할 규칙)
2. 위반 추론 (깰 수 있는 입력/순서 존재 여부)
3. 반례 구체화 (재현 가능한 형태)
```

Bug-first(반례 먼저, invariant는 사후 설명)는 대안으로 존재.
RQ급 비교 대상이나 MVP는 invariant-first.

### 4.5 Falsify

LLM agentic loop. 첫 행동은 기존 테스트로 반박 시도(step 0) —
거저로 깨지면 PoC를 짜지 않는다. 이후 PoC 생성 → 실행 → 관찰 →
(실패 시 수정 반복) → verdict.
Harness 방식 (직접 호출 vs 서버+HTTP)은 사전 고정 안 함, 케이스별 LLM 판단.
연구원은 confirmed은 PoC와 함께, inconclusive는 lead로 받는다.
완전 자동화가 목표가 아니다 — 최종적으로 취약점이 맞는지의 판정은
연구원의 몫이며, 파이프라인은 판정 가능한 증거까지 책임진다.

## 5. 실험 변형 (코어 제외, kill 조건부)

```text
A graph propagation: [1]-[2] 사이 risk 전파 레이어. C와 병렬 가능.
C peer anomaly: [1]과 병렬 신호. "왜 이것만 다르지" (역할-상대 판단).
B' finding 증폭기: side loop (3.1 참조). 선행 체크가 vague-vs-specific
   질문 정확도 갭 측정 — 갭 없으면 실험 없이 폐기. 본실험은
   bottom-up+embedding vs bottom-up+amplifier 비교.
D closed loop: [5] verdict → [1] 재보정. Phase 2.
```

공통 판정: 2-stage baseline 대비 비용 대비 finding으로 재고 지면 폐기.

## 6. 폐기 / 보류 기록

- **Adaptive recursion** (확률 보고 depth를 하나씩 늘리는 재귀): 비용 최적화용.
  Jev가 워낙 싸서($2 수준) 복잡도 대비 이득 의문. 보류 — "나중에 최적화" 목록.
- **Cold-start B** (관측 없이 LLM 가설부터): 주객전도 (비용 역전 + 인식 역전).
  폐기. Finding-triggered side loop(B')로만 부활.
- **항상 d1 고정안**: Cascade 없이 고정 depth 1회 호출. 단순성 대안으로 기록.
  Semantic ladder 채택으로 ladder 구조 안에 흡수됨.

## 7. 방법론 (필수)

- **Audit sampling**: Jev가 버린 low 밴드에서 랜덤 샘플링해 LLM/사람 검증.
  없으면 recall 정의상 측정 불가. MVP 포함 필수.
- Baseline: [평가](eval.md)의 2단 비교군 (triage B0~B3, e2e E0~E2).
  비교축: recall, 비용, 속도.
- 선행 측정: Jev vague-vs-specific 질문 정확도 갭 (B' 존폐 결정).

## 8. 미결정 사항

1. **Invariant IR 형태**: 자연어 vs 구조화 enum/DSL. [4]-[5]의 목.
2. **정답지**: 결정됨 — triage=사람 라벨, e2e=기지 CVE 1차+주입 2차. ([평가](eval.md))
3. **1차 범위**: 함수 전수 vs entry 도달만. 비용/범용성 트레이드오프.
4. **Harness 방식**: 사전 고정 안 함. 케이스별 LLM 판단 (§4.5).
5. **Cutoff/임계값/전파 가중치 등 파라미터 일체**: 방향 확정 후.
6. **State inventory 확정**: 휴리스틱+LLM 조합 검증 필요.
7. **첫 타깃 프로젝트 + 언어**: 결정됨 — D9 4트랙 (Discourse/7-Zip/Kanidm/K8s-RBAC).

## 9. RQ 스케치 (초안)

```text
RQ1. Jev가 security-invariant-bearing 코드를 잘 ranking하는가?
     (1차 recall@k + audit 기반 miss rate) → track-1 Yes ([jev-eval-01](specs/jev-eval-01.md)).
RQ2. LLM이 코드만 보고 application-specific invariant를 정확히 생성하는가?
     (valid invariant rate — 전체 파이프라인의 병목)
RQ3. 생성된 invariant를 falsification으로 반례까지 찾을 수 있는가?
RQ4. Jev routing으로 frontier 호출량을 줄여도 recall을 유지하는가?
     (single-LLM baseline 대비 비용/속도/recall)
```

RQ2가 병목이므로 RQ2부터 깨야 RQ3/RQ4가 의미 있음.
Baseline/지표 상세는 [평가](eval.md).

## 10. 약한 이음새 (우선 타격 순서)

1. [5]: agentic PoC loop가 최고 난이도. 막히면 finding이 "LLM 주장" 수준.
2. [1] cutoff: 전체 recall 상한. Generous vs 비용 곡선이 RQ1 본체.
3. Invariant IR: 자연어면 자동화 불가, 구조화면 표현력 부족.
4. Composer 품질: 묶음이 틀리면 2차 판단 무의미.

## 11. 다음 단계

[제품 로드맵](product.md)과 [티켓](../../tickets/README.md)으로 이관됨.
(구 후보 목록 삭제.)
