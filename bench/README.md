# 벤치

이 구성이 이 대상에서 버그에 닿는지 확인한다([DESIGN.md](../DESIGN.md) 5절).

2026-10-01 기준, 이 디렉터리의 공개 라벨과 공개 데이터셋 사례는 구현·구성 개발과 학습 오염 진단에 사용한다. 연구자에게 봉인한 사례도 모델이 학습하지 않았다고 보장할 수 없으므로 새 취약점 발견 효과의 최종 판정군에는 포함하지 않는다([ADR 0021](../docs/adr/0021-prospective-cases-for-novel-discovery.md)).

C/C++의 새 공개 벤치는 CyberGym Level 0을 기준으로 삼는다. 공식 10개 부분집합은 설치와 연결 파일럿에만 쓰며, 효과 비교 표본으로 해석하지 않는다. 다언어 사례는 CyberGym의 취약판 제공·숨긴 수정판 검증·최종 PoC 제출 계약을 유형별 오라클에 맞게 확장한다([ADR 0023](../docs/adr/0023-use-cybergym-level-0-as-c-anchor.md)). 아래 라벨과 Magma 도구는 기존 선별 접근의 근거와 개발 자료로 유지한다.

- `labels/`: 라벨 사례. 설계용 5개의 구성과 선정 이유는 [ADR 0013](../docs/adr/0013-evaluation-cases.md)에 있다. 봉인 사례의 기전은 Git에서 제외된 `data/sealed/`에만 두고 설계 중에는 열지 않는다.
- [`magma/`](magma/README.md): Magma의 대상과 버그로 1차 순위와 2차 구성을 재는 준비·스캔 도구. 한 리비전에 버그가 여러 개라 스캔 한 번으로 라벨을 여러 개 얻는다.
- 측정 도구: 1차 순위, 2차 묶음 도달률, 기준선 대비 순위.
  - 판정 척도는 코드 양 기준 재현율이다. 후보 순서대로 코드의 일정 비율(10~30%)을 읽을 때 담기는 버그의 비율을 목표([ADR 0018](../docs/adr/0018-candidate-goal-by-code-share.md))와 비교한다. 무작위 순서와 긴 함수부터 읽는 순서를 함께 보고한다.
  - Magma용 도구는 [`magma/recall.py`](magma/recall.py)다.
  - 2026-10-01 상태: 설계용 라벨의 도달률 스크립트는 아직 옮기지 않았다. Magma 라운드별 평가 스크립트는 `data/magma-2026-09-29/`에 있다.
- 대상 자신의 과거 보안 수정으로 구성을 검증하는 절차. 2026-09-29 상태: 작성 전.

라벨 형식: `case_id`, `target`(root, revision, source), `fix_reference`, `bug`, `target_function`, `essential_context`(`경로:줄-줄`과 이유), `related_functions`(`경로:함수 이름`과 역할). 함수는 시작 줄이 구성마다 달라질 수 있어 이름으로 적는다.
