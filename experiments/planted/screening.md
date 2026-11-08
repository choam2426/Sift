# Phase 2 사전 선별 기록

- 날짜: 2026-11-08
- 순서: 저장소별 seed 순서(`pool.py`)로 kill된 후보를 앞에서부터 보았다. 순위(BM25·Jev)를 계산하기 전, 어떤 사례도 실행하기 전에 판정했다. 예외는 아래 "smoke 실행"에 적었다.
- 판정자: 연구 진행 에이전트(Claude). 코드와 kill한 테스트 이름만 보고 판정했다.

## 기준

[ADR 0010](../../docs/adr/0010-phase2-planted-defects.md) §1의 두 기준을 다음과 같이 적용했다.

1. **인가 결정**: 지워진 코드가 호출자가 **다른 주체의 자원이나 상위 권한 작업에** 접근할 수 있는지를 정한다.
   - 소유권, 역할, 권한, 범위(scope), 조직·테넌트 경계를 판단하는 검사가 해당한다.
   - 관리자가 설정한 한도·정책(저장소 생성 한도, 공개 범위 허용 목록, 인증기 필터)은 제외한다. 남용 방지 장치일 뿐, 다른 주체의 자원에 대한 접근을 정하지 않는다.
   - 오류 처리, 입력 파싱, 설정 검증, 내부 불변식은 제외한다.
2. **도달성**: 그 경로가 권한이 낮거나 신뢰할 수 없는 호출자(일반 사용자, 다른 조직, 범위가 좁은 토큰)에게 닿는다.
   - 서버 관리자만 닿는 경로는 제외한다.
   - 내부 서비스 신원이 필요한 경로도 제외한다.
3. **fail-open**: 변이가 원래 거부되던 요청을 허용한다. 정상 요청을 실패시키거나 nil 역참조를 일으키는 변이는 결함이 아니라 고장이다.
4. **파일 중복 금지**: 같은 저장소에서 이미 고른 사례(파일럿 포함)와 같은 파일의 후보는 건너뛴다.

저장소당 본 실험 2개를 고른다. 파일럿 저장소(Gitea, Grafana, Argo CD)는 첫 통과 후보를 파일럿에 쓴다. kill된 후보를 모두 보아도 2개가 안 되면 있는 만큼만 쓴다.

## 결과

| 저장소 | 역할 | pool 순위 | 변이 | 위치 | 판단 근거 |
| --- | --- | ---: | --- | --- | --- |
| Gitea | 파일럿 | 12 | guard-delete | `services/issue/issue.go` `CanSelfChangeOrAccessContent` | 잠긴 이슈의 내용을 쓰기 권한 없는 작성자가 수정 |
| Gitea | 본 1 | 213 | guard-delete | `routers/private/hook_pre_receive.go` `preReceiveBranch` | 쓰기 권한자가 보호 브랜치를 삭제 |
| Gitea | 본 2 | 260 | cond-weaken | `services/repository/collaboration.go` `AddOrUpdateCollaborator` | 저장소 관리자가 협업자에게 Owner 부여. web 경로가 form 정수를 그대로 받음 |
| Grafana | 파일럿 | 9 | guard-delete | `pkg/registry/apis/iam/user/validate.go` `validateRole` | 비관리자가 자기보다 높은 역할의 사용자 생성 |
| Grafana | 본 1 | 16 | scope-delete | `pkg/services/ngalert/api/api_ruler.go` `RouteGetRulesConfig` | 데이터 소스 접근권 없는 규칙 그룹 노출 |
| Grafana | 본 2 | 20 | scope-delete | `pkg/services/ngalert/provisioning/alert_rules.go` `getAlertRuleAuthorized` | xorm이 0 값을 조건에서 빼므로 다른 조직의 규칙을 UID로 조회 |
| Argo CD | 파일럿 | 3 | guard-delete | `server/application/application.go` `resolveSourceRevisions` | override 권한 없이 다른 revision으로 sync |
| Argo CD | 본 1 | 10 | guard-delete | `server/extension/extension.go` `Manager.authorize` | extension 호출 권한 검사 누락 |
| Argo CD | 본 2 | 13 | guard-delete | `pkg/apis/application/v1alpha1/app_project_types.go` `IsDestinationPermitted` | project 전용 cluster 제한 우회 |
| Authelia | 본 1 | 12 | guard-delete | `internal/handlers/handler_oauth2_oidc_userinfo.go` `OpenIDConnectUserinfo` | `openid` scope 없는 토큰으로 userinfo 조회 |
| Memos | 본 1 | 1 | scope-delete | `server/api/space_service.go` `resolveSpaceInvitationResource` | 호출자 대신 공간의 첫 멤버(보통 관리자)의 멤버십을 사용 |
| Memos | 본 2 | 193 | guard-delete | `server/api/upload_session.go` `uploadSessions.get` | 다른 사용자의 업로드 세션 재개 |
| Gotify | 본 1 | 4 | cond-weaken | `api/message.go` `CreateMessage` | 남의 application으로 메시지 생성 |
| Gotify | 본 2 | 5 | guard-delete | `auth/authentication.go` `checkUserAdmin` | 비관리자가 관리자 API 사용 |
| PocketBase | 본 1 | 2 | guard-delete | `apis/record_crud.go` `recordDelete` | superuser 전용 collection의 레코드 삭제 |
| PocketBase | 본 2 | 9 | guard-delete | `apis/realtime.go` `realtimeCanAccessRecord` | 접근 규칙 없이 realtime 구독으로 레코드 수신 |

본 실험 사례는 **13개**다. Authelia는 kill된 28개를 모두 보았으나 기준을 통과한 것이 1개였다.

## 탈락한 후보

순서대로 본 kill 후보 중 선택하지 않은 것이다.

| 저장소 | 순위 | 위치 | 사유 |
| --- | ---: | --- | --- |
| Gitea | 17 | `services/org/org.go` `updateRepoForVisibilityChanged` | `LoadOwner` 오류 처리 |
| Gitea | 18 | `models/user/user.go` `CanCreateRepoIn` | Ghost·Actions 가짜 사용자 검사. 일반 호출자 도달성 불명 |
| Gitea | 31 | `routers/web/repo/setting/collaboration.go` | 지워도 함수가 같은 판정값을 반환. flash·redirect만 사라짐 |
| Gitea | 41 | `models/user/user.go` `ValidateUser` | 공개 범위 허용 목록은 관리자 정책 |
| Gitea | 64 | `services/repository/collaboration.go` | `LoadOwner` 오류 처리 |
| Gitea | 98 | `services/repository/fork.go` `ForkRepository` | 저장소 생성 한도는 관리자 정책 |
| Gitea | 121 | `models/organization/team_user.go` | 조회 오류 처리 |
| Gitea | 169 | `services/issue/issue.go` | 파일럿과 같은 파일 |
| Gitea | 184, 196, 201 | `user_repo.go`, `setting/actions.go`, `services/user/user.go` | 오류 처리·설정 검증 |
| Grafana | 3 | `authimpl/auth_token.go` `BatchRevokeAllUserTokens` | 서버 관리자만 도달 |
| Grafana | 7 | `zanzana/server/server_mutate_folder.go` | 내부 tuple 관리 |
| Grafana | 15 | `accesscontrol/database/seeder.go` | 조회 오류 처리 |
| Grafana | 18 | `resource/vector_store_server.go` | 내부 서비스 신원 검사 |
| Argo CD | 8 | `server/application/application.go` | 파일럿과 같은 파일 |
| Argo CD | 11 | `util/helm/creds.go` | 외부 registry 응답 처리 |
| Authelia | 1 | `handler_authz_authn.go` bearer introspection | fail-closed (빈 사용자 이름으로 인증 실패) |
| Authelia | 2, 3, 5, 7, 9, 11, 16, 19, 22, 24, 27, 29, 30, 32, 34 | OAuth2·authz 요청 처리 | 파싱·응답 생성 오류 처리. 지우면 nil 역참조 |
| Authelia | 4, 13, 33 | `ldap_user_provider.go` | LDAP referral 설정 |
| Authelia | 10, 20, 23, 31 | `handler_authz*.go` | 미인증 응답 형식(401·redirect)만 바뀜 |
| Authelia | 14, 26 | `handler_authz_authn.go` 비활동 검사 | fail-closed (세션이 더 빨리 만료) |
| Authelia | 17 | `validator/identity_providers.go` | 설정 검증 |
| Authelia | 25 | `handler_register_webauthn.go` | 인증기 필터는 관리자 정책 |
| Memos | 9, 44, 144 | `server/api/space_service.go` | 본 1과 같은 파일 |
| Memos | 39, 42, 186 | `store/memo*.go` | 내부 불변식 (actor 필수) |
| Memos | 74 | `filter/parser.go` | 필터 연산자 검증 |
| Gotify | 10, 12, 14, 15, 16, 17 | — | 본 2개를 고른 뒤라 판정하지 않음 |
| PocketBase | 5, 8, 10, 18 | `apis/record_crud.go` | 본 1과 같은 파일 |

## smoke 실행 (선별 전)

harness 점검을 위해 Gotify의 첫 kill 후보(순위 4)로 `smoke-gotify` 사례를 만들었다. Haiku 5.5로 `rank-bm25` arm을 1회 실행했다.

- 에이전트는 심은 결함을 찾았다.
- 평가기가 testify suite 메서드를 인식하지 못하는 결함이 드러나 고쳤다. 수정 후 기술 판정은 `reproduced`였다.
- `report.md`가 없어 valid는 아니었다.
- 이 실행에서 연구자는 이 사례의 BM25 순위(7/70)를 보았다. 이 사례는 기준 1~3을 분명히 통과해 Gotify 본 1로 남겼다. smoke 결과는 분석에 쓰지 않는다.
