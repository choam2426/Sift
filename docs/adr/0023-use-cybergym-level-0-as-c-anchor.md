# CyberGym Level 0을 C/C++ 기준 벤치로 사용하고 과제 계약을 다언어로 확장한다

2026-10-01 결정. C/C++ 메모리 안전성의 공개 개발군은 CyberGym Level 0을 기준 벤치로 사용한다. Level 0은 취약점 설명 없이 패치 전 코드에서 취약점을 찾고 PoC를 만들게 한다. 생성한 PoC를 취약판과 수정판에서 실행해 특정 수정으로 사라지는 충돌인지 검증할 수 있어, [첫 실험의 완료 조건](0020-first-study-reproduced-findings.md)과 [Sift의 1차·2차 Jev 선별](0025-restore-second-jev-stage.md)을 연결하기에 적합하다([CyberGym 논문](https://arxiv.org/html/2506.02548)).

CyberGym 기본 평가인 Level 1은 취약점의 대략적인 위치, 유형과 원인이 들어갈 수 있는 설명을 에이전트에 제공한다. 이 설정은 알려진 취약점의 PoC 재현 능력을 따로 측정할 때 사용하고, Jev가 조사 위치를 정하는 효과의 주된 비교에는 사용하지 않는다.

운영 계약은 다음과 같이 둔다.

- 에이전트에는 취약판 코드와 실행 환경만 제공하고, 수정판과 정답 자료는 평가기만 사용한다.
- 에이전트의 외부 검색을 막고 저장소 이력, 기준 PoC와 수정 자료를 제거한다.
- 여러 시도 중 하나가 아니라 에이전트가 고른 최종 PoC 하나를 채점한다.
- PoC가 취약판에서 문제를 일으키고 수정판에서 같은 문제가 사라지는지 실행으로 확인한다.
- 실행 채점에 더해 위치, 발생 조건, 원인과 영향을 담은 보고서를 독립적으로 검증한다.

이 계약은 CyberGym의 공식 운영 지침과 최종 제출 채점 권고를 따른다([저장소](https://github.com/sunblaze-ucb/cybergym), [FAQ](https://github.com/sunblaze-ucb/cybergym/blob/main/FAQ.md)).

공식 10개 부분집합은 설치, 실행 환경과 Sift 연결을 확인하는 파일럿에만 사용한다. 이 부분집합은 기존 에이전트가 PoC를 만들 수 있었던 사례 5개와 어려웠던 사례 5개로 의도적으로 구성됐으므로 전체 성능을 대표하는 효과 비교 표본으로 해석하지 않는다. 효과 비교에 사용할 사례 수, 프로젝트 중복 제한과 난이도 층화는 파일럿 뒤 결과를 보기 전에 별도로 고정한다.

CyberGym과 CyberGym-E2E는 현재 주로 C/C++ 메모리 안전 취약점과 sanitizer 충돌 오라클에 집중한다. Rust·Go·Python·JavaScript와 인가 우회, 경로 처리, 정보 노출, 자원 고갈 같은 비충돌형 취약점은 같은 과제 계약을 유지하면서 유형별 실행 오라클로 확장한다. CyberGym-E2E의 코드만 제공하는 격리 환경은 참고하되, 패치 작성 능력이 첫 연구 결과에 섞이지 않도록 첫 비교에는 패치 생성을 요구하지 않는다([CyberGym-E2E 논문](https://arxiv.org/html/2606.04460), [저장소](https://github.com/sunblaze-ucb/cybergym-e2e)).

모든 CyberGym 사례는 공개된 과거 취약점이므로 [ADR 0021](0021-prospective-cases-for-novel-discovery.md)의 공개 개발군 또는 오염 진단군으로만 사용한다. 이 결과만으로 새 취약점 발견 효과를 주장하지 않는다.
