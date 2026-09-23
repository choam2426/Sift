# 결정 로그

> 뒤집을 수 있지만, 뒤집을 때는 여기서 이유를 갱신한다. 최신이 아래.
> 번호는 재배열하지 않는다. 병합/폐기된 항목은 본문에 명시.

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

## D5 (2026-09-21): Triage는 static 뼈대 + Jev 신호

- Composer의 reachability/slicing이 구조, Jev가 risk gate/weight.
- Jev가 기대 이하라도 구조가 서 있도록. 단, Jev 제거는 D1 위반.

## D6 (2026-09-21): 가벼운 구성 유지

- 스크립트는 stdlib-only (bash+curl, python3 표준lib).
- 프레임워크/의존성은 필요해질 때까지 도입 금지.
- 후일담: 파서 런타임(tree-sitter)은 "필요"로 인정. 툴체인은
  mise(python+uv) + uv.lock. Semgrep 바이너리는 미관리 (PATH 가정).

## D7 (2026-09-21): 범위 확대 — 메모리 버그 포함

- 기존 thesis("메모리 커럽션이 아닌")를 확장. C++ 메모리 트랙 추가.
- 이유: 범용 취약점 탐지 제품으로 가기 위해 유형 커버리지 필요.

## D8 (2026-09-21): Generic-by-type

- 파이프라인 공통, 지식(질문셋/정답지)은 유형별 프로필.
- 새 유형 = 프로필 추가, 파이프라인 수정 없음.

## D9 (2026-09-21): 파일럿 4트랙

- Mastodon / 7-Zip / Kanidm / K8s-RBAC(범위 절단). 4×50라벨.
- 컨트랙트 phase 2, Swift 제외.
- 명단 확정은 D12 (rubric + no-churn).

## D10 (2026-09-21): Baseline 정의

- Triage: B0 random / B1 rule / B2 LLM-judge(샘플) / B3 Semgrep.
- E2E: E0 SAST / E1 single-LLM / E2 static+LLM(Jev 제외).
- 상세: [eval.md](eval.md).
- 전신 D4는 본 항목에 흡수 후 삭제됨 (번호는 결번 유지).

## D11 (2026-09-21): P0=P1 통일 명단 + impact 공동기준

- P0(측정)와 P1(발견) 트랙 통일. 라벨/학습 재사용.
- 선정 기준에 impact(발견 시 파급력) 추가. 측정 최적 + impact 포트폴리오.
- Discourse → Mastodon 교체 (연합 프라이버시 impact).
  Discourse 산출물(targets/data)은 폐기.

## D12 (2026-09-21): 트랙 확정 + no-churn

- Rubric 확정: labelability 40 / impact 30 / yield 20 / friction 10.
- 명단 확정: Mastodon / 7-Zip / Kanidm / K8s-RBAC.
- P0 중 교체 금지. 기술적 봉쇄시에만 예외.
- 확장 게이트: 1트랙 × 50라벨 먼저, 신호 확인 후 나머지.

## D13 (2026-09-21): 블라인드 라벨링 프로토콜

- 라벨러는 격리 서브에이전트 (own context). 입력은 guide + review만.
- 파일 접근 감사로 manifest/scores/data 미열람 확인. 004에서 검증됨.

## D14 (2026-09-21): 구 로드맵 폐기, 전제 중심 재수립

- 기존 P0~P4 로드맵 폐기 (제품형태 중심이라 전제와 어긋남).
- 전제: Jev + LLM으로 정적분석/리버싱에서 빠르고 효율적이고 정확하게.
- G1 정적분석 완증은 P0/P1로 계속. G2(리버싱 전이) 편입 미확정
  (→ D15에서 편입 확정).

## D15 (2026-09-21): G2 리버싱 전이 편입

- 디컴파일 텍스트에 동일 파이프라인 전이 실험.
- 디컴파일러 미선정 (Ghidra headless 유력).

## D16 (2026-09-22): 목표 범위 = 전 버그 종류 + CodeQL 정면 비교

- 로직 한정 아님. 정적/리버싱으로 찾을 수 있는 모든 종류.
- D7(메모리 포함)의 상위 확정. Jev 질문·rubric도 전 범위 커버로.
- G1 exit에 CodeQL head-to-head: 전체 범위 recall 동등 이상 + 비용 우위.
- G2 a/b 분리 철회 (순서 메모로), G3 신설 철회 (G1 exit 한 줄로).
- agentic 재현 제외, 문헌 수치 인용으로만 참고.

