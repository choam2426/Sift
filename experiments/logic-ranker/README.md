# Logic-bug Jev ranker 실험

2026-10-19 기준. 활성 실험은 Go 인가/접근 제어 로직 버그에서 **Jev 1.14.0을 후보 ranker로 쓰는 것**이다. Jev는 검증자가 아니라 우선순위 신호다. 결정과 근거는 [ADR 0006](../../docs/adr/0006-logic-bug-ranker-experiment.md)에 있다.

## 사례

`cases.json`에 네 사례의 취약·수정 리비전, 숨겨진 테스트 명령, 대상 route, Jev 질문이 있다.

| 사례 | 결함 | 취약 → 수정 | Go | 숨겨진 오라클 |
| --- | --- | --- | --- | --- |
| Kite | K8s proxy 경로 탐색 → RBAC 우회 | `d74c979` → `08116ee` (v0.14.1) | 1.26 | `go test ./pkg/kube -run TestBuildProxyURL` |
| Pocket ID | OIDC refresh token 인가 우회 | `59fe481` → `978ac87` (v2.6.0) | 1.26 | `go test ./internal/service -run TestOidcServiceRefreshTokenAuthorizationState` |
| Vikunja | cross-tenant IDOR | `37c35c6` → `36cdc2c` (v2.4.0) | 1.26 | `go test ./pkg/webtests -run 'TestTaskBucketV2/task_from_a_foreign_project_is_forbidden'` |
| Arcane | environment token admin gate 우회 | `6006dbe` → `4fe4c7e` (backend v2.11.0) | 1.27 | `go test ./internal/auth -run TestAuthMiddleware` |

네 수정 테스트는 취약판에서 컴파일되고 실패하며 수정판에서 통과함을 확인했다. Vikunja는 테스트용 `frontend/dist/index.html` 자리표시자가 필요하고, Arcane은 `backend/`에서 `../types`·`../cli` replace 경로가 유지돼야 한다.

## 추출

`extract_units`는 함수와 직접 호출/피호출을 묶은 bundle을 만든다. `extract_routes`는 Gin/Echo/Huma 라우트 등록, 그룹 미들웨어 체인, 핸들러, 직접 호출 결정 함수를 묶은 route 단위를 만든다.

```bash
# source root는 취약 리비전의 소스 트리
docker run --rm \
  -v "$PWD/experiments/logic-ranker/extract_routes:/extract:ro" \
  -v "$SRC:/src:ro" -v "$OUT:/out" golang:1.26 \
  /extract/extract -root /src -out /out
```

`extract_units`는 `-packages`로 범위를 지정한다. 예: Kite `pkg/kube,pkg/auth,pkg/middleware,pkg/rbac,pkg/proxy`.

## 채점

`score.py`는 `.env`의 `TYPESAFE_API_KEY`를 읽고 `jev-1.14.0`으로 Noul 점수를 기록한다.

```bash
mkdir -p ~/sift-runs/logic-ranker/kite
cp /tmp/routes/kite/routes.jsonl ~/sift-runs/logic-ranker/kite/
python3 experiments/logic-ranker/score.py --kind routes --data-root ~/sift-runs/logic-ranker
python3 experiments/logic-ranker/summarize.py --kind routes --data-root ~/sift-runs/logic-ranker
```

출력은 `<data-root>/<project>/routes-scores.jsonl`이다. `--kind units`는 함수 bundle 점수를 채점한다.

## Stage 1 결과

라우트 단위 742개, Jev 1.14.0, 1,066만 입력 토큰, 약 **$0.45**. 함수 bundle 2,115개까지 포함한 총 Jev 비용은 약 **$1.67**이었다.

| 사례 | 대상 라우트 | Jev 순위 | 길이 기준 |
| --- | --- | ---: | ---: |
| Kite | `GET /namespaces/:namespace/:kind/:name/proxy/*path` | **1/130** (0.8%) | 103/130 (79.2%) |
| Pocket ID | `POST /oidc/token` | **2/110** (1.8%) | 80/110 (72.7%) |
| Vikunja | `PUT /projects/{project}/views/{view}/buckets/{bucket}/tasks` | **28/355** (7.9%) | 228/355 (64.2%) |
| Arcane | `GET /debug/pprof/` | 18/147 (12.2%) | 38/147 (25.9%) |

- 네 사례 모두 Jev top 13% 안에 들었다.
- Kite·Pocket ID는 top 2%다.
- 수정 함수 자체는 낮게 순위가 매겨졌다. 결정 경로 entry/route가 더 좋은 단위다.
- Arcane은 pprof 라우트 묶음도 0.21에 그쳤고 최고 pprof 라우트는 16/147(10.9%)였다. 미들웨어 체인은 포함됐지만 개선 여지가 있다.

이 결과는 **ceiling test**다. 사례별 불변식 질문을 미리 넣었고, 프로젝트당 알려진 버그가 하나다. End-to-end 효율을 증명하지 않는다.

## E2E

Kite 파일럿 harness와 결과는 [`e2e/`](e2e/README.md)에 있다. 순정 $1.436, Jev ranker $1.373(Jev $0.0245 포함), 둘 다 reproduced. Kite는 ceiling case라 작은 차이만 났다.

## 다음

1. Pocket ID·Vikunja end-to-end, Arcane은 대조군
2. `routes.jsonl` 자동 생성과 질문 템플릿 사전 고정
3. 감사에서 workspace 내부 상대 경로와 실제 경계 이탈 구분

원자료와 stage 1 기록: `~/sift-runs/notes/2026-10-19-stage1-ranker.md`, `~/sift-runs/measurements/jev-ranker-stage1/`.
