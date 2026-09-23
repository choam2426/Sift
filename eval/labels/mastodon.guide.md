# Mastodon 라벨 가이드 (P0)

> 대상: `labels/mastodon.review.jsonl` 50개 (순서 셔플됨).
> `labels/mastodon.labels.json`의 label(0/1) + reason 한 줄을 기입.
> 매니페스트(밴드)와 scores는 보지 말 것 (블라인드).

## Positive (1) — "분석가가 5분 이상 파고들 보안 결정 코드"

해당하면 1:

- 인가 판단: 누가 무엇을 할 수 있나 (role/permission 체크, policy predicate)
- 소유권/테넌트 비교: 행위자 vs 대상의 관계 확인
- 상태 전이 가드: 허용된 전이만 통과시키는 검사
- 민감 쓰기: 권한/가시성/신용정보를 바꾸는 실행 (체크 유무 불문 — 체크
  없는 민감 쓰기가 제일 중요한 positive)

## Negative (0) — 그 외 전부

## 예시 (샘플 밖 발췌)

Positive:

```ruby
# AccountModerationNotePolicy#destroy? — 역할+소유권 복합 판단 → 1
def destroy?
  owner? || (role.can?(:manage_reports) && role.overrides?(record.account.user_role))
end
# AccountModerationNotePolicy#owner? — 소유권 비교 → 1
def owner?
  record.account_id == current_account&.id
end
# AccountModerationNotePolicy#create? — 권한 predicate → 1
def create?
  role.can?(:manage_reports)
end
```

Negative:

```ruby
# QueryBuilder#initialize — 단순 대입 → 0
def initialize(query, account, options = {})
  @query = query
  @account = account
  @options = options
end
# QueryBuilder#must_not_clauses — 빈 배열 반환 → 0
def must_not_clauses
  []
end
```

## 경계 규칙

- 로그인 체크만 있고 객체별 인가 없음 → 0
- 변경 후 체크 (too late) → 0
- 주석/ TODO / 로그뿐 → 0
- `authorize`/`can?` 호출로 강제하는 컨트롤러 → 1
- 애매하면 1 쪽 (triage는 recall 담당. reason에 "borderline" 표기)
