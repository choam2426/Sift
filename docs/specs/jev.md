# Jev 실측 스펙 (2026-09-21)

> 스크립트: [scripts/jev_probe.py](../../scripts/jev_probe.py). 모델: `jev-latest` → `jev-1.13.0`.
> 질문 1개(noul) 기준. n이 작으므로 파일럿 수치로만 볼 것.

## Latency (n=10, 동일 호출, 315 입력 토큰)

```text
min=447ms med=503ms p95=573ms max=573ms
```

벤더 주장(70~500ms)의 상한 언저리. 네트워크 포함 실측이라 양호.
전수 스캔 산수: 함수 10만 개 × 0.5s 순차 = 약 14시간.
병렬화 필수 (동시 호출 한도는 미측정).

## Calibration 맛보기 (8 케이스, thresh=0.5)

```text
accuracy = 8/8
positive (4): 0.90 ~ 0.98  — 명시 체크, decorator, tenant 매칭, early guard 전부 통과
negative (3): 0.02 ~ 0.04  — 무체크, TODO, 사후 체크 전부 통과
hard negative (1): 0.48    — 로그인 체크는 있으나 타객체 변경 (label=0, 턱걸이)
```

쉬운 케이스는 양극단으로 갈린다. Hard negative가 0.5 언저리에 걸림 —
uncertain 밴드(0.3~0.7) 설계의 실증적 근거 1호.
본격 calibration 곡선은 라벨 수백 개 규모에서 (§8 RQ1).

## 입력 길이 (signal을 끝에 매장, 질문 1개)

```text
chars=2,070   → 200, 536ms,  score=0.03
chars=10,074  → 200, 508ms,  score=0.03
chars=40,066  → 200, 829ms,  score=0.03
chars=100,050 → 200, 1068ms, score=0.03
```

100K chars(약 25K 토큰)까지 에러 없이 점수 안정.
Unit 통째 입력 가능. 상한(에러점)은 미탐색.

## 비용 감각

315 입력 토큰 호출 = $0.000013. 10만 함수 d0 스캔 ≈ $1.30.
Jev 비용은 무시 가능 구간. 돈이 아니라 latency × 병렬도가 병목.

## 미측정 (다음)

- 동시 호출 한도/rate limit
- 질문 수 증가 시(7개 전체) latency/정확도 변화
- 에러점 탐색 (100K chars 초과)
- 본 calibration (수백 라벨, thresh별 P/R 곡선)
