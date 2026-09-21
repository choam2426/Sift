# Jev 질문 설계 ablation (2026-09-21)

> 스크립트: [scripts/jev_ablation.py](../../scripts/jev_ablation.py) (PROTOTYPE 표시).
> 질문: 판단 선택지를 잘 주면 near-miss(0.48류)가 해결되나?
> 24 케이스 (pos 12 / neg 12, hard 포함) × 3 설계.

## 설계

- **A. noul**: "변경 전 인가 체크를 하나?" 단일 예/아니오 (baseline)
- **B. choice 3-way**: explicit / auth_only / absent → explicit만 1
- **C. decomp**: compares(행위자-대상 비교) / before(변경 전) / blocks(실패 시 차단)
  3개 noul을 AND로 결합

형식 메모: choice는 flat `criteria` 맵
(`{"type":"choice","instructions":..,"criteria":{..}}`).
응답: `{"choice": <key>, "confidence": .., "probabilities": {..}}`.

## 결과

```text
accuracy: noul=23/24 choice=22/24 decomp(AND)=18/24
```

Miss 내역:

```text
test bypass (label=0):      noul 0.50 MISS, choice explicit MISS, decomp OK
decorator auth (label=1):   choice auth_only MISS, decomp MISS (compares=0.10)
admin role (1):             decomp MISS (compares=0.48)
capability call (1):        decomp MISS (compares=0.41)
requires_role decorator:    decomp MISS (compares=0.14)
guard clause 403 (1):       decomp MISS (compares=0.20)
match role guard (1):       decomp MISS (compares=0.48)
```

## 해석

1. **가설 half-confirmed.** Choice는 hard negative near-miss를 해소
   (login-only 0.44 → auth_only 정분류, hard negative 8개 중 7개 정분류).
   그러나 implicit-form positive(decorator 등)를 놓침.
2. **Decomp-AND가 최악.** `compares` 하위질문이 명시적 비교 형태만
   인식해서 role/decorator/capability 형태에서 붕괴. AND가 최약체를
   증폭. 하위질문 wording이 형태를 포괄해야 함.
3. **막연한 질문이 형태 변화에 강함.** noul은 decorator를 0.88로
   맞춤 — 모델 자체의 넓은 "인가" 개념을 씀. 정밀 질문은 정밀하지만
   형태 변화에 brittle. Precision-robustness 트레이드오프.
4. **Disagreement가 불확실 신호.** noul vs choice가 갈린 케이스
   (decorator, test bypass)가 정확히 어려운 케이스.
   설계 간 불일치 자체를 uncertain/escalation 신호로 쓸 수 있음.
5. test bypass는 noul·choice가 다 틀리고(decorator 경로의
   require_admin에 속음) decomp만 맞힘 — 설계마다 잡는 게 다름.

## 다음

- `compares`류 wording을 implicit 형태까지 포괄하도록 수정 후 재측정
  ("decorator/helper/policy 호출 포함").
- Ensemble 실험: noul+choice 합의 시 확정, 불일치 시 escalate.
- Abstain 선택지는 별도 실험으로 (미실시).
