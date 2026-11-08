#!/usr/bin/env python3
"""Sleep until the session limit named in the last run.json resets (plus a margin)."""
import datetime, glob, json, re, sys, time

ws = sys.argv[1]
text = ''
for path in sorted(glob.glob(ws + '/control/runs/*/run.json'))[-1:]:
    text = json.load(open(path)).get('infra_abort') or ''
m = re.search(r'resets (\d{1,2})(?::(\d{2}))?\s*(am|pm)', text, re.I)
now = datetime.datetime.now()
if m:
    hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == 'pm' else 0)
    target = now.replace(hour=hour, minute=int(m.group(2) or 0), second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    wait = (target - now).total_seconds() + 300
else:
    wait = 1800
print(f'sleeping {wait / 60:.0f} min (reset text: {text[:80]!r})', flush=True)
time.sleep(wait)
