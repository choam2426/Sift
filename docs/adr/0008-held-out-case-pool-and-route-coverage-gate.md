# ADR 0008: held-out 사례는 oracle과 route coverage를 모두 통과해야 한다

- 날짜: 2026-10-21
- 상태: **REVISE, P0 수정 완료, 재리뷰 대기, 사례 pool 부족**. Mythos 5.1과 GPT-6 Astra가 REVISE를 냈고, P0 수정과 post-cutoff filter를 반영했다. 8개 confirmatory 세트는 아직 확정하지 못했다.
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

| 사례 | router | oracle | route | 상태 |
| --- | --- | --- | --- | --- |
| OpenList sharing path | Gin | 검증됨 | 231, handler+truncation 통과 | **provisional** |
| Semaphore role slug | mux | 검증됨 | 328, handler+truncation 통과 | **provisional** |
| Nginx UI secure session | Gin | adapter 필요 | 228, target 누락 | blocked |
| Arcane users:update | Echo | custom 필요 | 106, 통과 | dev project, exclude |
| rclone/Traefik | custom | upstream test | 2/1, target 누락 | blocked |
| Authorizer OIDC link | Gin | custom 필요 | 57, target truncated | fix 2026-08-07, gate fail |
| Cloudreve revoked share | Gin | custom 필요 | 157, target 존재 | fix commit 미확인 |
| Gotify/Pterodactyl/New API/SeaweedFS/Cosmos | — | 일부 검증 | — | fix가 cutoff 이전, exclude |

OpenList와 Semaphore는 oracle+handler+truncation+cutoff를 통과했지만, oracle 함수가 bundle에 없어 coverage gate를 통과하지 못한다. `eligible`로 부르지 않는다.

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

## P0 수정 (2026-10-21)

- `Use(...)`의 첫 middleware를 버리던 `x.Args[1:]`를 `x.Args`로 고쳤다.
- mux/Gin/Echo root router를 seed하고, Echo의 `(path, handler, middleware...)` 순서를 구분한다.
- nested group path를 항상 결합하고, handler를 middleware보다 먼저 넣어 80k truncation이 handler를 자르지 않게 했다.
- handler/middleware callee depth를 1로 줄여 target route가 truncate되지 않게 했다.
- `golden_test.py`에 Gin/Echo/mux/root/helper/middleware fixture를 추가했다.
- `check_coverage.py`는 target route/handler, `Truncated=false`, `Members ∩ fix_functions`를 검사한다.
- `e2e.py`는 모든 arm에 같은 질문을 주고, Jev reserve를 포함한 결합 상한, audit 무효화, 실제 decoy, panic reject, per-test 평가, semantic adjudicate를 추가했다.
- 단위 테스트: `test_e2e.py` 6개, `golden_test.py` 4개 통과.

## Post-cutoff filter 결과

수정 커밋 날짜를 확인하자 후보 pool이 크게 줄었다. 모델 기준일은 2026-06-30이다.

| 사례 | 수정 커밋 날짜 | post-cutoff | 판정 |
| --- | --- | --- | --- |
| OpenList | 2026-07-10 | 예 | oracle는 검증됐지만 oracle 함수가 bundle에 없음 → gate fail |
| Semaphore | 2026-07-05 | 예 | oracle는 검증됐지만 `db.ValidateRole`이 bundle에 없음 → gate fail |
| Nginx UI | 2026-07-03 | 예 | target route 누락 |
| Arcane | 2026-07-29 | 예 | dev project |
| rclone | 2026-07-08 | 예 | route table 없음 |
| Traefik | 2026-08-28 | 예 | route table 없음 |
| Gotify | 2026-04-19 | **아니오** | 제외 |
| Pterodactyl | 2026-05-23 | **아니오** | 제외 |
| New API | 2026-05-19 | **아니오** | 제외 |
| SeaweedFS | 2026-05-12 | **아니오** | 제외 |
| Cosmos | 2026-05-26 | **아니오** | 제외 |
| Cloudreve/Authorizer/Woodpecker | 미확인 | 미확인 | 보류 |

SSA 보강 후 OpenList는 oracle 함수까지 포함해 gate를 통과했다. Semaphore는 OSS route가 404 stub이라 제외한다. 현재 **post-cutoff + oracle + oracle-function coverage**를 만족하는 사례는 **OpenList 1개**다. 8개 confirmatory 세트는 아직 만들 수 없다.

## SSA call-graph enrichment (2026-10-21)

AST route extraction alone cannot see the authorization decision when it sits behind package/interface calls. `extract_calls` now loads the module with `go/packages`, builds an SSA call graph (CHA), and enriches each route with reachable functions.

- AST route is generated with `-depth 0` (compact handler/middleware), then SSA enrichment adds the call-graph index and selected project-function sources.
- OpenList target `GET /sd/:sid/*path` now contains `internal/op.GetSharingUnwrapPath` in both `Members` and `Text`, with `Truncated=false`. `check_coverage.py` passes.
- Semaphore is excluded: in the OSS build `pro/api.RolesController.AddRole` is a 404 stub, so the `db.ValidateRole` oracle is not reachable from a route.
- Current post-cutoff + oracle + oracle-function coverage: **OpenList only (1)**.
- SSA enrichment is CHA-based and over-approximates interface dispatch. It is an index, not a proof. Each case still needs the gate and manual review.

## 결정

- Extractor는 P0 수정 후 재리뷰 전까지 동결한다.
- `eligible=true`는 oracle, handler identity, truncation, publication cutoff, 재리뷰를 모두 통과한 뒤에만 쓴다.
- 8개 세트가 없으므로 confirmatory를 시작하지 않는다.
- 다음 선택지:
  - **A. 후보 pool 확장**: post-cutoff 수정 커밋과 Gin/Echo/mux route를 가진 Go authz 사례를 더 찾는다.
  - **B. 범위 축소**: OpenList·Semaphore 중심의 2~3 사례 파일럿으로만 보고하고 confirmatory 주장을 하지 않는다.
  - **C. intervention 변경**: custom router 사례에는 route index 대신 function-unit index를 쓰는 별도 실험을 설계한다. 기존 3-arm과 직접 비교하지 않는다.
- 권고: **A를 먼저** 하고, 8개가 계속 안 되면 B로 범위를 줄이거나 C를 별도 실험으로 분리한다.

## 아직 남은 일

- oracle 함수를 포함하는 decision-path 추출(깊은 call graph 또는 fix-independent unit index)
- P0 수정 후 Mythos/Astra 재리뷰와 finding-level semantic gate 보완
- Authorizer target truncation, Cloudreve fix commit 확인
- runtime route recall 검사와 exact handler identity fixture
- 8개 post-cutoff 사례 확보
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
- **감사**: direct docker/network 호출은 그 run을 무효화해 censored로 기록한다. 자동 재실행으로 대체하지 않는다. 인프라 장애만 사전에 정한 1회 재실행을 허용하고, 모든 시도를 남긴다. workspace 내부 `../`는 수동 검토한다.
- **오염**: `.git`·advisory·fix 이력을 제거하고 네트워크를 차단한다. post-cutoff만으로 오염이 없다고 주장하지 않는다.

## 실행 전 gate

1. 후보의 취약·수정 소스가 오프라인에서 빌드된다.
2. oracle이 취약판에서 `--- FAIL:`로 실패하고 수정판에서 통과하며, decoy(무관한 변경)에서는 같은 실패가 재현된다.
3. route bundle이 대상 route를 포함한다. 포함하지 않으면 extractor를 고치거나 사례를 제외한다.
4. 세 조건의 비용 회계와 Jev 비용이 기록된다.
5. 8개 미만이면 backup 순서대로 채우되, 결과를 본 뒤 사례를 바꾸지 않는다.

## 출처

- 후보·커밋·상태: `experiments/logic-ranker/e2e/heldout-candidates.json`
- OpenList: GHSA-86cx-wwf4-phq4, commit `59bd343`; oracle `internal/op/heldout_sharing_test.go`
- Gotify: GHSA-3hcj-9m7p-wwm9, commit `a874448`; oracle `router/heldout_password_test.go`
- Semaphore: GHSA-cxvf-gvfq-36w2, commit `bb2a4e1`; upstream `db/Role_test.go`
- 나머지 후보의 GHSA·커밋은 후보 JSON에 기록했다.
