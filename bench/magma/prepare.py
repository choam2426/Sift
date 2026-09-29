"""Build Magma buggy trees without fixes or canaries, and derive function labels per bug."""
import difflib, json, re, shutil, subprocess, sys, tempfile
from pathlib import Path
from sift.code import definitions_in, LANGUAGES

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "targets"  # Magma checkout in targets/magma, pinned sources in targets/magma-src/<target>
MAGMA = ROOT / "magma/targets"
OUT = REPO / "data/magma"

def patch(text, cwd):
    subprocess.run(["patch", "-s", "-p1", "-d", str(cwd)], input=text.encode(), check=True)

def strip(path):
    r = subprocess.run(["unifdef", "-UMAGMA_ENABLE_FIXES", "-UMAGMA_ENABLE_CANARIES", "-UENABLE_MAGMA_FIXES", str(path)], capture_output=True)
    if r.returncode not in (0, 1):
        raise RuntimeError(r.stderr.decode())
    path.write_bytes(r.stdout)

def touched(text):
    return sorted(set(re.findall(r"^\+\+\+ b/(\S+)", text, re.M)))

labels = {}
for t in sys.argv[1:]:
    base = ROOT / f"magma-src/{t}-base"
    buggy = ROOT / f"magma-src/{t}-bugs"
    for d in (base, buggy):
        shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(ROOT / f"magma-src/{t}", base, ignore=shutil.ignore_patterns(".git"))
    # Setup patches only change build files and fuzz harnesses; skipped.
    shutil.copytree(base, buggy)
    bugs = sorted((MAGMA / t / "patches/bugs").glob("*.patch"))
    files = set()
    for p in bugs:
        text = p.read_text().replace("%MAGMA_BUG%", p.stem)
        patch(text, buggy)
        files |= set(touched(text))
    for f in files:
        strip(buggy / f)
    for p in bugs:
        text = p.read_text().replace("%MAGMA_BUG%", p.stem)
        funcs = set()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for f in touched(text):
                (tmp / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(base / f, tmp / f)
            patch(text, tmp)
            for f in touched(text):
                strip(tmp / f)
                old = (base / f).read_text(errors="replace").splitlines()
                new = (tmp / f).read_text(errors="replace").splitlines()
                lines = set()
                for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
                    if tag != "equal":
                        lines |= set(range(j1 + 1, max(j2, j1 + 1) + 1))
                if Path(f).suffix not in LANGUAGES:
                    continue
                defs = definitions_in((tmp / f).read_bytes(), f, LANGUAGES[Path(f).suffix])
                for line in lines:
                    inner = [d for d in defs if d.start_line <= line <= d.end_line]
                    if inner:
                        d = min(inner, key=lambda d: d.end_line - d.start_line)
                        funcs.add(f"{f}:{d.name}")
        labels[f"{t}/{p.stem}"] = sorted(funcs)
    for backup in [*buggy.rglob("*.orig"), *buggy.rglob("*.rej"), *base.rglob("*.orig"), *base.rglob("*.rej")]:
        backup.unlink()  # left by patch when a hunk applies with an offset
    left = subprocess.run(["grep", "-rl", "MAGMA", str(buggy)], capture_output=True, text=True).stdout.split()
    print(t, len(bugs), "bugs; files with MAGMA left:", left)
OUT.mkdir(parents=True, exist_ok=True)
(OUT / ("labels-prep-" + "-".join(sys.argv[1:]) + ".json")).write_text(json.dumps(labels, indent=1))
for k, v in labels.items():
    print(k, v)
