# 결과 데이터

이 연구의 Go 로직 버그 e2e 실행 46회를 실행 단위로 정리한 표다. 결론과 해석은 [ADR 0009](../docs/adr/0009-conclude-research-after-stage-0.md)에 있다.

## 파일

### `runs.csv`

실행 한 번이 한 행이다.

| 열 | 뜻 |
| --- | --- |
| `study` | `route-2arm-pilot`(ADR 0006), `route-3arm-pilot`(ADR 0007), `stage0-unit`(제품 결정 메모 Stage 0) |
| `case` | `kite`, `vikunja`, `pocketid`, `arcane` |
| `arm` | `vanilla`, `route-index`, `jev`(route 단위 + Jev), `jev-unit`(file 단위 + Jev) |
| `run` | 같은 study·case·arm 안의 반복 번호 |
| `claude_usd` | Claude Code가 보고한 정가 기준 비용 추정치 |
| `jev_usd` | Jev 입력 토큰 × $0.042/1M |
| `total_usd` | `claude_usd + jev_usd` |
| `turns`, `wall_s` | 에이전트 턴 수, 경과 시간(초) |
| `technical` | 제출 test의 판정. `reproduced`는 취약판 3회 실패·수정판 3회 통과·decoy 3회 실패 |
| `semantic` | 연구자의 의미 검토. Stage 0에서만 기록했다 |
| `audit_*` | 도구 호출에서 감지한 경계 표시 횟수. `parent_path`는 대부분 workspace 안의 상대 경로였다 |
| `valid` | Stage 0만. 기술 판정·의미 검토·감사(docker/network/subagent)·비용 상한을 모두 통과 |
| `note` | 기록상 주의 사항 |

route 파일럿(`route-*`)에는 의미 검토와 `valid` 열이 없다. 그 시점의 harness에는 해당 단계가 없었다.

### `stage0-jev-file-ranks.csv`

Stage 0 `jev-unit` 실행에서 Jev가 매긴 file 단위 순위다. `file_kind`가 `fix`이면 수정 커밋이 바꾼 파일, `entry`이면 결함으로 가는 route 진입점 파일이다. `entry`는 결과를 본 뒤 사람이 지정한 진단용 표시다.

## 공개하지 않은 것

- 에이전트 전사(`stream.jsonl`): 분석 대상 오픈소스 프로젝트의 소스 코드가 섞여 있다.
- 에이전트가 제출한 `report.md`·`test.go`, Jev 호출 로그, 독립 리뷰 원문.
- 문서에 나오는 `~/sift-runs/...` 경로는 연구자 로컬의 원자료 위치다. 이 저장소에서는 접근할 수 없다.
