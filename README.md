# Falsify

> Instead of looking for unsafe code, find unsafe assumptions.

Memory-safe 백엔드의 logic/security invariant 위반을 자동 탐지한다.
싼 triage(Jev) → 깊은 분석(frontier LLM) → falsification(반례 실행) 구조.

## 빠른 시작

```bash
cp .env.example .env   # 키 두 개 기입: TYPESAFE_API_KEY, MODEL_API_KEY
./scripts/smoke.sh     # 키 검사 + 최소 호출 테스트
python3 scripts/jev_probe.py  # Jev 실측 (latency/calibration/입력한계)
```

상세: [제품](docs/product.md) · [아키텍처](docs/architecture.md) · [평가](docs/eval.md) · [결정 로그](docs/decisions.md)

## 구조

```text
docs/
  product.md    제품 정의 + 로드맵
  architecture.md  파이프라인 설계 상세
  eval.md       평가 전략 (baseline/지표/정답지)
  decisions.md  결정 로그
  research/     문헌/배경 조사 (날짜별)
  specs/        실측 스펙 (Jev, frontier, ...)
scripts/
  smoke.sh      키 검사 + 스모크 테스트
  jev_probe.py  Jev 실측 프로브 (stdlib only)
```

## 현 상태 (2026-09-21)

- Jev + frontier 연결 확인, Jev 파일럿 실측 완료 ([specs/jev.md](docs/specs/jev.md))
- 질문 설계 ablation 완료 ([specs/jev-questions.md](docs/specs/jev-questions.md))
- 다음: P0 triage 파일럿 (추출 파이프부터)
