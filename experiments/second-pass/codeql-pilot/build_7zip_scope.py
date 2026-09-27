#!/usr/bin/env python3
"""Compile the 7-Zip C files covered by the pinned first-pass inventory."""

import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--functions", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--objects-dir", type=Path, required=True)
    args = parser.parse_args()

    functions = [json.loads(line) for line in args.functions.read_text().splitlines() if line]
    files = sorted({row["file"] for row in functions})
    if len(functions) != 602 or len(files) != 55 or any(not path.startswith("C/") or not path.endswith(".c") for path in files):
        raise ValueError("expected the pinned 7-Zip 26.01 first-pass scope: 602 functions in 55 C files")

    source_root = args.source_root.resolve()
    objects_dir = args.objects_dir.resolve()
    for relative in files:
        source = (source_root / relative).resolve()
        if not source.is_relative_to(source_root) or not source.is_file():
            raise ValueError("source path is outside snapshot or absent: " + relative)
        output = objects_dir / Path(relative).with_suffix(".o")
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["/usr/bin/clang", "-c", relative, "-o", str(output)],
                       cwd=source_root, check=True)
    print(f"compiled {len(files)} C files from {source_root}")


if __name__ == "__main__":
    main()
