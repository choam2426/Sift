#!/usr/bin/env python3
"""PROTOTYPE experiment: noul vs 3-way choice vs decomposed questions.
Question: does better question design fix near-miss judgments (e.g. 0.48)?
Run: python3 scripts/jev_ablation.py. Stdlib only."""
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = {}
try:
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
except FileNotFoundError:
    pass
KEY = env.get("TYPESAFE_API_KEY") or os.environ.get("TYPESAFE_API_KEY")
MODEL = env.get("JEV_MODEL", "jev-latest")
API = "https://api.typesafe.ai/v1/systemone"
if not KEY:
    print("MISSING: TYPESAFE_API_KEY")
    sys.exit(1)


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
                    "body": json.loads(r.read().decode())}
    except Exception as e:
        return {"ok": False, "ms": (time.monotonic() - t0) * 1000,
                "detail": str(e)[:200]}


Q_NOUL = {"v": {"type": "noul", "instructions": (
    "Does this function perform an authorization check before mutating state?")}}
Q_CHOICE = {"v": {"type": "choice",
    "instructions": "What kind of authorization does this function perform before mutating state?",
    "criteria": {
        "explicit": "Compares actor identity/role/tenant against the target object before mutation, and blocks on failure.",
        "auth_only": "Checks login only, or checks after mutation, or the check does not gate the mutation.",
        "absent": "No authorization of any kind."}}}
Q_DECOMP = {
    "compares": {"type": "noul", "instructions": (
        "Does the code compare the actor's identity, role, or tenant against the target object?")},
    "before": {"type": "noul", "instructions": (
        "Does any such check happen before state is mutated?")},
    "blocks": {"type": "noul", "instructions": (
        "Does a failed check prevent the mutation (raise, return, or deny)?")}}

# (label, name, code) — 12 pos / 12 neg
CASES = [
    (1, "explicit owner check",
     "def update_project(user, project):\n    if user.id != project.owner_id:\n        raise Forbidden()\n    db.save(project)"),
    (1, "admin role check",
     "def purge_logs(actor):\n    if actor.role != 'admin':\n        raise Forbidden()\n    db.delete_all(Logs)"),
    (1, "decorator auth",
     "@require_auth\n@admin_only\ndef delete_project(pid):\n    db.delete(Project, pid)"),
    (1, "tenant match",
     "def move_file(user, f, dst):\n    if user.tenant_id != f.tenant_id:\n        raise Forbidden()\n    f.folder = dst\n    db.save(f)"),
    (1, "capability call",
     "def refund(order, actor):\n    if not actor.can('refund', order):\n        return denied()\n    order.status = 'refunded'\n    db.save(order)"),
    (1, "helper require_owner",
     "def rename(user, doc, name):\n    require_owner(user, doc)\n    doc.name = name\n    db.save(doc)"),
    (1, "policy object",
     "def close_acct(actor, acct):\n    if not policy.allow(actor, 'close', acct):\n        raise Forbidden()\n    acct.status = 'closed'\n    db.save(acct)"),
    (1, "requires_role decorator",
     "@requires_role('billing')\ndef issue_refund(order_id):\n    create_refund(order_id)"),
    (1, "multi-condition",
     "def edit(user, doc):\n    if user.id != doc.owner_id and user.id not in doc.editors:\n        raise Forbidden()\n    doc.body = request.body\n    db.save(doc)"),
    (1, "guard clause 403",
     "def ban(mod, target):\n    if not mod.is_moderator:\n        return 403\n    target.banned = True\n    db.save(target)"),
    (1, "match role guard",
     "def wipe(mod, room):\n    match mod.role:\n        case 'admin':\n            room.msgs = []\n            db.save(room)\n        case _:\n            raise Forbidden()"),
    (1, "verify in try",
     "def transfer(user, t):\n    try:\n        verify_access(user, t)\n    except AuthError:\n        raise Forbidden()\n    execute(t)"),
    (0, "no check",
     "def update_project(pid):\n    p = db.load(Project, pid)\n    p.name = request.name\n    db.save(p)"),
    (0, "todo comment",
     "def delete_user(uid):\n    # TODO: add permission check later\n    db.delete(User, uid)"),
    (0, "login only",
     "def set_role(req):\n    if not req.user.is_logged_in:\n        raise Unauthorized()\n    target = db.load(User, req.target_id)\n    target.role = req.role\n    db.save(target)"),
    (0, "check after mutation",
     "def rename(p, name):\n    p.name = name\n    db.save(p)\n    if not current_user.is_admin:\n        log('non-admin renamed')"),
    (0, "commented-out check",
     "def delete_doc(user, doc):\n    # if user.id != doc.owner_id: raise Forbidden()\n    db.delete(doc)"),
    (0, "log only",
     "def refund(order, actor):\n    if actor.id != order.user_id:\n        log('suspicious refund')\n    order.status = 'refunded'\n    db.save(order)"),
    (0, "check does not gate",
     "def wipe(actor):\n    if actor.role == 'admin':\n        log('admin wipe')\n    db.delete_all(Records)"),
    (0, "trusts client role",
     "def promote(req):\n    if req.role == 'admin':\n        target = db.load(User, req.target_id)\n        target.role = 'admin'\n        db.save(target)"),
    (0, "test bypass",
     "def delete_all_data(user):\n    if ENV == 'test':\n        db.delete_all(Data)\n        return\n    require_admin(user)\n    db.delete_all(Data)"),
    (0, "existence not permission",
     "def get_salary(user, target_id):\n    if user is None:\n        raise Unauthorized()\n    return db.load(User, target_id).salary"),
    (0, "frontend-only comment",
     "def set_price(pid, price):\n    # UI hides this button from non-admins\n    db.load(Product, pid).price = price\n    db.save()"),
    (0, "swallowed auth failure",
     "def migrate(user):\n    try:\n        verify_admin(user)\n    except AuthError:\n        pass\n    run_migration()"),
]

print(f"cases={len(CASES)} model={MODEL}")
print(f"{'case':28s} {'lbl':3s} {'noul':>6s} {'choice':>9s} {'decomp':>14s}")
tot = {"noul": 0, "choice": 0, "decomp": 0}
detail = []
for label, name, code in CASES:
    rn = jev(code, Q_NOUL)
    rc = jev(code, Q_CHOICE)
    rd = jev(code, Q_DECOMP)
    try:
        sn = rn["body"]["answers"]["v"]["noul"]
        pn = 1 if sn >= 0.5 else 0
    except Exception:
        sn, pn = None, -1
    try:
        cc = rc["body"]["answers"]["v"]["choice"]
        pc = 1 if cc == "explicit" else 0
    except Exception:
        cc, pc = "?", -1
    try:
        a = rd["body"]["answers"]
        s1, s2, s3 = a["compares"]["noul"], a["before"]["noul"], a["blocks"]["noul"]
        pd = 1 if min(s1, s2, s3) >= 0.5 else 0
        ds = f"{s1:.2f}/{s2:.2f}/{s3:.2f}"
    except Exception:
        ds, pd = "?", -1
    for k, p in (("noul", pn), ("choice", pc), ("decomp", pd)):
        if p == label:
            tot[k] += 1
    detail.append({"case": name, "label": label, "noul": sn, "choice": cc,
                   "decomp": ds, "pred": [pn, pc, pd]})
    sn_s = f"{sn:.2f}" if sn is not None else "ERR"
    print(f"{name:28s} {label:<3d} {sn_s:>6s} {cc:>9s} {ds:>14s}")

n = len(CASES)
print(f"\naccuracy: noul={tot['noul']}/{n} choice={tot['choice']}/{n} "
      f"decomp(AND)={tot['decomp']}/{n}")
print("\nmisses:")
for d in detail:
    marks = []
    for design, p in zip(("noul", "choice", "decomp"), d["pred"]):
        if p != d["label"]:
            marks.append(design)
    if marks:
        print(f"  {d['case']}: label={d['label']} missed-by={','.join(marks)} "
              f"(noul={d['noul']} choice={d['choice']} decomp={d['decomp']})")
json.dump({"tot": tot, "n": n, "detail": detail},
          open("/tmp/jev_ablation_report.json", "w"), indent=1)
print("report: /tmp/jev_ablation_report.json")
