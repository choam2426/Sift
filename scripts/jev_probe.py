#!/usr/bin/env python3
"""Jev spec probe: latency, calibration taste, input limits. Stdlib only."""
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env(path):
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                env[k.strip()] = v
    except FileNotFoundError:
        pass
    return env


env = load_env(os.path.join(ROOT, ".env"))
KEY = env.get("TYPESAFE_API_KEY") or os.environ.get("TYPESAFE_API_KEY")
MODEL = env.get("JEV_MODEL", "jev-latest")
API = "https://api.typesafe.ai/v1/systemone"
if not KEY:
    print("MISSING: TYPESAFE_API_KEY")
    sys.exit(1)

Q = {"has_auth_check": {"type": "noul", "instructions": (
    "Does this function perform an authorization check before mutating state?")}}


def jev(state, questions, timeout=120):
    body = json.dumps({"model": MODEL, "state": state, "questions": questions})
    req = urllib.request.Request(
        API, data=body.encode(),
        headers={"Authorization": "Bearer " + KEY,
                 "Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "ms": (time.monotonic() - t0) * 1000,
                    "status": r.status, "body": json.loads(r.read().decode())}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:300]
        except Exception:
            detail = ""
        return {"ok": False, "ms": (time.monotonic() - t0) * 1000,
                "status": e.code, "detail": detail}
    except Exception as e:  # timeout etc.
        return {"ok": False, "ms": (time.monotonic() - t0) * 1000,
                "status": "ERR", "detail": str(e)[:200]}


def score_of(res):
    try:
        return res["body"]["answers"]["has_auth_check"]["noul"]
    except Exception:
        return None


results = {"model": MODEL, "latency_ms": [], "calib": [], "limits": []}

# Phase 1: latency, N=10 identical calls
LAT_STATE = ("def update_project(user, project):\n"
             "    if user.id != project.owner_id and not user.is_admin:\n"
             "        raise Forbidden()\n"
             "    project.name = request.name\n"
             "    db.save(project)")
print("== latency (n=10) ==")
for _ in range(10):
    r = jev(LAT_STATE, Q)
    if r["ok"]:
        results["latency_ms"].append(round(r["ms"]))
        print(f"  ok {r['ms']:.0f}ms tokens={r['body'].get('usage')}")
    else:
        print(f"  FAIL {r['status']} {r.get('detail', '')}")
lat = results["latency_ms"]
if lat:
    print(f"  min={min(lat)} med={statistics.median(lat):.0f} "
          f"p95={sorted(lat)[int(len(lat)*0.95)]} max={max(lat)} (n={len(lat)})")

# Phase 2: calibration taste, 8 labeled cases
CASES = [
    (1, "explicit owner+admin check",
     "def update_project(user, project):\n    if user.id != project.owner_id and not user.is_admin:\n        raise Forbidden()\n    db.save(project)"),
    (1, "decorator auth",
     "@require_auth\n@admin_only\ndef delete_project(project_id):\n    db.delete(Project, project_id)"),
    (1, "tenant match check",
     "def move_file(user, f, dst):\n    if user.tenant_id != f.tenant_id:\n        raise Forbidden()\n    f.folder = dst\n    db.save(f)"),
    (1, "early return guard",
     "def refund(order, actor):\n    if not actor.can('refund', order):\n        return denied()\n    order.status = 'refunded'\n    db.save(order)"),
    (0, "no check at all",
     "def update_project(project_id):\n    p = db.load(Project, project_id)\n    p.name = request.name\n    db.save(p)"),
    (0, "todo promises future check",
     "def delete_user(uid):\n    # TODO: add permission check later\n    db.delete(User, uid)"),
    (0, "login check only, mutates any object",
     "def set_role(req):\n    if not req.user.is_logged_in:\n        raise Unauthorized()\n    target = db.load(User, req.target_id)\n    target.role = req.role\n    db.save(target)"),
    (0, "check after mutation (too late)",
     "def rename(p, name):\n    p.name = name\n    db.save(p)\n    if not current_user.is_admin:\n        log('non-admin renamed')"),
]
print("== calibration (8 cases, thresh=0.5) ==")
correct = 0
for label, name, code in CASES:
    r = jev(code, Q)
    s = score_of(r)
    pred = 1 if (s is not None and s >= 0.5) else 0
    ok = "OK " if (r["ok"] and pred == label) else "MISS"
    if r["ok"] and pred == label:
        correct += 1
    results["calib"].append({"case": name, "label": label, "score": s})
    print(f"  {ok} label={label} score={s} :: {name}")
print(f"  accuracy={correct}/{len(CASES)}")

# Phase 3: input limits, signal buried at end
FILLER = ("def get_item(i):\n    return db.load(Item, i)\n\n")
SIGNAL = ("def wipe_tenant(tenant_id):\n    t = db.load(Tenant, tenant_id)\n"
          "    db.delete_all(t.records)\n")
print("== limits (signal at end, expect score~0 for no-check) ==")
for size in (2000, 10000, 40000, 100000):
    n = max(1, size // len(FILLER))
    state = FILLER * n + SIGNAL
    r = jev(state, Q, timeout=180)
    s = score_of(r)
    results["limits"].append({"chars": len(state), "status": r["status"],
                              "ms": round(r["ms"]), "score": s})
    print(f"  chars={len(state)} status={r['status']} "
          f"ms={r['ms']:.0f} score={s}")

with open("/tmp/jev_probe_report.json", "w") as f:
    json.dump(results, f, indent=1)
print("report: /tmp/jev_probe_report.json")
