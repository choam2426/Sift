# 평가 전략

> Triage 파일럿(P0)과 end-to-end(P1~)의 비교군/지표/정답지 정의.
> 상태: 정의 확정 (2026-09-21). 실행은 P0부터.

## P0 — Triage 파일럿 (ranking 레벨)

동일 라벨셋(4트랙 × 50) 위 헤드투헤드.

```text
B0 random        마루. 공짜.
B1 rule ranker   자작 휴리스틱 (위험 키워드/API + 복잡도). "Jev vs 룰".
B2 LLM-judge     라벨 샘플에만 frontier 직접 점수. 목표는 동급+1/100 비용.
B3 Semgrep       보안 룰셋 → 함수당 finding 밀도 ranking. "기존 도구" 상대.
Jev  noul + choice 두 arm.
```

지표: recall@k, precision@k (k=5/10/20%), 밴드별 적중률.
B0/B1/B3/Jev는 전수 scoring 후 샘플 평가, B2만 샘플 한정.

성공 기준:

```text
필수: B0, B1 유의미 상회 (특히 recall@10~20%)
목표: B3 동급 이상
stretch: B2 동급 (비용 1/100로)
```

## P1~ — End-to-end (finding 레벨)

```text
E0 SAST 기성품   Semgrep/CodeQL 유형별 룰셋. incumbent.
E1 single-LLM    triage/falsify 없이 청크 전수. "그냥 LLM" 상대.
E2 static+LLM    우리 파이프라인에서 Jev만 제외. RQ4 직접 답.
Ours             풀파이프라인.
```

Agentic(Naptime류)은 phase 2 baseline 후보로 보류.

지표: confirmed findings, review burden(사람이 볼 후보 수),
precision, 기지 CVE 재발견율, cost per confirmed finding.

정답지: 트랙별 기지 CVE (+fix commit) 1차, 주입 버그 2차.
Triage 라벨과 별개 산출물.

성공 기준:

```text
E0 대비: confirmed 동급 이상 + review burden 동급 이하
E1 대비: confirmed 동급 이상 + cost 1/10 이하
E2 대비: recall 유지 + frontier 호출량 대폭 감소 (RQ4)
```

## 실행 순서

P0 → P1(1트랙) → P2(멀티트랙). 지금은 정의만, 실행은 P0부터.
