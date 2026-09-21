# Falsify — 컨셉 및 초안 구조

> 상태: 아이디어 논의 스냅샷 (2026-09-21). 확정 아님. 미결정은 별도 표기.
> 가칭: Falsify — "Instead of looking for unsafe code, find unsafe assumptions."

## 1. 컨셉

### 1.1 Thesis

Memory-safe 환경에서도 살아남는 취약점은 **메모리 커럽션이 아니라
logic/security invariant 위반**이다. 개발자가 당연하다고 믿은 암묵적 전제를
깨는 입력/호출 순서를 자동으로 찾아낸다.

연구식 표현: Automated security invariant discovery and falsification
for memory-safe backend applications.

### 1.2 핵심 분업: Jev + LLM

단일 frontier LLM에 코드를 통째로 주는 대신, 인간 분석가의 작업 흐름을
자동화한다:

```text
분석가 recon (공격 표면 파악)      → static extractor
분석가 triage (스치듯 보고 선별)    → Jev (수백 ms짜리 glance)
분석가 deep dive (전제 추출)        → LLM invariant 생성
분석가 PoC (깨지는 입력 구성)       → falsification (반례 실행)
```

- **Jev = recall 담당**: 싸고 빠르게 넓게 본다. 놓치지 않는 게 목표.
- **LLM = precision 담당**: 좁혀진 후보만 깊게 본다. Invariant 명시 강제.
- 설계 원리는 인간 모방이 아니라 **"싼 판단 → 비싼 추론" 분업**.
  인간의 주의력 제약을 기계가 따라할 필요는 없다 (B안 참조).

### 1.3 Jev란 (2026-09-15 출시)

- TypeSafe AI (ex-OpenAI Diogo Almeida)의 "System One" 모델. 텍스트를
  생성하지 않고 typed decision + calibrated probability만 반환.
- 입력: state + 미리 선언한 typed 질문. 출력: 선택지/점수/yes-no 확률.
- 스펙(벤더 발표): 70~500ms, 입력 $0.042/MTok, 출력 무료.
- API: `POST https://api.typesafe.ai/v1/systemone`
- 출시 6일차라 독립 검증 거의 없음. Calibration 주장은 RQ에서 검증 대상.

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
4 위반 탐색: 로직은 갭 ← LLM + falsifier 자리
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
[Composer] logic unit 합성
  입력: CodeDB + 1차 scores + state inventory
  출력: ranked logic units (capped, deduped, flow-ordered)
         │
         ▼
[2 Jev logic] 흐름 위반 — 후보만
  판단 대상: logic unit (의미 단위, 아래 정의)
  질문형: 검증형 ("이 슬라이스에서 auth가 강제되는가?")
  출력: 수상 logic
         │
         ▼
[3 Jev cross-logic] 일관성 — 쌍/그룹
  판단 대상: logic unit 쌍/그룹
  질문형: 비교형 ("A는 체크하는데 B는 왜 안 하나?")
  출력: 불일치 후보
         │
         ▼
[4 LLM] deep dive
  입력: 2, 3의 출력 slice
  출력: Invariant IR + violation scenario (구조화 강제)
         │
         ▼
[5 Falsify] 2단
  5a cheap: 기존 테스트와 invariant 충돌 체크 → 충돌 시 invariant 폐기
  5b expensive: 반례를 테스트/harness로 실행 → 깨지면 finding 확정
  출력: verdict {confirmed / refuted / inconclusive} + 증거
         │
         ▼ (confirmed만)
[Side loop] finding 증폭기 (B')
  finding → 패턴 일반화 (LLM 1회) → Jev 전수 sibling sweep
  → 추가 후보 → [4]로. Cold-start 가설후검증은 폐기.
```

### 3.2 설계 원리

1. **Funnel**: 뒤로 갈수록 집합은 좁아지고 판단은 비싸진다.
2. **Semantic ladder**: 단계마다 판단 대상이 달라진다
   (function → logic → cross-logic). 각 단계가 타깃 버그 클래스에 대응.
3. **Artifact contract**: 단계 사이 산출물 고정 —
   CodeDB → scored list → logic units → Invariant IR → verdict.
4. **측정 후크 내장**: 필터마다 audit sampling 슬롯. 재는 장치 없이
   파이프라인을 만들지 않는다.

### 3.3 타깃 취약점 (초기 범위)

authorization bypass, cross-tenant isolation failure,
state-machine/workflow bypass, replay/idempotency bug,
cross-endpoint validation inconsistency, quota/accounting/conservation
violation.

## 4. 컴포넌트별 방향

### 4.1 Review unit: 함수 중심 + 얇은 껍질

```text
review unit = named callable 본문 + 껍질 {decorator, 시그니처, 호출 이름 목록}
```

"함수 소스만"은 recall 구멍 (auth가 decorator에 있는 경우 등).
껍질은 토큰 2배 미만으로 신호 대부분 회수.

### 4.2 Jev ladder (function → logic → cross-logic)

- 1차 범위는 함수 전수와 entry 도달만 중 미결정 (§8.3 참조).
- 단계가 깊어질수록 질문형이 탐지형 → 검증형 → 비교형으로 바뀐다.
- N차로 열어두되 실제 설계는 3단에서 멈춤. 그 위는 아키텍처 리뷰 영역.

### 4.3 Composer: flow extraction + bundling (핵심)

Logic unit 정의: 하나의 보안 관련 동작을 함께 구현하는 함수 집합.
Invariant가 붙을 만한 덩어리.

핵심 통찰: 원하는 건 flow(세로: entry → … → sink)이지
module(가로: 패키지)이 아니다. Community detection(Louvain류),
embedding 클러스터링은 틀린 도구.

```text
Phase 1 — path extraction: entry → sensitive sink beam search, risky top-K
Phase 2 — bundling: prefix/suffix 공유 경로 병합 → flow bundle = logic unit
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

"In invariant 명시 없이 취약하다는 주장 금지"가 원칙. 출력:

```text
1. Invariant 생성 (이 코드가 지켜야 할 규칙)
2. 위반 추론 (깰 수 있는 입력/순서 존재 여부)
3. 반례 구체화 (재현 가능한 형태)
```

Bug-first(반례 먼저, invariant는 사후 설명)는 대안으로 존재.
RQ급 비교 대상이나 MVP는 invariant-first.

### 4.5 Falsify

5a(기존 테스트 충돌 체크)가 방파제. 5b(반례 실행 harness)가 최고 난이도.
Harness 방식 (handler 직접 호출 vs 서버+HTTP)은 미결정.

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
- Baseline: frontier LLM 통째로(single-LLM) vs 제안 파이프라인.
  비교축: recall, 비용, 속도.
- 선행 측정: Jev vague-vs-specific 질문 정확도 갭 (B' 존폐 결정).

## 8. 미결정 사항

1. **Invariant IR 형태**: 자연어 vs 구조화 enum/DSL. [4]-[5]의 목.
2. **정답지**: 과거 CVE vs 인공 주입 vs 사람 라벨. RQ의 나침반.
3. **1차 범위**: 함수 전수 vs entry 도달만. 비용/범용성 트레이드오프.
4. **Harness 방식**: 직접 호출 vs 서버+HTTP.
5. **Cutoff/임계값/전파 가중치 등 파라미터 일체**: 방향 확정 후.
6. **State inventory 확정**: 휴리스틱+LLM 조합 검증 필요.
7. **첫 타깃 프로젝트 + 언어**: Rust부터인지, decisions 1-4 이후.

## 9. RQ 스케치 (초안)

```text
RQ1. Jev가 security-invariant-bearing 코드를 잘 ranking하는가?
     (1차 recall@k + audit 기반 miss rate)
RQ2. LLM이 코드만 보고 application-specific invariant를 정확히 생성하는가?
     (valid invariant rate — 전체 파이프라인의 병목)
RQ3. 생성된 invariant를 falsification으로 반례까지 찾을 수 있는가?
RQ4. Jev routing으로 frontier 호출량을 줄여도 recall을 유지하는가?
     (single-LLM baseline 대비 비용/속도/recall)
```

RQ2가 병목이므로 RQ2부터 깨야 RQ3/RQ4가 의미 있음.

## 10. 약한 이음새 (우선 타격 순서)

1. [4]→[5]: harness 생성이 최고 난이도. 막히면 finding이 "LLM 주장" 수준.
2. [1] cutoff: 전체 recall 상한. Generous vs 비용 곡선이 RQ1 본체.
3. Invariant IR: 자연어면 자동화 불가, 구조화면 표현력 부족.
4. Composer 품질: 묶음이 틀리면 2차 판단 무의미.

## 11. 다음 단계 후보

- Invariant IR 설계 ([4]와 [5] 양쪽의 목)
- Falsify 심화 (5a 상세 + 5b 최소형)
- 정답지/벤치마크 설계
- Composer 내재 지표 정교화
