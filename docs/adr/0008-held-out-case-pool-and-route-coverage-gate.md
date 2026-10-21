# ADR 0008: held-out 사례는 oracle과 route coverage를 모두 통과해야 한다

- 날짜: 2026-10-21
- 상태: **제안**. confirmatory 실행은 아직 하지 않았다. 사례 선정과 extractor 범위를 사용자와 합의한 뒤 실행한다.
- 관련: [ADR 0007](0007-three-arm-ranker-evaluation-after-independent-review.md), [ADR 0004](0004-measurement-cases-after-training-cutoff.md)

## 맥락

개발 사례 4개(Kite, Vikunja, Pocket ID, Arcane)는 arm별 효과가 서로 달랐다. confirmatory에는 결과를 보지 않은 held-out Go authz 사례 8~12개가 필요하다. 후보를 public advisory에서 고르는 과정에서 두 가지 gate가 실제 병목임을 확인했다.

1. **Oracle gate**: 제출 테스트가 취약판에서 실패하고 수정판에서 통과해야 한다. upstream regression test가 새 함수·필드를 참조하면 취약판에서 컴파일되지 않으므로 그대로 쓸 수 없다.
2. **Route coverage gate**: 3-arm의 `route-index`와 `jev`는 같은 route bundle을 받는다. bundle이 대상 route를 포함하지 않으면 ranking 효과를 공정하게 비교할 수 없다.

## 확인한 사실

### Oracle

다음 세 사례는 취약판 실패·수정판 통과를 이 머신에서 확인했다.

| 사례 | GHSA | 취약 → 수정 | oracle | 결과 |
| --- | --- | --- | --- | --- |
| OpenList sharing path | GHSA-86cx-wwf4-phq4 | `757f9d3` → `59bd343` | custom `GetSharingUnwrapPath` 테스트 | 취약판 FAIL, 수정판 PASS |
| Gotify password change | GHSA-3hcj-9m7p-wwm9 | `c256025` → `a874448` | custom router/HTTP 테스트 | 취약판 200, 수정판 403 |
| Semaphore role slug | GHSA-cxvf-gvfq-36w2 | `323410f` → `bb2a4e1` | upstream `db/Role_test.go` | 취약판 FAIL, 수정판 PASS |

- Echo, kin-openapi, goshs, OliveTin, SeaweedFS, Traefik, rclone은 수정 커밋에 regression test가 있지만, 아직 취약판 컴파일·실패를 확인하지 않았다.
- Nginx UI의 `api/user/security_test.go`는 취약판에서 assertion failure가 아니라 panic을 낸다. evaluator는 `--- FAIL:`만 실패로 인정하므로 adapter가 필요하다.
- Pterodactyl, New API, Arcane users:update는 custom behavior test가 필요하다.

### Route coverage

현재 `extract_routes`는 Gin/Echo/Huma만 다룬다.

| 사례 | route 수 | 대상 route 포함 | 판정 |
| --- | ---: | --- | --- |
| Gotify | 37 | `POST current/user/password` 포함 | 사용 가능 |
| OpenList | 162 | `/share/create` 누락 | helper 등록 함수 때문에 불완전 |
| Semaphore | 1 | 없음 | gorilla/mux 미지원 |
| rclone/Traefik/SeaweedFS | — | — | HTTP route table 없음 |
| Pterodactyl/Nginx UI/New API | — | 미확인 | Gin이므로 추출 가능성 있음 |

## 후보 pool

전체 후보와 상태는 `experiments/logic-ranker/e2e/heldout-candidates.json`에 있다. 13개 후보 중 현재 `eligible=true`는 Gotify 하나다.

| 우선순위 | 사례 | router | oracle | route | 상태 |
| ---: | --- | --- | --- | --- | --- |
| 1 | Gotify password change | Gin | 검증됨 | 37, 대상 포함 | **eligible** |
| 2 | OpenList sharing path | Gin | 검증됨 | 162, 대상 누락 | repair 필요 |
| 3 | Semaphore role slug | mux | 검증됨 | 1 | extractor mux 지원 필요 |
| 4 | Pterodactyl JWT scope | Gin | custom 필요 | 미확인 | 보류 |
| 5 | Nginx UI secure session | Gin | adapter 필요 | 미확인 | 보류 |
| 6 | New API root token | Gin | custom 필요 | 미확인 | 보류 |
| 7 | Cloudreve revoked share | Gin | fix commit 미확인 | 미확인 | 보류 |
| 8 | Authorizer OIDC link | Gin | fix commit 미확인 | 미확인 | 보류 |
| 9 | Woodpecker agent scope | Gin | fix commit 미확인 | 미확인 | 보류 |
| 10 | Arcane users:update | Echo | custom 필요 | 미확인 | dev project, backup |
| 11 | rclone restic path | custom | upstream test | 없음 | route blocked |
| 12 | Traefik request-target | custom | upstream test | 없음 | route blocked |
| 13 | SeaweedFS JWT prefix | custom | upstream test | 없음 | route blocked |

## 결정 제안

**A. Extractor를 gorilla/mux와 helper 등록 함수까지 확장한다.** Semaphore를 즉시 사용할 수 있고, mux를 쓰는 Go 프로젝트로 후보가 넓어진다. route bundle이 대상 route를 포함하는지 자동 검증한다. 비용은 extractor 구현·회귀 테스트다.

**B. Gin/Echo 사례로만 8개를 채운다.** extractor는 그대로 두고, Gin/Echo 후보의 oracle을 만든다. 구현은 적지만 후보가 줄고, OpenList의 helper 등록 문제는 별도 repair가 필요하다.

권고: **A를 먼저 하고, 그래도 8개가 안 되면 B를 병행한다.** route extraction 자체가 제품 가설의 핵심이므로, 대상 route를 놓치는 extractor로 confirmatory를 돌리면 `route-index` arm을 부당하게 약화시킨다.

## 확정 전 pre-registration

사례가 eligible이 된 뒤, 결과를 보기 전에 다음을 고정한다.

- **Arm**: `vanilla`, `route-index`, `jev`. 같은 route bundle을 route-index와 jev에 제공한다.
- **질문**: bug class별 generic 질문 하나. 사례별 oracle 질문은 쓰지 않는다.
  - `route-authorization`: "Does this route enforce the caller's authorization for the resource and context it actually operates on before the protected operation?"
  - `body-object`: "Does this route authorize the object identified in the request body as well as the objects in the URL before the protected operation?"
  - `authorization-state`: "Does this route re-check the current authorization, account state, and group restrictions before issuing or extending credentials?"
  - `configured-gates`: "Does this route apply every configured authorization gate before the handler or side effect runs?"
- **K**: 10.
- **반복**: arm·사례당 3회, arm 순서는 사례별로 무작위화한다.
- **주 지표**: $30 cap에서 censoring한 cost-to-first-validated-finding. 실패는 censored로 기록한다.
- **보조 지표**: reproduced rate, turns, wall time, Jev 요청·토큰·비용, audit flags.
- **판정**: 사례별 paired 차이의 중앙값과 bootstrap 95% CI. CI가 0을 포함하면 효과를 주장하지 않는다.
- **재시도**: primary에서는 테스트 수정·재제출을 허용하지 않는다. rejected는 실패로 센다.
- **감사**: direct docker/network 호출은 그 run을 무효화하고 재실행한다. workspace 내부 `../`는 수동 검토한다.
- **오염**: `.git`·advisory·fix 이력을 제거하고 네트워크를 차단한다. post-cutoff만으로 오염이 없다고 주장하지 않는다.

## 실행 전 gate

1. 후보의 취약·수정 소스가 오프라인에서 빌드된다.
2. oracle이 취약판에서 `--- FAIL:`로 실패하고 수정판·decoy에서 통과한다.
3. route bundle이 대상 route를 포함한다. 포함하지 않으면 extractor를 고치거나 사례를 제외한다.
4. 세 조건의 비용 회계와 Jev 비용이 기록된다.
5. 8개 미만이면 backup 순서대로 채우되, 결과를 본 뒤 사례를 바꾸지 않는다.

## 출처

- 후보·커밋·상태: `experiments/logic-ranker/e2e/heldout-candidates.json`
- OpenList: GHSA-86cx-wwf4-phq4, commit `59bd343`; oracle `internal/op/heldout_sharing_test.go`
- Gotify: GHSA-3hcj-9m7p-wwm9, commit `a874448`; oracle `router/heldout_password_test.go`
- Semaphore: GHSA-cxvf-gvfq-36w2, commit `bb2a4e1`; upstream `db/Role_test.go`
- 나머지 후보의 GHSA·커밋은 후보 JSON에 기록했다.
