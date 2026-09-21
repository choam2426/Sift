# 결정 로그

> 뒤집을 수 있지만, 뒤집을 때는 여기서 이유를 갱신한다. 최신이 아래.

## D1 (2026-09-21): Jev는 필수, 제거 불가

- 파이프라인의 주인공. RQ1(Jev ranking 품질) = 프로젝트의 생사.
- 작업 순서 함의: Jev 검증이 0순위, fail fast.
- 배경: 문헌은 static+LLM만 보증하므로 Jev는 검증된 선택이 아니라
  프로젝트의 베팅임. 수용하고 정면 돌파.

## D2 (2026-09-21): Frontier = muse-spark-1.3-contributor

- Meta Model API, OpenAI 호환 (`https://api.meta.ai/v1`).
- $0.10/$0.20 per MTok, 1M 컨텍스트.
- Contributor 티어는 프롬프트로 학습함. 실험 단계 수용,
  prospective analysis + disclosure 전에 재검토.

## D3 (2026-09-21): Secret은 .env, knob은 config

- `.env`는 git 금지, `.env.example`은 템플릿으로 커밋.
- 비-시크릿 설정(모델명, endpoint)은 나중에 `config/`로 분리.
- CLI 로그인 키(auth.json)를 파이프라인용으로 재사용하지 않음.

## D4 (2026-09-21): Baseline 2단화

- 약한 baseline: single-LLM 통째로 (교육용, 이기는 게 당연).
- 강한 baseline: static-slice + LLM (IRIS/LLMxCPG류, 진짜 승부).

## D5 (2026-09-21): Triage는 static 뼈대 + Jev 신호

- Composer의 reachability/slicing이 구조, Jev가 risk gate/weight.
- Jev가 기대 이하라도 구조가 서 있도록. 단, Jev 제거는 D1 위반.

## D6 (2026-09-21): 가벼운 구성 유지

- 스크립트는 stdlib-only (bash+curl, python3 표준lib).
- 프레임워크/의존성은 필요해질 때까지 도입 금지.

## D7 (2026-09-21): 범위 확대 — 메모리 버그 포함

- 기존 thesis("메모리 커럽션이 아닌")를 확장. C++ 메모리 트랙 추가.
- 이유: 범용 취약점 탐지 제품으로 가기 위해 유형 커버리지 필요.

## D8 (2026-09-21): Generic-by-type

- 파이프라인 공통, 지식(질문셋/정답지)은 유형별 프로필.
- 새 유형 = 프로필 추가, 파이프라인 수정 없음.

## D9 (2026-09-21): 파일럿 4트랙

- Discourse / 7-Zip / Kanidm / K8s-RBAC(범위 절단). 4×50라벨.
- 컨트랙트 phase 2, Swift 제외.

## D10 (2026-09-21): Baseline 정의

- Triage: B0 random / B1 rule / B2 LLM-judge(샘플) / B3 Semgrep.
- E2E: E0 SAST / E1 single-LLM / E2 static+LLM(Jev 제외).
- 상세: [eval.md](eval.md).
