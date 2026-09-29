# 벤치

이 구성이 이 대상에서 버그에 닿는지 확인한다([DESIGN.md](../DESIGN.md) 5절).

- `labels/`: 라벨 사례. 설계용 5개의 구성과 선정 이유는 [ADR 0013](../docs/adr/0013-evaluation-cases.md)에 있다. 봉인 사례의 기전은 Git에서 제외된 `data/sealed/`에만 두고 설계 중에는 열지 않는다.
- [`magma/`](magma/README.md): Magma의 대상과 버그로 1차 순위와 2차 구성을 재는 준비·스캔 도구. 한 리비전에 버그가 여러 개라 스캔 한 번으로 라벨을 여러 개 얻는다.
- 측정 도구: 1차 순위, 2차 묶음 도달률, 기준선 대비 순위. 2026-09-30 상태: 설계용 라벨의 도달률 스크립트는 아직 옮기지 않았다. Magma 평가 스크립트는 `data/magma-2026-09-29/`에 있다.
- 대상 자신의 과거 보안 수정으로 구성을 검증하는 절차. 2026-09-29 상태: 작성 전.

라벨 형식: `case_id`, `target`(root, revision, source), `fix_reference`, `bug`, `target_function`, `essential_context`(`경로:줄-줄`과 이유), `related_functions`(`경로:함수 이름`과 역할). 함수는 시작 줄이 구성마다 달라질 수 있어 이름으로 적는다.
