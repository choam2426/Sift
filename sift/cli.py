import argparse
import asyncio
import json
import sys
from pathlib import Path

from sift import code, run
from sift.jev import Jev, api_key
from sift.triage import triage


def main(argv=None, transport=None) -> int:
    parser = argparse.ArgumentParser(prog="sift")
    commands = parser.add_subparsers(dest="command", required=True)
    stage1 = commands.add_parser("triage", help="score every function (stage 1)")
    stage1.add_argument("target", type=Path)
    stage1.add_argument("--run", type=Path, required=True, help="run directory; rerun to resume")
    stage1.add_argument("--concurrency", type=int, default=16)
    stage1.add_argument("--max-requests", type=int, help="stop after sending this many requests")
    stage1.add_argument("--estimate", action="store_true", help="count functions and tokens only")
    args = parser.parse_args(argv)

    functions = code.functions(args.target)
    if args.estimate:
        tokens = sum(len(f.code) for f in functions) // 4  # rough: ~4 characters per token
        print(json.dumps({"functions": len(functions), "approx_input_tokens": tokens}))
        return 0

    args.run.mkdir(parents=True, exist_ok=True)
    manifest = run.manifest(args.target)
    jev = Jev(api_key(), args.run / "jev-cache.jsonl", concurrency=args.concurrency,
              max_requests=args.max_requests, transport=transport)

    async def score():
        try:
            return await triage(functions, jev)
        finally:
            await jev.close()

    summary = run.write(args.run, manifest, functions, asyncio.run(score()), jev.stopped)
    print(json.dumps(summary))
    if jev.stopped:
        print(f"stopped: {jev.stopped}; rerun with the same --run to resume", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
