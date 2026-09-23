# Falsify — 제품 정의

> "Instead of looking for unsafe code, find unsafe assumptions."
> 이 문서는 왜/누구/무엇만 다룬다.
> 어떻게 → [아키텍처](architecture.md), 순서 → [로드맵](roadmap.md).

## 문제

- App-specific 버그는 SAST가 못 잡고,
  LLM 통째로는 비싸고 시끄러움 (PrimeVul 3% F1급).
- C/C++ 메모리 버그는 기존 도구 + 퍼징이 있으나 triage가 사람 손.
- 공통 병목: **어디를 볼지(선별) + 왜 위험한지(전제) + 진짜 깨지나(확증).**

## 사용자

취약점 연구원. Repo를 넣으면 검증 가능한 것만 받는 사람.

## 제품

```text
입력: repo (버전 고정) 또는 바이너리 (디컴파일 경유, G2)
출력: ranked findings — 각각 invariant + 위반 근거 + PoC (미확증은 lead로 분리).
최종 취약점 판정은 연구원.
가격 감각: SAST급 비용, 분석가급 깊이 (전 버그 종류, D16)
```

새 유형 추가 = 프로필(질문셋 + 정답지 정의) 추가, 파이프라인 수정 없음
(Generic-by-type, D8).

## Non-goals (지금)

자동 수정(auto-fix), 실시간 IDE 연동, 디컴파일 없는 바이너리 직접 분석.
Agentic은 [5] PoC loop에만 허용, 파이프라인 본체는 고정 funnel.
