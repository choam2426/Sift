# ADR 0013: Sift 종료 결과와 보안 byproduct의 공개 상태

- 날짜: 2026-11-10
- 상태: 채택
- 관련: [ADR 0009](0009-conclude-research-after-stage-0.md)(Phase 1 결론), [ADR 0011](0011-stop-phase2-after-pilot.md)(Claude Phase 2 종료), [ADR 0012](0012-deepseek-v41-flash-planted-study.md)(DeepSeek 파일럿 종료)

## 맥락

Sift의 연구 질문은 Jev를 코딩 에이전트에 붙였을 때 취약점 발견 비용이 개선되는지였다. Phase 1은 개발 사례 4개에서 탐색적 결론을 냈고([ADR 0009](0009-conclude-research-after-stage-0.md)), Phase 2와 DeepSeek 후속 실험은 파일럿에서 종료됐다([ADR 0011](0011-stop-phase2-after-pilot.md), [ADR 0012](0012-deepseek-v41-flash-planted-study.md)). 두 후속 실험은 Jev 효과의 새 추정치를 주지 않았다.

실험 과정에서 연구 질문과 별개인 보안 byproduct가 나왔다. 이 ADR은 연구를 닫으면서 그 공개 상태를 한 곳에 기록한다. 취약점의 기술 내용·PoC·제보 ID는 이 저장소에 기록하지 않는다. 비공개 advisory가 수정 전 공개되지 않도록 하기 위해서다.

## 결정

**Sift 연구를 종료하고, 추가 Jev 실험을 시작하지 않는다.** Phase 1 결론은 그대로 유지한다. Phase 2·DeepSeek의 H1~H3는 미평가다.

보안 byproduct의 상태는 다음과 같다.

| Byproduct | 제출 경로 | 상태 |
| --- | --- | --- |
| Grafana 인가 결함 | 비공개 신고 채널 | 제출됨, triage 대기 |
| Gitea 인가 결함 A | Gitea 비공개 security advisory | 제출됨, triage 대기 |
| Gitea 결함 B | 공개 fix PR | PR 제출됨, 비공개 advisory 아님 |

- 제출 ID, advisory URL, PR 번호는 신고자가 보관한다. 이 저장소에는 기록하지 않는다.
- CVE는 아직 없다. CVE 발급은 Gitea/GitHub CNA가 수정·공개 과정에서 결정한다. 제출만으로 보장되지 않는다.
- 결함의 기능·컴포넌트 이름도 수정·공개 전에는 이 저장소에 쓰지 않는다. 범위를 좁혀 재발견을 돕기 때문이다.
- 비공개 advisory의 기술 내용·PoC·재현 코드는 저장소 밖 비공개 패키지에 둔다. 결함 B는 공개 PR로 제출됐으므로 그 PR이 공개 기록이 된다.
- byproduct는 Jev 효과의 증거가 아니다. Phase 1 결론과 제품 판단을 바꾸지 않는다.

## 이유

1. **연구 질문과 byproduct를 분리한다.** 보안 발견은 실험 harness의 부산물이지, Jev ranking의 효과를 보여 주는 결과가 아니다.
2. **공개 상태를 혼동하지 않는다.** 같은 Gitea 저장소의 두 발견이라도 하나는 비공개 advisory, 다른 하나는 공개 PR이다. 문서에서 이를 구분해야 embargo와 공개 기록이 섞이지 않는다.
3. **CVE를 약속하지 않는다.** CVE는 CNA의 판단이다. 연구 기록이 CVE 발급을 전제로 쓰이면 안 된다.
4. **재현 자료를 보존한다.** 사례·harness·분석 코드는 후속 연구의 설계 자료로 남기지만, 활성 실험으로 운영하지 않는다.

## 결과의 지위

- Phase 1: 개발 사례 4개의 탐색적 결론. Jev는 긴 탐색에서 비용을 줄였지만, valid finding당 차이는 작았고 검증 실패가 이득을 상쇄했다.
- Phase 2: 파일럿 종료. Jev/BM25/vanilla의 본 비교는 실행하지 않았다.
- DeepSeek: 파일럿 종료. Argo CD 1건만 valid였고, Gitea는 심은 결함이 아닌 다른 실제 결함을 찾아 topdir 판정을 통과하지 못했다.
- 보안 byproduct: 위 표의 상태. 연구 결론과 별개다.

## 재개 조건

1. Jev 효과를 다시 측정하려면 새 프로토콜과 새 예산으로 시작한다. 기존 큐를 이어 붙이지 않는다.
2. 보안 byproduct의 triage 결과가 오면 이 ADR에 상태만 갱신한다. 기술 내용은 비공개 패키지에 둔다.
3. 결함 B의 PR이 수정·병합되면 PR 상태와 날짜를 기록한다. CVE가 발급되면 그 사실만 기록한다.
4. 새로운 공개가 필요하면 유지관리자와 일정을 조율한 뒤 진행한다.
