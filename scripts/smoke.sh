#!/usr/bin/env bash
# smoke.sh — key check + minimal Jev / frontier calls.
# Never prints secret values. Exits non-zero on any failure.
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then
  # Parse KEY=VALUE lines WITHOUT executing them (values may contain | etc.)
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue;; esac
    case "$line" in *=*) :;; *) continue;; esac
    key=${line%%=*}; val=${line#*=}
    first=${val%"${val#?}"}; last=${val#"${val%?}"}
    if [ "$first" = '"' ] && [ "$last" = '"' ]; then val=${val#\"}; val=${val%\"}; fi
    if [ "$first" = "'" ] && [ "$last" = "'" ]; then val=${val#\'}; val=${val%\'}; fi
    export "$key=$val"
  done < "$ROOT/.env"
fi

fail=0
need() {
  if [ -z "${!1:-}" ]; then echo "MISSING: $1"; fail=1;
  else echo "OK: $1 is set"; fi
}
need TYPESAFE_API_KEY
need MODEL_API_KEY
: "${FRONTIER_MODEL:=muse-spark-1.3-contributor}"
: "${FRONTIER_BASE_URL:=https://api.meta.ai/v1}"
echo "OK: FRONTIER_MODEL=$FRONTIER_MODEL"
echo "OK: FRONTIER_BASE_URL=$FRONTIER_BASE_URL"
[ "$fail" -ne 0 ] && exit 1

call() { # $1=name $2=url $3=bearer_var $4=json_file
  local code body
  code=$(curl -s --max-time 90 -o /tmp/smoke_body.txt -w "%{http_code}" \
    "$2" -H "Authorization: Bearer ${!3}" -H "Content-Type: application/json" \
    --data-binary "@$4") || code="CURL_FAIL"
  body=$(head -c 1200 /tmp/smoke_body.txt 2>/dev/null)
  echo "--- $1: HTTP $code ---"
  echo "$body"
  echo
  case "$code" in 2*) return 0;; *) return 1;; esac
}

# 1. Jev: one noul triage question over a tiny code state
cat > /tmp/smoke_jev.json <<'JSON'
{"model": "jev-latest",
 "state": "def update_project(user, project):\n    if user.id != project.owner_id and not user.is_admin:\n        raise Forbidden()\n    project.name = request.name\n    db.save(project)",
 "questions": {"has_auth_check": {"type": "noul", "instructions": "Does this function perform an authorization check before mutating state?"}}}
JSON
call "Jev" "https://api.typesafe.ai/v1/systemone" TYPESAFE_API_KEY /tmp/smoke_jev.json || fail=1

# 2. Frontier: minimal chat completion
cat > /tmp/smoke_frontier.json <<JSON
{"model": "$FRONTIER_MODEL",
 "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
 "max_tokens": 16}
JSON
call "Frontier" "$FRONTIER_BASE_URL/chat/completions" MODEL_API_KEY /tmp/smoke_frontier.json || fail=1

rm -f /tmp/smoke_body.txt /tmp/smoke_jev.json /tmp/smoke_frontier.json
[ "$fail" -eq 0 ] && echo "SMOKE: PASS" || echo "SMOKE: FAIL"
exit "$fail"
