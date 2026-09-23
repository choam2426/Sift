# P0 Eval 01 — Mastodon triage head-to-head (2026-09-21)

> 명령: `make eval` (scripts/eval.py). 라벨 50개 중 positive 21개.
> 전수 arm은 층화가중 recall@k 추정치, llm-judge는 샘플 한정.

## 결과

```text
arm               R@5   R@10   R@20    P@5   P@10   P@20   sAUC
jev-noul-auth    0.30   0.43   0.70   1.00   0.73   0.60   0.95
jev-choice       0.30   0.50   0.93   1.00   0.85   0.79   0.97
jev-noul-broad   0.27   0.43   1.00   0.93   0.73   0.85   0.99
rule             0.32   0.48   0.55   1.00   0.81   0.46   0.87
semgrep          0.05   0.23   0.39   0.15   0.39   0.33   0.48
llm-judge                                           acc .94   0.98
B0 random: R@k=k, prevalence ≈ 0.169
band hit (noul-auth): top5%: 13/13, 5-20%: 6/13, 20-50%: 2/12, rest: 0/12
```

## 판정 (eval.md P0 기준)

- 필수 (B0/B1 상회): **PASS**. R@20에서 Jev 전 arm(0.70~1.00)이
  rule(0.55)을 압도. 단 R@5는 rule이 미세 우위 — 룰은 뻔한 head를,
  Jev는 나머지를 잡는다.
- 목표 (B3 동급 이상): **PASS++**. semgrep AUC 0.48 ≈ 랜덤.
  OSS 룰셋에는 auth-logic 신호가 거의 없다.
- stretch (B2 동급): **PASS**. broad AUC 0.99 vs judge 0.98.
  판단당 비용은 Jev ≈$0.000016 vs judge ≈$0.0004 (약 25배).

## 해석

- 밴드 적중률 13/13 → 6/13 → 2/12 → 0/12: 단조 calibration 곡선.
  Top band는 전수 positive, bottom은 전수 negative.
- Broad arm이 label 정의(보안 결정 전반)와 제일 맞아떨어짐.
  Auth 특화 arm도 0.95+로 유효.
- Semgrep의 참패는 "기존 도구보다" 주장의 직접 근거.

## 한계

- n=50 (신뢰구간 넓음), 1트랙. 3트랙 확장으로 검증 필요.
- recall@k는 층화가중 추정치 (HT 분산 — P는 1.0 cap).
  sAUC는 샘플 내 discordance로 가중 없음.
- 층화 arm = noul-auth (타 arm top-k 추정치 분산 ↑).
