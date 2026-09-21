# Falsify — 제품 정의

> "Instead of looking for unsafe code, find unsafe assumptions."
> 상태: 방향 문서 (2026-09-21). 실험 결과에 따라 개정.

## 문제

- Memory-safe 코드의 로직/권한/상태 버그는 SAST가 못 잡고 (app-specific),
  LLM 통째로는 비싸고 시끄러움 (PrimeVul 3% F1급).
- C/C++ 메모리 버그는 기존 도구 + 퍼징이 있으나 triage가 사람 손.
- 공통 병목: **어디를 볼지(선별) + 왜 위험한지(전제) + 진짜 깨지나(확증).**

## 사용자

보안 엔지니어 / OSS 메인테이너. Repo를 넣으면 리뷰할 것만 받는 사람.

## 제품

```text
입력: repo (버전 고정)
출력: ranked findings — 각각 invariant + 위반 근거 + 재현 절차
가격 감각: SAST급 비용, 분석가급 깊이 (app-specific 로직 한정)
```

## 동작 원리 (Generic-by-type)

파이프라인은 공통, 지식은 유형별 프로필로:

```text
[0 Recon] → [1 Jev triage] → [Composer] → [2/3 Jev logic] →
[4 LLM deep dive] → [5 Falsify] → findings
```

새 유형 추가 = 프로필(질문셋 + 정답지 정의) 추가. 파이프라인 수정 없음.

상세: [architecture.md](architecture.md).

## 파일럿 트랙 (4)

```text
1. Discourse (web/logic)   2. 7-Zip (cpp/memory)
3. Kanidm (rust/logic)     4. K8s RBAC 패키지 (go/infra)
```

Phase 2: 스마트컨트랙트 미니트랙. Swift 제외 (D9).

## 로드맵

```text
P0 triage 파일럿 — 4트랙 × 50라벨, B0~B3 비교 (지금)
P1 e2e 1트랙 — 풀파이프라인 + E0~E2 비교, CVE 재발견
P2 멀티트랙 e2e — falsify harness 확충, B' 증폭기 실험
P3 제품 표면 — CLI/CI 연동, 리포트 포맷, 비용 대시보드
P4 prospective + disclosure — 신규 대상, 책임공개 프로세스
```

## Non-goals (지금)

Agentic loop, 자동 수정(auto-fix), 실시간 IDE 연동, 바이너리-only 대상.
