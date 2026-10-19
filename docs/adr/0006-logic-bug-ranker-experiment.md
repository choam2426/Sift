# ADR 0006: 활성 실험은 Go 인가 로직 버그의 Jev ranker다

- 날짜: 2026-10-19
- 상태: 채택. C/C++ 메모리 안전성 testbed(ADR 0001~0005)는 파일럿·대조로 보존하고, 활성 실험은 이 ADR을 따른다.
- 관련: [ADR 0001](0001-jev-collaboration-research-charter.md), [ADR 0003](0003-cost-as-matched-budget-and-first-run-measures-consumption.md), [ADR 0004](0004-measurement-cases-after-training-cutoff.md), [ADR 0005](0005-pinned-source-build-for-post-cutoff-cases.md)

## 맥락

C/C++ 메모리 안전성 파일럿에서 libzip은 fuzzing으로 6.13달러에 발견됐고, libhevc는 28.30달러를 쓰고도 발견하지 못했으며 감사 표시가 있었다. fuzzing이 결과를 지배하면 Jev의 의미적 기여를 분리하기 어렵다. 로직 버그는 명세 추론·상태·인가 경계가 핵심이므로 Jev의 후보 순위 신호를 측정하기에 더 맞는다.

archive를 확인한 결과 Jev는 검증자가 아니라 **후보 ranker**다. `jev-1.14.0`은 `POST /v1/systemone`에 `state`와 질문을 보내 Noul 점수를 받는다. 설명·위치·테스트를 반환하지 않는다. 따라서 Jev에게 검증을 맡기지 않고, 후보 순위만 맡긴다.

## 결정

1. **활성 범위는 Go 인가/접근 제어 로직 버그다.** C/C++ 메모리 안전성 testbed는 삭제하지 않고 파일럿·대조 자료로 둔다.
2. **Jev는 ranker다.** 점수는 조사 우선순위 신호이며 취약점 확률·검증 결과가 아니다. 낮은 점수는 안전성의 증명이 아니다.
3. **두 arm으로 비교한다.** 순정 강한 에이전트와 Jev ranker가 주어진 강한 에이전트. 같은 소스·도구·검증 가이드·금전 상한을 쓰고, Jev 호출 비용은 총예산에 포함한다. Jev arm도 Jev를 반드시 써야 하지는 않는다.
4. **unit은 함수가 아니라 결정 경로다.** 진입점, 인가/검증 결정, 상태·설정, 보호된 동작, 오류 경로를 포함한다. 라우트 등록·미들웨어 체인·핸들러·직접 호출 결정 함수를 한 단위로 묶는다.
5. **Jev 1.14.0을 명시적으로 고정한다.** `jev-latest`/`jev-preview` 별칭은 쓰지 않는다. 기본 64k/request·32k/question, 긴 문맥은 별도 profile로만 쓴다. Noul은 절대 임계값이 아니라 top-K 순위로 쓴다.
6. **사례는 post-cutoff Go 보안 수정에서 고른다.** 아래 네 사례의 취약·수정 리비전과 숨겨진 오라클을 고정한다.
7. **1차 평가는 offline ranker다.** 알려진 결정 경로 entry/route의 순위, Recall@K, 길이·random 대비 lift, Jev 비용을 측정한다. 2차는 end-to-end다.
8. **end-to-end 지표는 검증된 발견당 비용이다.** 보조 지표는 첫 발견까지 비용, Jev 호출 비용, 실제 Jev 사용량, 정밀도, 미도달이다.

## 사례

| 사례 | 결함 | 취약 → 수정 | Go | 숨겨진 오라클 |
| --- | --- | --- | --- | --- |
| Kite | K8s proxy 경로 탐색 → RBAC 우회 | `d74c979` → `08116ee` (v0.14.1) | 1.26 | `go test ./pkg/kube -run TestBuildProxyURL` |
| Pocket ID | OIDC refresh token 인가 우회 | `59fe481` → `978ac87` (v2.6.0) | 1.26 | `go test ./internal/service -run TestOidcServiceRefreshTokenAuthorizationState` |
| Vikunja | cross-tenant IDOR (kanban task bucket) | `37c35c6` → `36cdc2c` (v2.4.0) | 1.26 | `go test ./pkg/webtests -run 'TestTaskBucketV2/task_from_a_foreign_project_is_forbidden'` |
| Arcane | environment token이 admin gate 우회 | `6006dbe` → `4fe4c7e` (backend v2.11.0) | 1.27 | `go test ./internal/auth -run TestAuthMiddleware` |

네 수정 테스트는 취약판 소스에서 컴파일되고 실패하며, 수정판에서 통과함을 확인했다. Vikunja는 테스트용 `frontend/dist/index.html` 자리표시자가 필요하고, Arcane은 `backend/`에서 `../types`·`../cli` replace 경로가 유지돼야 한다.

## Stage 1 결과 (2026-10-19)

함수 단위 bundle 2,115개를 Jev 1.14.0으로 채점했다. 이어서 라우트 인식 unit 742개를 채점했다. 총 Jev 비용은 약 1.67달러였고 오류는 없었다.

라우트 단위에서 알려진 결정 경로의 순위:

| 사례 | 대상 라우트 | Jev 순위 | 길이 기준 |
| --- | --- | ---: | ---: |
| Kite | `GET /namespaces/:namespace/:kind/:name/proxy/*path` | **1/130** (0.8%) | 103/130 (79.2%) |
| Pocket ID | `POST /oidc/token` | **2/110** (1.8%) | 80/110 (72.7%) |
| Vikunja | `PUT /projects/{project}/views/{view}/buckets/{bucket}/tasks` | **28/355** (7.9%) | 228/355 (64.2%) |
| Arcane | `GET /debug/pprof/` | 18/147 (12.2%) | 38/147 (25.9%) |

- 네 사례 모두 Jev top 13% 안에 들었다. Kite·Pocket ID는 top 2%다.
- 같은 사례의 수정 함수 자체는 낮게 순위가 매겨졌다. 수정 함수는 helper이고, 실제 결정 경로 entry/route가 더 좋은 단위다.
- 라우트 인식 단위는 함수 단위 bundle보다 Kite·Pocket ID에서 크게 개선됐다.
- Arcane은 pprof 라우트 묶음도 0.21로 개별 라우트와 비슷했고, 최고 pprof 라우트는 16/147(10.9%)였다. 미들웨어 체인은 unit에 포함됐지만 추가 개선 여지가 있다.

이 결과는 **가능성**을 보여주지만 end-to-end 효율을 증명하지 않는다. 질문은 사례별 불변식으로 고정한 ceiling test였고, 프로젝트당 알려진 버그는 하나다.

## Kite e2e 파일럿 (2026-10-19)

Kite 한 사례로 순정과 Jev ranker를 각 1회 실행했다. 두 arm 모두 `buildProxyURL` 경로 탐색 결함을 찾고 테스트를 제출해 `reproduced` 판정을 받았다.

| 항목 | 순정 | Jev ranker |
| --- | ---: | ---: |
| Claude 비용 | $1.436 | $1.348 |
| Jev 비용 | — | $0.0245 (130요청, 582,973토큰) |
| 총비용 | **$1.436** | **$1.373** |
| 턴 | 16 | 18 |
| 소요 시간 | 171초 | 224초 |
| 감사 | 경계 이탈 없음 (workspace 내부 상대 경로 2건) | 경계 이탈 없음 (동일) |

Jev arm은 라우트 130개를 한 번 채점해 대상 `/namespaces/.../proxy/*path`를 top 1로 올렸다. 총비용 차이는 $0.063(4.4%)으로 작았다. Kite는 국소적이고 명시적인 가드라 순정도 빠르게 찾는 ceiling case이므로, 이 결과를 Jev의 일반 효과로 해석하지 않는다.

## 다음

1. Pocket ID(refresh state machine)와 Vikunja(cross-tenant IDOR)로 end-to-end를 확장한다. Kite는 ceiling/control로 둔다.
2. Jev arm의 `routes.jsonl` 생성을 `extract_routes`로 자동화하고, 질문 템플릿을 사전 고정한다.
3. 반복 횟수와 사례 수를 파일럿 비용·변동성을 보고 정한다.
4. 감사에서 workspace 내부 상대 경로와 실제 경계 이탈을 구분하도록 개선한다.

## 한계

- Jev 1.14는 소폭 개선 버전이며 코드 triage에서 1.13보다 낫다고 가정하지 않는다. 필요하면 같은 라벨로 1.13/1.14를 비교한다.
- Noul은 보정된 확률이 아니고, 점수 분포는 프로젝트·질문마다 다르다.
- 라우트 인식 추출기는 Gin/Echo/Huma의 일반적인 패턴만 다룬다. 동적 라우트·필드 함수·인터페이스 호출은 누락될 수 있다.
- post-cutoff 사례라도 취약 코드와 수정 설명이 학습 데이터에 있었을 수 있다. 결과와 함께 적는다.

## 출처

- Jev 1.14 모델·가격·컨텍스트: https://docs.typesafe.ai/models, https://typesafe.ai/blog/jev-1-14
- Kite: https://github.com/kite-org/kite, GHSA-c534-2w9c-x7fm / GO-2026-6105
- Pocket ID: https://github.com/pocket-id/pocket-id, GHSA-w6p7-2fxx-4f44 / GO-2026-6119
- Vikunja: https://github.com/go-vikunja/vikunja, GHSA-5pg6-m483-7vrg / GO-2026-6308
- Arcane: https://github.com/getarcaneapp/arcane, GHSA-mp22-58ff-6fhr
- Stage 1 기록: `~/sift-runs/notes/2026-10-19-stage1-ranker.md`, `~/sift-runs/measurements/jev-ranker-stage1/`
