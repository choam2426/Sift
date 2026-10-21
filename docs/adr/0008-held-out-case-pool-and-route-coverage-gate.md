# ADR 0008: held-out 사례는 oracle과 route coverage를 모두 통과해야 한다

- 날짜: 2026-10-21
- 상태: **REVISE, confirmatory 중단**. A 구현(commit `423d5b1`)을 Mythos 5.1과 GPT-6 Astra가 리뷰했고 둘 다 REVISE를 냈다. P0 수정 전에는 8개 held-out 실행을 시작하지 않는다.
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

### Route coverage (A 구현 후, extractor v7)

`extract_routes`를 gorilla/mux, helper 등록 함수, package alias 기반 handler 해석까지 확장했다. 전체 수치는 `experiments/logic-ranker/e2e/heldout-route-coverage.json`에 있다.

| 사례 | route 수 | 대상 route 포함 | 판정 |
| --- | ---: | --- | --- |
| Gotify | 37 | `POST current/user/password` | 사용 가능 |
| OpenList | 233 | `POST /share/create` | 사용 가능 |
| Semaphore | 329 | `GET/POST /api/roles` | 사용 가능 |
| Pterodactyl | 35 | `POST /upload/file`, `GET /download/file` | route 가능, oracle 필요 |
| New API | 320 | `GET /api/user/` | route 가능, oracle 필요 |
| Cosmos | 155 | `/cosmos/api/constellation/public-devices` | route 가능, oracle 필요 |
| Arcane | 106 | `PUT /users/{userId}` | route 가능, oracle 필요, dev project |
| Cloudreve | 157 | `share/:id` | route 가능, fix commit 미확인 |
| Authorizer | 276 | `/oauth_callback/:oauth_provider` | route 가능, fix commit 미확인 |
| Nginx UI | 231 | `/api/users/:id` 누락 | cosy generic router 미지원 |
| SeaweedFS | 107 | filer JWT route 누락 | custom handler 미지원 |
| Woodpecker | 42 | agent route 누락 | helper prefix 미지원 |
| goshs/OliveTin/rclone/Goploy | 3~5 | 대상 누락 | custom router 미지원 |
| Traefik/Echo/kin-openapi/SFTPGo | 0 | — | HTTP route table 없음 |

## 후보 pool

전체 후보와 상태는 `experiments/logic-ranker/e2e/heldout-candidates.json`에 있다.

| 우선순위 | 사례 | router | oracle | route | 상태 |
| ---: | --- | --- | --- | --- | --- |
| 1 | Gotify password change | Gin | 검증됨 | 37, 대상 포함 | **eligible** |
| 2 | OpenList sharing path | Gin | 검증됨 | 233, 대상 포함 | **eligible** |
| 3 | Semaphore role slug | mux | 검증됨 | 329, 대상 포함 | **eligible** |
| 4 | Pterodactyl JWT scope | Gin | custom 필요 | 35, 대상 포함 | route ready |
| 5 | New API root token | Gin | custom 필요 | 320, 대상 포함 | route ready |
| 6 | Cosmos bearer token | custom | custom 필요 | 155, 대상 포함 | route ready |
| 7 | Cloudreve revoked share | Gin | fix commit 미확인 | 157, 대상 포함 | fix 필요 |
| 8 | Authorizer OIDC link | Gin | fix commit 미확인 | 276, 대상 포함 | fix 필요 |
| 9 | Arcane users:update | Echo | custom 필요 | 106, 대상 포함 | dev project, backup |
| 10 | Nginx UI secure session | Gin | adapter 필요 | 231, 대상 누락 | blocked |
| 11 | SeaweedFS JWT prefix | custom | upstream test | 107, 대상 누락 | blocked |
| 12 | Woodpecker agent scope | Gin | fix commit 미확인 | 42, 대상 누락 | blocked |
| 13 | rclone/Traefik/goshs/OliveTin | custom | upstream test | 0~5, 대상 누락 | blocked |

## 결정과 구현

**A. Extractor를 gorilla/mux와 helper 등록 함수까지 확장한다.** 구현했다. Semaphore·OpenList·New API의 대상 route가 bundle에 들어왔고, route coverage를 자동 확인할 수 있게 됐다.

**B. Gin/Echo 사례로만 8개를 채운다.** A로도 8개가 안 되면 B를 병행한다.

A의 구현 범위:
- `Path`, `PathPrefix`, `Subrouter`, `Methods`, `HandlerFunc` 체인
- 중첩 group과 `Use` 미들웨어
- router group을 인자로 받는 helper 함수의 호출 site prefix
- selector 이름과 package basename이 일치하는 handler 우선 해석
- 중첩 호출에서 inner route 중복 방지

## 독립 리뷰 (2026-10-21)

Mythos 5.1과 GPT-6 Astra에게 extractor와 ADR 0008을 read-only로 리뷰시켰다. 둘 다 **REVISE**였다. 전체 보고서는 `~/sift-runs/notes/2026-10-21-heldout-review-mythos.md`, `~/sift-runs/notes/2026-10-21-heldout-review-astra.md`에 있다.

공통 P0:

1. **Coverage gate가 path string만 확인한다.** 대상 route의 `Members`가 fix가 건드린 함수를 포함하는지, `Truncated=false`인지 확인해야 한다. 지금은 경로가 같아도 handler가 다른 함수일 수 있다.
2. **`Use`가 첫 middleware를 버린다.** `main.go`의 `x.Args[1:]`는 `Use(Auth)`에서 Auth를 잃는다. `x.Args[0:]`로 고치고, helper route에 caller middleware를 붙여야 한다.
3. **Jev arm만 bug-class 질문을 받는다.** `route-index`와 `vanilla`에는 같은 질문이 없다. 질문을 모든 arm에 동일하게 주거나, 사례별 class 질문을 없애야 한다.
4. **Advisory 공개일이 후보 JSON에 없다.** post-cutoff 기준을 사례별로 기록하고, 수정 커밋 날짜도 확인해야 한다.

Astra가 추가로 지적한 P0:

- `reproduced`를 semantic review 전에 성공으로 계산한다.
- Jev 비용이 Claude 상한과 합산되지 않아 arm별 실효 상한이 다르다.
- Docker socket 접근과 audit flag가 결과를 무효화하지 않는다.

P1:

- root mux/net/http router 누락, helper 재귀·빈 prefix·인자 위치, `joinRoute`의 already-prefixed shortcut, package alias 해석, silent drop, 진짜 decoy 부재, panic 처리, oracle-informed `task_scope`, extractor를 target에 맞춰 반복 수정한 점, 3회 반복의 power 부족, audit 재실행의 optional stopping.

## 결정

- Extractor는 reviewed commit `423d5b1`에 동결한다. 추가 target-fit 수정은 하지 않는다.
- P0를 별도 변경으로 고치고, golden fixture와 target bundle의 handler identity/truncation 검사를 추가한다.
- P0 수정 후 같은 두 리뷰어에게 재리뷰를 받는다. 그 전에는 confirmatory를 실행하지 않는다.
- `eligible=true`는 oracle, handler identity, truncation, publication cutoff를 모두 통과한 뒤에만 쓴다.

## 아직 남은 일

- P0 수정: middleware, 질문 대칭, publication date, coverage gate, semantic review, budget ledger
- golden extractor fixture와 runtime route recall 검사
- Pterodactyl·New API·Cosmos의 behavior oracle
- Cloudreve·Authorizer의 fix commit 확인
- 8개 eligible 사례 확정 후 pre-registration 동결

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
