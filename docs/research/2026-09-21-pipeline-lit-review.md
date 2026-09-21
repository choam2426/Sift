# 파이프라인 구조 문헌 조사 (2026-09-21)

> deep-research 워크플로우 종합. 질문: Jev triage cascade + LLM deep dive +
> falsification 구조가 효과적인가, 더 좋은 구조는 없나.

## 종합 판정

구조 방향은 지지됨. Static prefilter/slice + LLM + verification이
이미 이기는 패턴으로 검증돼 있음. 단, 문헌이 보증하는 것은 static
구조이지 learned triage가 아님 (D1의 베팅 근거).

## 근거

1. **Single-LLM 단독은 약함.** 7B SOTA가 BigVul 68.26% F1 →
   PrimeVul 3.09% F1, GPT-3.5/4는 랜덤 수준.
   [PrimeVul](https://arxiv.org/abs/2403.18624).
   SecVulEval statement-level 최고 23.83% F1.
   [SecVulEval](https://arxiv.org/abs/2505.19828).
   Opus 4.6 CVE recall 25~28.5%, benign의 38~51%에서 오탐.
   [Zeropath](https://zeropath.com/blog/benchmarking-opus-4-6-vuln-detection).

2. **Static prefilter/slice + LLM은 검증됨.** LLift: ~1000 케이스
   zero miss, precision 50%, Linux 신규 UBI 버그 13개.
   [LLift](https://arxiv.org/abs/2308.00245).
   IRIS (CodeQL+GPT-4): 55/120 vs LLM 단독 27/120.
   [IRIS](https://arxiv.org/abs/2405.17238).
   LLMxCPG: CPG slice로 코드 68~91% 절감, F1 +15~40%, multi-function.
   [LLMxCPG](https://arxiv.org/abs/2507.16585).

3. **Agentic + verifier가 recall 최상이나 불안정.**
   Justification depth + 독립 verifier가 최고 recall, 최대 편차.
   Naptime 원칙으로 최대 20x (CyberSecEval2).
   [Naptime](https://projectzero.google/2024/06/project-naptime.html).
   Big Sleep 실전 0day (SQLite 2024-10, CVE-2025-6965 사전 탐지).
   [Big Sleep](https://projectzero.google/2024/10/from-naptime-to-big-sleep.html).
   함의: agentic loop는 phase 2, MVP는 고정 파이프라인.

4. **Flow형 세로 단위가 정석.** Taint-path 열거, slicing,
   CodeQL path query, Joern reachableByFlows + depth cap(기본 20).
   [CodeQL](https://codeql.github.com/docs/writing-codeql-queries/creating-path-queries/),
   [Joern](https://docs.joern.io/cpgql/data-flow-steps/).
   Composer의 flow extraction + cap 설계를 지지.

5. **규모/정밀 한계가 설계를 제약.** CodeQL bottom-up 전체 DB는
   성능 사망 (demand-driven/bounded 정당화).
   Semgrep OSS는 intraprocedural only.
   IRIS도 FDR 84.8% — falsification이 생사선.

## 설계 반영

- Composer는 static 뼈대 우선 (D5).
- Baseline 2단화 (D4). 강한 상대는 IRIS류.
- Falsification에 예산 우선 배분.
- Agentic 확장은 phase 2로 보류.

## 미해결/생략 범위

- Jev 자체 ranking 품질 (RQ1, 별도 파일럿으로).
- 비용/지연시간 수치, 언어별 tooling 적합성.
- 종합 과정에서 Jev를 static prefilter로 가정했던 점 주의 —
  본 문서는 재해석 반영됨.
