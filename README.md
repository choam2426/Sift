# Sift

Sift는 **Jev 같은 SystemOne 모델을 사용해 취약점을 더 빠르고 효율적으로 찾아낼 수 있는지** 연구하는 프로젝트다. 2026-10-01에 연구 목적을 다시 확인했으며, 구체적인 성공 기준과 분석 구조는 이 목적에 맞춰 재검토한다([ADR 0019](docs/adr/0019-systemone-vulnerability-research-goal.md)).

최종적으로는 **연구 결과를 바탕으로 사용자가 분석 대상에 맞는 Sift를 구축할 수 있는 가이드**를 제공한다. 가이드에는 효과가 확인된 조건과 한계를 반영한다.

지금까지 시험한 접근은 Jev로 함수와 관련 코드 묶음의 우선순위를 정하고, 연구원의 에이전트가 심층 조사하는 방식이다. 저장소에는 이 접근의 **설계, 스펙, 참조 구현과 실험 근거**가 있다.

**[설계](DESIGN.md)부터 읽는다.** 구축 절차는 [설치 가이드](INSTALL.md)에 있다.

| 제공물 | 위치 |
|---|---|
| 설계 | [`DESIGN.md`](DESIGN.md) |
| 스펙 | [`spec/`](spec/) |
| 보일러플레이트 (참조 구현) | [`boilerplate/`](boilerplate/) |
| 벤치 | [`bench/`](bench/) |
| 질문 라이브러리 | [`questions/`](questions/) |
| 운영 스킬 | [`skill/`](skill/) |
| 설치 가이드 | [`INSTALL.md`](INSTALL.md) |
| 결과 환류 | [`reports/`](reports/) |
| 실험 | [`experiments/`](experiments/README.md) |
| 결정 기록 | [`docs/adr/`](docs/adr/) |
