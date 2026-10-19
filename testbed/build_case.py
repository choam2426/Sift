#!/usr/bin/env python3
"""Build and verify one measurement case from pinned sources.

    python3 build_case.py build <recipe.json> --out <bundle-dir>
    python3 build_case.py evaluate <bundle-dir>/case.json --input <file> [--out <dir>]

A recipe pins the project repository, vulnerable and fixed commits, the
OSS-Fuzz project revision, the base-builder image digest, the harness, and the
public reference testcase. The build command produces a bundle:

    case.json      local image refs, expected crash, reference hash
    fix.tar        fixed image, removed from Docker after the build
    reference.bin  reference testcase (control material)
    build.json     provenance, commands, logs, image IDs, verification results
    logs/          full build and run logs

The vulnerable image is built from a git archive (no history) and contains no
reference input. The fixed image is saved to fix.tar and removed from Docker, so
it is not reachable through the Docker socket until evaluate loads it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CMD_TIMEOUT_S = 10
DOCKER_TIMEOUT_S = 120


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def run(cmd: list[str], *, cwd: Path | None = None, timeout: float | None = None, check: bool = True,
        env: dict | None = None, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout, env=env, input=input_bytes)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} failed ({proc.returncode}): "
                           f"{proc.stderr.decode(errors='replace')[-600:]}")
    return proc


def docker(*args: str, timeout: float | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return run(["docker", *args], timeout=timeout, check=check)


def image_id(ref: str) -> str | None:
    proc = docker("image", "inspect", "--format", "{{.Id}}", ref, check=False)
    return proc.stdout.decode().strip() or None if proc.returncode == 0 else None


def load_recipe(path: Path) -> dict:
    recipe = json.loads(path.read_text(encoding="utf-8"))
    required = ("id", "project", "source_dir", "platform", "repo", "vuln_commit", "fix_commit",
                "oss_fuzz_repo", "oss_fuzz_commit", "oss_fuzz_project", "base_builder",
                "fuzzing_language", "sanitizer", "harness", "build_script", "reference_url",
                "reference_sha256", "expected_crash", "entry_point")
    missing = [k for k in required if k not in recipe]
    if missing:
        raise ValueError(f"recipe is missing: {', '.join(missing)}")
    if not recipe["source_dir"].startswith("/") or not recipe["source_dir"].rstrip("/").endswith("/" + recipe["project"]):
        raise ValueError("source_dir must be absolute and end with the project name")
    expected = recipe["expected_crash"]
    for key in ("type", "file", "line", "function"):
        if key not in expected:
            raise ValueError(f"expected_crash is missing {key}")
    return recipe


def content_key(recipe: dict, build_script: str) -> str:
    pinned = {k: recipe[k] for k in ("repo", "vuln_commit", "fix_commit", "oss_fuzz_repo", "oss_fuzz_commit",
                                     "oss_fuzz_project", "base_builder", "fuzzing_language", "sanitizer",
                                     "harness", "source_dir", "platform")}
    pinned["build_script_sha256"] = sha256_text(build_script)
    return sha256_text(json.dumps(pinned, sort_keys=True))[:12]


def fetch_source(repo: str, commit: str, dest: Path, work: Path) -> None:
    """Archive one commit without .git, fetching it if the local clone lacks it."""
    clone = work / "repo"
    if not (clone / ".git").exists():
        run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", repo, str(clone)], timeout=1800)
    if run(["git", "-C", str(clone), "cat-file", "-e", f"{commit}^{{commit}}"], check=False).returncode != 0:
        run(["git", "-C", str(clone), "fetch", "-q", "origin", commit], timeout=1800)
    dest.mkdir(parents=True, exist_ok=False)
    archive = run(["git", "-C", str(clone), "archive", commit], timeout=600)
    run(["tar", "-x", "-C", str(dest)], input_bytes=archive.stdout, timeout=600)


def oss_fuzz_recipe(recipe: dict, work: Path) -> dict:
    """Fetch the pinned OSS-Fuzz project recipe and return its file hashes."""
    clone = work / "oss-fuzz"
    if not (clone / ".git").exists():
        run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", recipe["oss_fuzz_repo"], str(clone)],
            timeout=1800)
    commit = recipe["oss_fuzz_commit"]
    if run(["git", "-C", str(clone), "cat-file", "-e", f"{commit}^{{commit}}"], check=False).returncode != 0:
        run(["git", "-C", str(clone), "fetch", "-q", "origin", commit], timeout=1800)
    project_dir = f"projects/{recipe['oss_fuzz_project']}"
    files = {}
    for name in ("Dockerfile", "build.sh", "project.yaml"):
        proc = run(["git", "-C", str(clone), "show", f"{commit}:{project_dir}/{name}"], check=False, timeout=120)
        if proc.returncode == 0:
            files[name] = sha256_text(proc.stdout.decode(errors="replace"))
    return files


def dockerfile(recipe: dict) -> str:
    return "\n".join([
        f"FROM {recipe['base_builder']}",
        f"ENV FUZZING_LANGUAGE={recipe['fuzzing_language']} FUZZING_ENGINE=libfuzzer "
        f"SANITIZER={recipe['sanitizer']} ARCHITECTURE=x86_64",
        f"COPY src {recipe['source_dir']}",
        "COPY build.sh /src/build.sh",
        f"WORKDIR {recipe['source_dir']}",
        "RUN compile",
        "",
    ])


def build_one(recipe: dict, source: Path, build_script: Path, tag: str, mode: str, log_path: Path) -> str:
    context = log_path.parent / f"context-{mode}"
    context.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source, context / "src")
    shutil.copy(build_script, context / "build.sh")
    (context / "Dockerfile").write_text(dockerfile(recipe), encoding="utf-8")
    proc = docker("build", "--platform", recipe["platform"], "--network", "none", "--pull=false",
                  "-t", tag, str(context), timeout=3600, check=False)
    log_path.write_bytes(proc.stdout + proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"build failed for {tag}; see {log_path}")
    ident = image_id(tag)
    if not ident:
        raise RuntimeError(f"built image {tag} is missing")
    return ident


def run_input(recipe: dict, image: str, input_path: Path) -> dict:
    inner = " ".join([recipe["harness"], "/tmp/poc"])
    started = time.monotonic()
    proc = docker("run", "--rm", "--network", "none", "--platform", recipe["platform"],
                  "-v", f"{input_path.resolve()}:/tmp/poc:ro", image,
                  "/bin/bash", "-c", f"timeout -s SIGKILL {CMD_TIMEOUT_S} {inner} 2>&1",
                  timeout=DOCKER_TIMEOUT_S, check=False)
    output = proc.stdout.decode(errors="replace")
    return {"exit": proc.returncode, "seconds": round(time.monotonic() - started, 2),
            "executed": "Running: /tmp/poc" in output or "Executed /tmp/poc" in output, "output": output}


def matches_crash(output: str, expected: dict) -> bool:
    required = (str(expected["type"]), f"{expected['file']}:{expected['line']}", str(expected["function"]))
    return all(item in output for item in required)


def verify(recipe: dict, vuln_image: str, fix_image: str, reference: Path) -> dict:
    runs = {"vuln": [], "fix": []}
    for _ in range(2):
        runs["vuln"].append(run_input(recipe, vuln_image, reference))
    for _ in range(2):
        runs["fix"].append(run_input(recipe, fix_image, reference))
    vuln_ok = all(r["exit"] != 0 and r["executed"] and matches_crash(r["output"], recipe["expected_crash"])
                  for r in runs["vuln"])
    fix_ok = all(r["exit"] == 0 and r["executed"] for r in runs["fix"])
    return {"ok": vuln_ok and fix_ok, "vuln_ok": vuln_ok, "fix_ok": fix_ok, "runs": runs}


def toolchain_info(recipe: dict, image: str) -> dict:
    harness = f"/out/{Path(recipe['harness']).name}"
    proc = docker("run", "--rm", "--network", "none", "--platform", recipe["platform"], image, "bash", "-c",
                  f"sha256sum {harness} | cut -d' ' -f1; clang --version | head -1; cmake --version | head -1",
                  check=False, timeout=120)
    lines = proc.stdout.decode(errors="replace").splitlines()
    return {"harness_sha256": lines[0] if lines else None,
            "clang": lines[1] if len(lines) > 1 else None,
            "cmake": lines[2] if len(lines) > 2 else None}


def audit_vuln_image(recipe: dict, image: str) -> dict:
    project = recipe["source_dir"].rstrip("/")
    check = docker("run", "--rm", "--network", "none", "--platform", recipe["platform"], image, "bash", "-c",
                   f"test ! -e {project}/.git && test ! -e /tmp/poc && test -z \"$(find {project} -name .git -print -quit)\" "
                   f"&& echo CLEAN", check=False, timeout=120)
    text = check.stdout.decode(errors="replace")
    history = docker("history", "--no-trunc", "--format", "{{.CreatedBy}}", image, check=False)
    history_text = history.stdout.decode(errors="replace")
    leaks = [needle for needle in (recipe["reference_url"], recipe["reference_sha256"],
                                   recipe.get("notes", "")) if needle and needle in history_text]
    return {"clean": check.returncode == 0 and "CLEAN" in text,
            "git_or_reference_absent": "CLEAN" in text,
            "history_reference_leaks": leaks,
            "history_sha256": sha256_text(history_text)}


def cmd_build(args: argparse.Namespace) -> int:
    recipe_path = Path(args.recipe)
    recipe = load_recipe(recipe_path)
    bundle = Path(args.out).resolve()
    if bundle.exists() and any(bundle.iterdir()):
        print(f"FAIL bundle {bundle} exists and is not empty")
        return 1
    bundle.mkdir(parents=True, exist_ok=True)
    logs = bundle / "logs"
    logs.mkdir()
    work = Path(args.work).resolve() if args.work else bundle / "work"
    work.mkdir(parents=True, exist_ok=True)

    build_script = (recipe_path.parent / recipe["build_script"]).resolve()
    if not build_script.is_file():
        print(f"FAIL build script missing: {build_script}")
        return 1
    if image_id(recipe["base_builder"]) is None:
        print(f"     pulling {recipe['base_builder']} ...")
        docker("pull", "--platform", recipe["platform"], "-q", recipe["base_builder"], timeout=3600)
    script_text = build_script.read_text(encoding="utf-8")
    key = content_key(recipe, script_text)
    vuln_tag = f"sift-target-{key}:local"
    fix_tag = f"sift-fix-{key}:local"
    record = {"recipe": str(recipe_path.resolve()), "started_at": now(), "content_key": key,
              "builder_sha256": sha256_file(Path(__file__).resolve()),
              "pins": {k: recipe[k] for k in ("repo", "vuln_commit", "fix_commit", "oss_fuzz_repo",
                                               "oss_fuzz_commit", "oss_fuzz_project", "base_builder",
                                               "fuzzing_language", "sanitizer", "harness", "platform")},
              "build_script_sha256": sha256_text(script_text), "oss_fuzz_recipe_sha256": oss_fuzz_recipe(recipe, work)}

    print(f"recipe {recipe['id']} key={key}")
    for mode, commit in (("vuln", recipe["vuln_commit"]), ("fix", recipe["fix_commit"])):
        source = work / f"src-{mode}"
        if not source.exists():
            fetch_source(recipe["repo"], commit, source, work)
        print(f"ok   source {mode} {commit[:10]} ({sum(1 for p in source.rglob('*') if p.is_file())} files)")

    started = time.monotonic()
    record["images"] = {}
    record["images"]["vuln"] = {"tag": vuln_tag,
                                "id": build_one(recipe, work / "src-vuln", build_script, vuln_tag, "vuln",
                                                logs / "vuln-build.log")}
    record["images"]["fix"] = {"tag": fix_tag,
                               "id": build_one(recipe, work / "src-fix", build_script, fix_tag, "fix",
                                               logs / "fix-build.log")}
    record["build_seconds"] = round(time.monotonic() - started, 1)
    print(f"ok   built vuln and fix images in {record['build_seconds']}s")
    record["toolchain"] = toolchain_info(recipe, vuln_tag)
    print(f"ok   harness sha256={record['toolchain']['harness_sha256']} clang={record['toolchain']['clang']}")

    reference = bundle / "reference.bin"
    run(["curl", "-fsSL", "--max-time", "120", recipe["reference_url"], "-o", str(reference)], timeout=180)
    digest = sha256_file(reference)
    if digest != recipe["reference_sha256"]:
        print(f"FAIL reference sha256 {digest} != {recipe['reference_sha256']}")
        return 1
    print(f"ok   reference testcase {len(reference.read_bytes())} bytes sha256={digest[:12]}")

    verification = verify(recipe, vuln_tag, fix_tag, reference)
    record["verification"] = {k: v for k, v in verification.items() if k != "runs"}
    for mode in ("vuln", "fix"):
        for i, r in enumerate(verification["runs"][mode], 1):
            (logs / f"{mode}-run-{i}.log").write_text(r["output"], encoding="utf-8")
        record.setdefault("runs", {})[mode] = [
            {k: v for k, v in r.items() if k != "output"} for r in verification["runs"][mode]
        ]
    (logs / "reference-run-vuln.log").write_text(verification["runs"]["vuln"][0]["output"], encoding="utf-8")
    if not verification["ok"]:
        print("FAIL reference testcase did not verify: "
              f"vuln_ok={verification['vuln_ok']} fix_ok={verification['fix_ok']}")
        for mode in ("vuln", "fix"):
            r = verification["runs"][mode][0]
            print(f"     {mode}: exit={r['exit']} executed={r['executed']}")
            print("     " + (r["output"].strip().splitlines()[-1] if r["output"].strip() else ""))
        return 1
    print("ok   reference testcase crashes vulnerable and not fixed (2 runs each, signature matched)")

    audit = audit_vuln_image(recipe, vuln_tag)
    record["audit"] = audit
    if not audit["clean"] or audit["history_reference_leaks"]:
        print(f"FAIL image audit: {audit}")
        return 1
    print("ok   vulnerable image has no .git, no /tmp/poc, no reference in history")

    fix_tar = bundle / "fix.tar"
    started = time.monotonic()
    run(["docker", "save", "-o", str(fix_tar), fix_tag], timeout=3600)
    record["fix_archive"] = {"path": "fix.tar", "sha256": sha256_file(fix_tar),
                             "bytes": fix_tar.stat().st_size, "save_seconds": round(time.monotonic() - started, 1)}
    docker("image", "rm", "-f", fix_tag, check=False)
    if image_id(fix_tag):
        print("FAIL fixed image is still present after removal")
        return 1
    print(f"ok   fixed image saved to fix.tar and removed from Docker ({record['fix_archive']['bytes']} bytes)")

    case = {
        "id": recipe["id"], "project": recipe["project"], "source_dir": recipe["source_dir"],
        "platform": recipe["platform"],
        "images": {
            "vul": {"kind": "local", "tag": vuln_tag, "digest": record["images"]["vuln"]["id"]},
            "fix": {"kind": "local", "tag": fix_tag, "digest": record["images"]["fix"]["id"],
                    "archive": "fix.tar"},
        },
        "reference": {"path": "reference.bin", "sha256": digest, "bytes": len(reference.read_bytes())},
        "fix_archive": {"path": "fix.tar", "sha256": record["fix_archive"]["sha256"],
                        "bytes": record["fix_archive"]["bytes"]},
        "expected_crash": recipe["expected_crash"],
        "run_command": [recipe["harness"], "/tmp/poc"],
        "build_command": ["compile"],
        "entry_point": recipe["entry_point"],
        "build": {k: record[k] for k in ("content_key", "pins", "build_script_sha256",
                                          "oss_fuzz_recipe_sha256", "build_seconds")},
        "toolchain": record["toolchain"],
        "builder_sha256": record["builder_sha256"],
    }
    (bundle / "case.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    record["finished_at"] = now()
    (bundle / "build.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"ok   bundle ready: {bundle}")
    return 0


def load_case(path: Path) -> tuple[dict, Path]:
    case = json.loads(path.read_text(encoding="utf-8"))
    return case, path.resolve().parent


def cmd_evaluate(args: argparse.Namespace) -> int:
    case_path = Path(args.case)
    case, base = load_case(case_path)
    vuln = case["images"]["vul"]
    fix = case["images"]["fix"]
    if image_id(vuln["tag"]) != vuln["digest"]:
        print(f"FAIL vulnerable image {vuln['tag']} is missing or differs from its recorded ID")
        return 1
    if image_id(fix["tag"]):
        print(f"FAIL fixed image {fix['tag']} is already loaded; the bundle expects it to be absent")
        return 1
    archive = base / fix["archive"]
    if not archive.is_file():
        print(f"FAIL fixed archive missing: {archive}")
        return 1
    recorded = case.get("fix_archive", {}).get("sha256")
    if recorded and sha256_file(archive) != recorded:
        print("FAIL fixed archive hash differs from the case record")
        return 1
    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        print(f"FAIL input missing: {input_path}")
        return 1
    loaded = False
    try:
        run(["docker", "load", "-i", str(archive)], timeout=3600)
        loaded = True
        if image_id(fix["tag"]) != fix["digest"]:
            print(f"FAIL loaded fixed image ID differs from the recorded ID")
            return 1
        reference = base / case["reference"]["path"]
        if sha256_file(reference) != case["reference"]["sha256"]:
            print("FAIL reference testcase hash differs")
            return 1
        verification = verify({"harness": case["run_command"][0], "platform": case["platform"],
                               "expected_crash": case["expected_crash"]},
                              vuln["tag"], fix["tag"], input_path)
        record = {"case": case["id"], "input": str(input_path),
                  "input_sha256": sha256_file(input_path), "at": now(),
                  "vuln_image": vuln, "fix_image": fix, "verification": {
                      k: v for k, v in verification.items() if k != "runs"},
                  "runs": {m: [{k: v for k, v in r.items() if k != "output"} for r in rs]
                           for m, rs in verification["runs"].items()}}
        for mode in ("vuln", "fix"):
            for i, r in enumerate(verification["runs"][mode], 1):
                record.setdefault("outputs", {})[f"{mode}-{i}"] = r["output"][-4000:]
        print(f"verdict: {'reproduced' if verification['ok'] else 'rejected'}")
        if args.out:
            out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
            (out / f"eval-{time.strftime('%Y%m%dT%H%M%S')}.json").write_text(
                json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return 0 if verification["ok"] else 2
    finally:
        if loaded:
            docker("image", "rm", "-f", fix["tag"], check=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build"); p.add_argument("recipe"); p.add_argument("--out", required=True); p.add_argument("--work")
    p = sub.add_parser("evaluate"); p.add_argument("case"); p.add_argument("--input", required=True); p.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        return cmd_build(a) if a.cmd == "build" else cmd_evaluate(a)
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
