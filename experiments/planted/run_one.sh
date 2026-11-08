#!/bin/sh
# Run one (case, arm, rep) to completion, redoing runs aborted by a session limit.
#   run_one.sh <group> <case> <arm> <rep> [scope] [cap]
set -u
here=$(cd "$(dirname "$0")" && pwd)
group=$1 case=$2 arm=$3 rep=$4 scope=${5:-repo} cap=${6:-30}
root=~/sift-runs/planted/runs/$group
ws=$root/$case-$arm-r$rep
[ -e "$ws/control/done" ] && { echo "done already: $ws"; exit 0; }
for attempt in 1 2 3 4 5 6; do
  if [ -e "$ws" ]; then
    python3 "$here/harness.py" teardown --workspace "$ws" >/dev/null 2>&1
    mkdir -p "$root/aborted" && mv "$ws" "$root/aborted/$(basename "$ws")-$(date +%Y%m%dT%H%M%S)"
  fi
  python3 "$here/harness.py" prepare --case "$case" --arm "$arm" --workspace "$ws" --scope "$scope" || exit 1
  python3 "$here/harness.py" run --workspace "$ws" --max-budget-usd "$cap"
  rc=$?
  python3 "$here/harness.py" teardown --workspace "$ws"
  if [ $rc -ne 3 ]; then touch "$ws/control/done"; exit $rc; fi
  echo "infra abort (attempt $attempt); waiting for the limit to reset"
  python3 "$here/wait_reset.py" "$ws"
done
exit 3
