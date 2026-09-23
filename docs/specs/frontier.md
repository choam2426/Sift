# Frontier 실측 메모 (2026-09-21)

> 모델: muse-spark-1.3-contributor (Meta Model API, OpenAI 호환).

- Always-on reasoning: 1숫자 답에도 4k+ 예산 필요 (512/2048 잘림 확인).
  50판단 ≈22.5k in / 86k out ≈ $0.02.
- 판단당 비용 ≈$0.0004 (Jev ≈$0.000016의 약 25배).
- Judge 용도는 temp 0 + 숫자 정규식 파싱으로 충분 (50/50).
