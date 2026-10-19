# Sift

2026-10-19 기준. Sift의 목표는 **Jev(SystemOne)와 강한 코딩 에이전트의 협업으로 실제 취약점 발견의 시간·비용 대비 성과를 높일 수 있는지** 연구하고, 그 방법을 구현하는 **도구**와 효과를 검증하는 **논문**을 만드는 것이다.

현재 활성 실험은 **Go 인가/접근 제어 로직 버그에서 Jev 1.14를 후보 ranker로 쓰는 것**이다. Jev는 검증자가 아니라 후보 순위기이며, `vanilla`/`route-index`/`jev` 3-arm을 같은 예산·환경에서 비교한다([ADR 0007](docs/adr/0007-three-arm-ranker-evaluation-after-independent-review.md)). C/C++ 메모리 안전성 testbed와 사례는 파일럿·대조 자료로 보존한다.

공개 사례는 통제 평가에, 신규 발견 주장은 사전에 방법을 고정한 전향적 오픈소스 평가에 사용한다. 완료한 발견에는 보고서와 취약판·수정판 PoC의 독립 교차 검증이 필요하다.

실험 대상과 실행 경계는 [logic-ranker 실험](experiments/logic-ranker/README.md)과 [testbed](testbed/README.md)가 제공한다. C/C++ 사례 이미지는 고정 소스 빌드로 만든다([ADR 0005](docs/adr/0005-pinned-source-build-for-post-cutoff-cases.md)).

[활성 설계](DESIGN.md) · [연구 헌장](docs/adr/0001-jev-collaboration-research-charter.md) · [결정 기록](docs/adr/)
