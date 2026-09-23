# Falsify

> Instead of looking for unsafe code, find unsafe assumptions.

Memory-safe 백엔드의 logic/security invariant 위반을 자동 탐지한다.
싼 triage(Jev) → 깊은 분석(frontier LLM) → falsification(반례 실행) 구조.

## 빠른 시작

```bash
mise install           # python + uv — mise 본체는 curl https://mise.run | sh
make venv              # uv sync → .venv
cp .env.example .env   # 키 두 개 기입: TYPESAFE_API_KEY, MODEL_API_KEY
make smoke             # 키 검사 + 최소 호출 테스트
```

상세: [제품](docs/product.md) · [아키텍처](docs/architecture.md) · [평가](docs/eval.md) · [결정 로그](docs/decisions.md)

## 구조

```text
docs/           product/architecture/eval/decisions/research/specs
tickets/        P0 001-008 (all done)
eval/           labels/ (ground truth) + baselines/ (frozen)
scripts/        smoke/probe/ablation + P0 pipeline
mise.toml + pyproject.toml/uv.lock / Makefile
```

## 현 상태 (2026-09-21)

- Jev + frontier 연결 확인, Jev 파일럿 실측 완료 ([specs/jev.md](docs/specs/jev.md))
- 질문 설계 ablation 완료 ([specs/jev-questions.md](docs/specs/jev-questions.md))
- P0 1트랙 (Mastodon) 완주: 추출→스코어링→라벨→4 baseline→eval ([jev-eval-01](docs/specs/jev-eval-01.md))
- 다음: 나머지 3트랙 확장 (D12 게이트 통과)
