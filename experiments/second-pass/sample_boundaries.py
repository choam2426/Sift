#!/usr/bin/env python3
"""Choose nested, deterministic development samples of P boundary groups."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


RULE = "boundary-sample-v1"
SAMPLE_SIZES = (200, 800)
POLICIES = ("P", "R", "C")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--boundaries", type=Path, required=True,
                        help="directory made by prepare_boundaries.py")
    parser.add_argument("--stage1-run", type=Path, required=True,
                        help="stage-1 run containing selected.jsonl and functions.jsonl")
    parser.add_argument("--target", type=Path, required=True,
                        help="source tree used to compute the M0 size proxy")
    parser.add_argument("--required", type=Path,
                        help="evaluator-only JSONL containing required p_candidate_id values")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    boundary_manifest = _object(args.boundaries / "manifest.json")
    if boundary_manifest.get("rule") != "source-callsite-boundaries-v1":
        raise ValueError("unsupported boundary inventory rule")

    atoms = _indexed_rows(args.boundaries / "callsites.jsonl", "id")
    candidates = {
        policy: _indexed_rows(
            args.boundaries / f"candidates-{policy.lower()}.jsonl", "id"
        )
        for policy in POLICIES
    }
    _validate_candidates(candidates, atoms)

    scores, score_normalization = _scores(args.stage1_run / "selected.jsonl")
    functions, function_normalization = _function_sources(
        args.stage1_run / "functions.jsonl", args.target
    )
    required = _required(args.required, candidates["P"])

    p_population = []
    p_singletons = 0
    for candidate in candidates["P"].values():
        callsite_ids = tuple(candidate["callsite_ids"])
        if len(callsite_ids) == 1 and candidate["id"] not in required:
            p_singletons += 1
            continue
        p_population.append(candidate)

    member_index = {
        policy: _member_index(rows.values())
        for policy, rows in candidates.items()
    }
    records = [
        _record(candidate, member_index, atoms, scores, functions)
        for candidate in p_population
    ]
    by_id = {record["p_candidate_id"]: record for record in records}
    missing_required = required - by_id.keys()
    if missing_required:
        raise ValueError(f"required P candidates absent from sample population: {sorted(missing_required)}")

    ordinary = [record for record in records if record["p_candidate_id"] not in required]
    ordered = [by_id[candidate_id] for candidate_id in sorted(required)]
    ordered += _stratified_order(ordinary)

    outputs = {}
    for size in SAMPLE_SIZES:
        if len(ordered) < size:
            raise ValueError(f"population has {len(ordered)} groups, fewer than sample size {size}")
        sample = sorted(ordered[:size], key=lambda row: row["p_candidate_id"])
        path = args.output / f"sample-{size}.jsonl"
        _jsonl(path, sample)
        outputs[str(size)] = {
            "path": path.name,
            "sha256": _sha(path),
            **_summary(sample, candidates, atoms, functions),
        }

    manifest = {
        "rule": RULE,
        "sample_sizes": list(SAMPLE_SIZES),
        "inputs": {
            "boundary_manifest_sha256": _sha(args.boundaries / "manifest.json"),
            "callsites_sha256": _sha(args.boundaries / "callsites.jsonl"),
            "candidates": {
                policy: _sha(args.boundaries / f"candidates-{policy.lower()}.jsonl")
                for policy in POLICIES
            },
            "selected_sha256": _sha(args.stage1_run / "selected.jsonl"),
            "functions_sha256": _sha(args.stage1_run / "functions.jsonl"),
            "required_sha256": _sha(args.required) if args.required else None,
        },
        "population": {
            "p_groups": len(candidates["P"]),
            "excluded_singleton_p_groups": p_singletons,
            "eligible_p_groups": len(records),
            "required_p_groups": len(required),
            "strata": dict(sorted(Counter(row["stratum"] for row in records).items())),
        },
        "input_normalization": {
            "stage1_scores": score_normalization,
            "function_sources": function_normalization,
        },
        "samples": outputs,
        "notes": [
            "Required groups are applied by the evaluator after candidate generation.",
            "Sample rows do not identify which groups were required.",
            "M0 size proxies contain caller call expressions plus unique callee bodies.",
            "When one function ID names multiple conditional bodies, the longest body is used.",
            "When one selected function ID has multiple scores, the highest score is used.",
            "Estimated tokens use the observed stage-1 ratio of 1.8 source characters per token.",
        ],
    }
    _json(args.output / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False))


def _record(candidate: dict, member_index: dict, atoms: dict, scores: dict,
            functions: dict) -> dict:
    member_ids = tuple(candidate["callsite_ids"])
    member_key = tuple(sorted(member_ids))
    related = {}
    for policy in POLICIES:
        policy_ids = set()
        for callsite_id in member_ids:
            policy_ids.update(member_index[policy][callsite_id])
        selected = []
        covered = set()
        for candidate_id in sorted(policy_ids):
            row = member_index[policy]["@rows"][candidate_id]
            row_members = set(row["callsite_ids"])
            overlap = row_members & set(member_ids)
            if overlap:
                selected.append(candidate_id)
                covered.update(overlap)
        if covered != set(member_ids):
            raise ValueError(f"{candidate['id']}: {policy} candidates do not cover P members")
        related[policy] = selected

    caller = candidate["caller"]
    if caller not in scores:
        raise ValueError(f"{candidate['id']}: caller has no stage-1 score: {caller}")
    m0_chars = _m0_chars(member_key, candidate["callees"], atoms, functions)
    features = {
        "calls": len(member_ids),
        "r_splits": len(related["R"]),
        "m0_size_proxy_chars": m0_chars,
        "stage1_score": scores[caller],
    }
    return {
        "p_candidate_id": candidate["id"],
        "policy_candidate_ids": related,
        "stratum": _stratum(features),
        "features": features,
    }


def _member_index(rows) -> dict:
    index = defaultdict(list)
    row_index = {}
    for row in rows:
        candidate_id = row["id"]
        row_index[candidate_id] = row
        for callsite_id in row["callsite_ids"]:
            index[callsite_id].append(candidate_id)
    result = dict(index)
    result["@rows"] = row_index
    return result


def _stratum(features: dict) -> str:
    return "/".join((
        _bucket("calls", features["calls"], (2, 4, 8)),
        _bucket("r", features["r_splits"], (1, 2, 4)),
        _bucket("chars", features["m0_size_proxy_chars"], (2_000, 8_000, 32_000)),
        _score_bucket(features["stage1_score"]),
    ))


def _bucket(name: str, value: int, limits: tuple[int, ...]) -> str:
    for limit in limits:
        if value <= limit:
            return f"{name}<={limit}"
    return f"{name}>{limits[-1]}"


def _score_bucket(value: float) -> str:
    if value < 0.70:
        return "score<0.70"
    if value < 0.80:
        return "score<0.80"
    return "score>=0.80"


def _stratified_order(rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        groups[row["stratum"]].append(row)
    ranked = []
    for stratum, members in groups.items():
        members.sort(key=lambda row: _digest({
            "rule": RULE,
            "stratum": stratum,
            "p_candidate_id": row["p_candidate_id"],
        }))
        total = len(members)
        stratum_tie = _digest({"rule": RULE, "stratum": stratum})
        for index, row in enumerate(members):
            ranked.append((index / total, stratum_tie, row["p_candidate_id"], row))
    ranked.sort(key=lambda item: item[:3])
    return [item[3] for item in ranked]


def _summary(sample: list[dict], candidates: dict, atoms: dict,
             functions: dict) -> dict:
    ids = {policy: set() for policy in POLICIES}
    for row in sample:
        for policy in POLICIES:
            ids[policy].update(row["policy_candidate_ids"][policy])

    packet_keys = set()
    m0_chars = 0
    for policy in POLICIES:
        for candidate_id in ids[policy]:
            candidate = candidates[policy][candidate_id]
            member_key = tuple(sorted(candidate["callsite_ids"]))
            packet_keys.add(member_key)
    for member_key in packet_keys:
        callees = sorted({
            callee
            for callsite_id in member_key
            for callee in _direct_callees(atoms[callsite_id])
        })
        m0_chars += _m0_chars(member_key, callees, atoms, functions)

    return {
        "p_groups": len(sample),
        "policy_candidates": {policy: len(ids[policy]) for policy in POLICIES},
        "unique_packet_member_sets": len(packet_keys),
        "m0_size_proxy_chars": m0_chars,
        "m0_size_proxy_tokens_at_1_8_chars_per_token": round(m0_chars / 1.8),
        "strata": dict(sorted(Counter(row["stratum"] for row in sample).items())),
    }


def _m0_chars(member_ids, callees, atoms: dict, functions: dict) -> int:
    call_chars = sum(len(atoms[callsite_id]["code"]) for callsite_id in member_ids)
    missing = sorted(set(callees) - functions.keys())
    if missing:
        raise ValueError(f"callee functions missing from functions.jsonl: {missing[:3]}")
    return call_chars + sum(len(functions[callee]) for callee in set(callees))


def _direct_callees(atom: dict) -> set[str]:
    return {
        target["callee"]
        for target in atom["targets"]
        if target.get("kind") == "direct" and isinstance(target.get("callee"), str)
    }


def _function_sources(path: Path, target: Path) -> tuple[dict[str, str], dict]:
    target = target.resolve()
    sources = {}
    variants = defaultdict(set)
    rows = 0
    file_cache = {}
    for number, row in enumerate(_rows(path), 1):
        rows += 1
        function_id = row.get("id")
        relative = row.get("path")
        start = row.get("start_line")
        end = row.get("end_line")
        if (not isinstance(function_id, str) or not isinstance(relative, str)
                or not isinstance(start, int) or not isinstance(end, int)
                or start < 1 or end < start):
            raise ValueError(f"{path}:{number}: invalid function boundary")
        source_path = (target / relative).resolve()
        if not source_path.is_relative_to(target):
            raise ValueError(f"{path}:{number}: source path escapes target")
        if source_path not in file_cache:
            file_cache[source_path] = source_path.read_text(errors="replace").splitlines(True)
        lines = file_cache[source_path]
        if end > len(lines):
            raise ValueError(f"{path}:{number}: function boundary exceeds source file")
        code = "".join(lines[start - 1:end])
        variants[function_id].add((start, end, hashlib.sha256(code.encode()).hexdigest()))
        previous = sources.get(function_id)
        if previous is None or (len(code), code) > (len(previous), previous):
            sources[function_id] = code
    return sources, {
        "rows": rows,
        "unique_function_ids": len(sources),
        "duplicate_rows": rows - len(sources),
        "ids_with_distinct_source_variants": sum(len(values) > 1 for values in variants.values()),
        "duplicate_rule": "longest source body, then lexical order",
        "chosen_sources_sha256": _digest({
            function_id: hashlib.sha256(code.encode()).hexdigest()
            for function_id, code in sorted(sources.items())
        }),
    }


def _scores(path: Path) -> tuple[dict[str, float], dict]:
    scores = {}
    variants = defaultdict(set)
    rows = 0
    for number, row in enumerate(_rows(path), 1):
        rows += 1
        function_id = row.get("function_id")
        score = row.get("score")
        if not isinstance(function_id, str) or not isinstance(score, (int, float)):
            raise ValueError(f"{path}:{number}: invalid function_id or score")
        score = float(score)
        if not 0 <= score <= 1:
            raise ValueError(f"{path}:{number}: score outside [0, 1]")
        variants[function_id].add(score)
        scores[function_id] = max(score, scores.get(function_id, score))
    return scores, {
        "rows": rows,
        "unique_function_ids": len(scores),
        "duplicate_rows": rows - len(scores),
        "ids_with_distinct_scores": sum(len(values) > 1 for values in variants.values()),
        "duplicate_rule": "highest score",
    }


def _required(path: Path | None, p_candidates: dict) -> set[str]:
    if path is None:
        return set()
    required = set()
    for number, row in enumerate(_rows(path), 1):
        candidate_id = row.get("p_candidate_id")
        if not isinstance(candidate_id, str):
            raise ValueError(f"{path}:{number}: invalid p_candidate_id")
        if candidate_id not in p_candidates:
            raise ValueError(f"{path}:{number}: unknown P candidate {candidate_id}")
        required.add(candidate_id)
    return required


def _validate_candidates(candidates: dict, atoms: dict) -> None:
    for policy in POLICIES:
        for candidate in candidates[policy].values():
            if candidate.get("policy") != policy:
                raise ValueError(f"{candidate.get('id')}: wrong policy")
            member_ids = candidate.get("callsite_ids")
            if (not isinstance(member_ids, list) or not member_ids
                    or not all(isinstance(value, str) for value in member_ids)):
                raise ValueError(f"{candidate.get('id')}: invalid callsite_ids")
            if len(member_ids) != len(set(member_ids)):
                raise ValueError(f"{candidate.get('id')}: duplicate callsite_ids")
            if not isinstance(candidate.get("caller"), str):
                raise ValueError(f"{candidate.get('id')}: invalid caller")
            if (not isinstance(candidate.get("callees"), list)
                    or not all(isinstance(value, str) for value in candidate["callees"])):
                raise ValueError(f"{candidate.get('id')}: invalid callees")
            missing = set(member_ids) - atoms.keys()
            if missing:
                raise ValueError(f"{candidate.get('id')}: unknown callsites {sorted(missing)[:3]}")


def _indexed_rows(path: Path, field: str) -> dict[str, dict]:
    index = {}
    for number, row in enumerate(_rows(path), 1):
        value = row.get(field)
        if not isinstance(value, str):
            raise ValueError(f"{path}:{number}: invalid {field}")
        if value in index:
            raise ValueError(f"{path}:{number}: duplicate {field}: {value}")
        index[value] = row
    return index


def _object(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected one JSON object")
    return value


def _rows(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line:
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number}: expected one JSON object")
        rows.append(value)
    return rows


def _digest(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _jsonl(path: Path, rows) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


if __name__ == "__main__":
    main()
