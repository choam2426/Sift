"""Magma bench: scan a buggy tree, keep the agreed scope, optionally run stage 1, map labels to units."""
import argparse, asyncio, difflib, json, re, shutil, subprocess, tempfile
from dataclasses import replace
from pathlib import Path
from sift import cfamily, run
from sift.code import Unanalyzed
from sift.jev import Jev, api_key
from sift.triage import triage

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "targets"
HERE = REPO / "data/magma"  # compile DBs in db/<target>/, labels and run directories are written here
OUT_OF_SCOPE = {
    "libpng": r"^(contrib|tests?|scripts|projects|arm|intel|mips|powerpc)/|^pngtest\.c$",
    "libtiff": r"^(test|contrib|build|archive|port|html|doc|cmake)/",
    "libxml2": r"^(test|fuzz|example|python|doc|win32|vms|os400|macos|VxWorks|bakefile|xstc|result)/|^(test.*|runtest.*|runsuite|runxmlconf|testapi|trionan|trio|triostr|lint)\.c$",
    "libsndfile": r"^(tests|examples|regtest|ossfuzz|Octave|Scripts|doc|cmake|man|m4)/|^src/test_",
    "lua": r"^(testes)/|^(ltests|onelua)\.c$",
    "poppler": r"^(qt5|qt6|glib|cpp|test|fuzz|cmake)/",
}

def strip(path):
    r = subprocess.run(["unifdef", "-UMAGMA_ENABLE_FIXES", "-UMAGMA_ENABLE_CANARIES", "-UENABLE_MAGMA_FIXES", str(path)], capture_output=True)
    path.write_bytes(r.stdout)

def changed_lines(t):
    """Per bug: lines in the all-bugs tree that the bug changed, found via base coordinates."""
    base, buggy = ROOT / f"magma-src/{t}-base", ROOT / f"magma-src/{t}-bugs"
    result = {}
    for p in sorted((ROOT / f"magma/targets/{t}/patches/bugs").glob("*.patch")):
        text = p.read_text().replace("%MAGMA_BUG%", p.stem)
        spans = []
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            files = sorted(set(re.findall(r"^\+\+\+ b/(\S+)", text, re.M)))
            for f in files:
                (tmp / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(base / f, tmp / f)
            subprocess.run(["patch", "-s", "-p1", "-d", str(tmp)], input=text.encode(), check=True)
            for f in files:
                strip(tmp / f)
                old = (base / f).read_text(errors="replace").splitlines()
                one = (tmp / f).read_text(errors="replace").splitlines()
                allb = (buggy / f).read_text(errors="replace").splitlines()
                # base line -> all-bugs line
                to_all = {}
                for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, allb, autojunk=False).get_opcodes():
                    for k in range(i2 - i1 + (1 if tag != "equal" else 0)):
                        to_all.setdefault(i1 + k, j1 + min(k, max(j2 - j1 - 1, 0)))
                for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, one, autojunk=False).get_opcodes():
                    if tag != "equal":
                        for i in range(i1, max(i2, i1 + 1)):
                            spans.append((f, to_all.get(i, i) + 1))
        result[p.stem] = spans
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target"); ap.add_argument("--max-requests", type=int)
    ap.add_argument("--estimate", action="store_true")
    a = ap.parse_args()
    t = a.target
    src = ROOT / f"magma-src/{t}-bugs"
    scan = cfamily.scan(src, [HERE / f"db/{t}/compile_commands.json"])
    scope = re.compile(OUT_OF_SCOPE[t])
    keep = [f for f in scan.functions if not scope.search(f.path)]
    dropped = [Unanalyzed(f.path, f.start_line, f.end_line, f.name, "outside the agreed scope")
               for f in scan.functions if scope.search(f.path)]
    scan = replace(scan, functions=keep, unanalyzed=scan.unanalyzed + dropped,
                   calls=[c for c in scan.calls if not scope.search(c.caller.split(":")[0])])
    by_file = {}
    for f in keep:
        by_file.setdefault(f.path, []).append(f)
    labels = {}
    for bug, spans in changed_lines(t).items():
        ids = set()
        for path, line in spans:
            inner = [f for f in by_file.get(path, []) if f.start_line <= line <= f.end_line]
            if inner:
                ids.add(min(inner, key=lambda f: f.end_line - f.start_line).id)
        labels[bug] = sorted(ids)
    (HERE / f"labels-{t}.json").write_text(json.dumps(labels, indent=1))
    chars = sum(len(f.code) for f in keep)
    print(json.dumps({"target": t, "functions": len(keep), "out_of_scope": len(dropped),
                      "unanalyzed": len(scan.unanalyzed) - len(dropped), "chars": chars,
                      "failed_parses": scan.failed_parses, "configs": len(scan.configs),
                      "unlabeled_bugs": [b for b, v in labels.items() if not v]}))
    if a.estimate:
        return
    d = HERE / f"runs/{t}"
    d.mkdir(parents=True, exist_ok=True)
    jev = Jev(api_key(), d / "jev-cache.jsonl", max_requests=a.max_requests)
    async def score():
        try:
            return await triage(keep, jev, 0.60, 0.15)
        finally:
            await jev.close()
    print(json.dumps(run.write(d, run.manifest(src, 0.60, 0.15), scan, asyncio.run(score()), jev.stopped)))

if __name__ == "__main__":
    main()
