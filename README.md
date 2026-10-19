# Sift

2026-10-16 기준. Sift의 목표는 **Jev(SystemOne)와 강한 코딩 에이전트의 협업으로 실제 취약점 발견의 시간·비용 대비 성과를 높일 수 있는지** 연구하고, 그 방법을 구현하는 **도구**와 효과를 검증하는 **논문**을 만드는 것이다. 도구의 구체적인 형태와 Jev의 역할은 아직 정하지 않았다.

첫 연구는 C/C++ 메모리 안전성의 white-box 조사다. Jev 협업을 강한 에이전트 단독 및 동종 강한 에이전트 복수 실행과 동일한 금전·시간 상한에서 비교한다. 공개 사례는 통제 평가에, 신규 발견 주장은 사전에 방법을 고정한 전향적 오픈소스 평가에 사용한다. 완료한 발견에는 보고서와 취약판·수정판 PoC의 독립 교차 검증이 필요하다.

실험 대상과 실행 경계는 [testbed](testbed/README.md)가 제공한다. 학습 기준일 이후 사례의 이미지는 고정 소스 빌드로 만든다([ADR 0005](docs/adr/0005-pinned-source-build-for-post-cutoff-cases.md)).

[활성 설계](DESIGN.md) · [연구 헌장](docs/adr/0001-jev-collaboration-research-charter.md) · [결정 기록](docs/adr/)
