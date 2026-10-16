#!/usr/bin/env python3
"""Build a small CodeQL-DB-facts pilot around the top selected XzDec function.

The candidate rule is source-neutral: every address-taken field of the entry
object passed to a statically resolved callee becomes one state-object
candidate. No vulnerability labels, security queries, byte limits, or Jev
calls are used here. This is a feasibility pilot, not the A baseline.
"""

from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "targets/7zip"
FIRST_RUN = ROOT / "experiments/first-pass/runs/7zip-26.01-code-only-v1"
FUNCTIONS = ROOT / "data/7zip.c.functions.jsonl"
FACTS = Path("/tmp")
STAMP = "2026-09-25"
DB_TAG = "55"
RULE = "addressed-state-object-v3-pilot"
OUTPUT = ROOT / "experiments/second-pass/runs/codedb-state-pilot-2026-09-25-v4"
FACT_NAMES = (
    "db-call-arguments", "db-field-accesses", "db-conditions", "db-parameters",
    "source-type-declarations",
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def fact_path(name):
    return FACTS / f"sift-{name}-{DB_TAG}-{STAMP}.csv"


def read_csv(name):
    with fact_path(name).open(newline="") as source:
        return list(csv.DictReader(source))


class Sources:
    def __init__(self):
        self.lines = {}

    def get(self, relative):
        if relative not in self.lines:
            path = (SOURCE_ROOT / relative).resolve()
            if not path.is_relative_to(SOURCE_ROOT.resolve()) or not path.is_file():
                raise ValueError(f"source outside pinned tree: {relative}")
            self.lines[relative] = path.read_text(errors="replace").splitlines()
        return self.lines[relative]

    def lines_span(self, relative, start, end):
        lines = self.get(relative)
        if not 1 <= start <= end <= len(lines):
            raise ValueError(f"invalid source lines: {relative}:{start}-{end}")
        return "\n".join(lines[start - 1:end])

    def expr(self, relative, start_line, start_col, end_line, end_col):
        lines = self.get(relative)
        if not 1 <= start_line <= end_line <= len(lines):
            raise ValueError(f"invalid expression lines: {relative}")
        if start_line == end_line:
            return lines[start_line - 1][start_col - 1:end_col]
        return "\n".join(
            [lines[start_line - 1][start_col - 1:]]
            + lines[start_line:end_line - 1]
            + [lines[end_line - 1][:end_col]]
        )


def key(file, line, name):
    return file, int(line), name


def type_name(type_text):
    names = re.findall(r"[A-Za-z_][A-Za-z_0-9]*", type_text)
    return next((name for name in names if name not in {"const", "volatile", "struct"}), None)


def build():
    revision = subprocess.check_output(
        ["git", "-C", str(SOURCE_ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    if subprocess.run(
        ["git", "-C", str(SOURCE_ROOT), "diff", "--quiet", "HEAD", "--"],
        check=False,
    ).returncode:
        raise ValueError("source snapshot has tracked changes")
    first_manifest = json.loads((FIRST_RUN / "manifest.json").read_text())
    if (first_manifest["source_revision"] != revision
            or first_manifest["functions_sha256"] != sha(FUNCTIONS.read_bytes())
            or first_manifest["input_profile"] != "code-only-v1"):
        raise ValueError("first-pass input does not match source snapshot")
    units = read_jsonl(FUNCTIONS)
    by_id = {unit["id"]: unit for unit in units}
    by_location = {(unit["file"], unit["start_line"], unit["name"]): unit
                   for unit in units}
    if len(by_id) != len(units) or len(by_location) != len(units):
        raise ValueError("ambiguous function inventory")
    selected = read_jsonl(FIRST_RUN / "selected.jsonl")
    if selected != sorted(selected, key=lambda row: (-row["score"], row["unit_id"])):
        raise ValueError("first-pass selection order changed")
    entry = next(by_id[row["unit_id"]] for row in selected
                 if by_id[row["unit_id"]]["file"] == "C/XzDec.c")
    rank = next(i for i, row in enumerate(selected, 1) if row["unit_id"] == entry["id"])
    if any(entry[k] != value for k, value in (("name", "XzUnpacker_Code"),
                                               ("start_line", 1015))):
        raise ValueError("pilot entry changed; review selection rule")

    sources = Sources()
    for unit in units:
        if sources.lines_span(unit["file"], unit["start_line"], unit["end_line"]) != unit["code"]:
            raise ValueError("function differs from pinned source: " + unit["id"])

    params = defaultdict(dict)
    for row in read_csv("db-parameters"):
        params[key(row["col0"], row["col1"], row["col2"])][int(row["index"])] = {
            "name": row["col4"], "type": row["col5"]
        }
    entry_key = key(entry["file"], entry["start_line"], entry["name"])
    owner_parameter = params[entry_key][0]
    owner_name = owner_parameter["name"]
    owner_type = owner_parameter["type"]

    calls = defaultdict(lambda: {"arguments": {}})
    for row in read_csv("db-call-arguments"):
        caller = key(row["col0"], row["col1"], row["col2"])
        callee = key(row["col3"], row["col4"], row["col5"])
        call_key = (caller, callee, row["col6"], int(row["col7"]), int(row["col8"]),
                    int(row["col9"]), int(row["col10"]))
        item = calls[call_key]
        index = int(row["index"])
        code = sources.expr(row["col12"], int(row["col13"]), int(row["col14"]),
                            int(row["col15"]), int(row["col16"]))
        old = item["arguments"].get(index)
        if old is not None and old != code:
            raise ValueError("ambiguous argument expression")
        item["arguments"][index] = code
    call_items = [(call_key, calls[call_key]) for call_key in sorted(calls)]

    type_rows = defaultdict(list)
    for row in read_csv("source-type-declarations"):
        type_rows[row["col0"]].append(row)

    def declaration(name):
        options = type_rows.get(name, [])
        if not options:
            return None
        source = sorted(options, key=lambda row: (row["col1"], int(row["col2"])))[0]
        file = source["col1"]
        end = int(source["col4"])
        start = int(source["col8"]) if source["col7"] == file else end
        if start > end:
            start = end
        return {"name": name, "file": file, "start_line": start, "end_line": end,
                "code": sources.lines_span(file, start, end)}

    def supporting_declarations(owner_name, state_name):
        names = {name for name in (owner_name, state_name) if name}
        queue = [state_name]
        while queue:
            current = queue.pop()
            item = declaration(current)
            if not item:
                continue
            for token in set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", item["code"])):
                if token in type_rows and token not in names:
                    names.add(token)
                    queue.append(token)
        result = [item for name in sorted(names) if name and (item := declaration(name))]
        return sorted(result, key=lambda item: (item["file"], item["start_line"], item["name"]))

    def supporting_macros(declarations):
        result = {}
        for item in declarations:
            tokens = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", item["code"]))
            for line_number, line in enumerate(sources.get(item["file"]), 1):
                match = re.match(r"\s*#\s*define\s+([A-Za-z_][A-Za-z_0-9]*)\b", line)
                if match and match.group(1) in tokens:
                    key = (item["file"], line_number)
                    result[key] = {"name": match.group(1), "file": item["file"],
                                   "line": line_number, "code": line}
        return [result[key] for key in sorted(result)]

    root_type = type_name(owner_type)
    address_calls = defaultdict(list)
    for call_key, item in call_items:
        caller, callee, call_file, call_line, _, _, _ = call_key
        first_arg = item["arguments"].get(0, "")
        caller_param = params.get(caller, {}).get(0)
        if (not caller_param or caller_param["type"] != owner_type
                or caller_param["name"] != owner_name):
            continue
        match = re.fullmatch(r"&" + re.escape(owner_name) + r"->([A-Za-z_][A-Za-z_0-9]*)",
                             first_arg.strip())
        if match and callee in params and 0 in params[callee]:
            address_calls[match.group(1)].append((call_key, item))
    if not address_calls:
        raise ValueError("no state-object calls from entry owner type")

    field_rows = read_csv("db-field-accesses")
    condition_rows = read_csv("db-conditions")
    unresolved_rows = list(csv.reader((ROOT / "experiments/second-pass/runs/"
                                       "codeql-a-direct-2026-09-25/unresolved.csv").open()))[1:]
    candidates = []
    origins = []
    unresolved_report = []

    for field_name, roots in sorted(address_calls.items()):
        if not any(call_key[0] == entry_key for call_key, _ in roots):
            continue
        state_types = {params[call_key[1]][0]["type"] for call_key, _ in roots}
        state_names = {type_name(type_text) for type_text in state_types}
        if len(state_names) != 1 or None in state_names:
            unresolved_report.append({"field": field_name, "reason": "multiple_state_parameter_types",
                                      "types": sorted(state_types)})
            continue
        state_name = state_names.pop()
        state_members = {call_key[1] for call_key, _ in roots}
        queue = list(state_members)
        forwarding = []
        while queue:
            current = queue.pop()
            current_param = params.get(current, {}).get(0)
            if not current_param or type_name(current_param["type"]) != state_name:
                continue
            for call_key, item in call_items:
                caller, callee = call_key[:2]
                if (caller != current or item["arguments"].get(0, "").strip() != current_param["name"]
                        or type_name(params.get(callee, {}).get(0, {}).get("type", "")) != state_name):
                    continue
                forwarding.append((call_key, item))
                if callee not in state_members:
                    state_members.add(callee)
                    queue.append(callee)
        owner_callers = {call_key[0] for call_key, _ in roots}
        member_keys = {entry_key, *owner_callers, *state_members}
        mapped = {item: by_location.get(item) for item in member_keys}
        missing = [item for item, unit in mapped.items() if unit is None]
        if missing:
            unresolved_report.append({"field": field_name, "reason": "missing_function_body",
                                      "functions": [list(item) for item in sorted(missing)]})
            continue
        ordered = sorted((unit for unit in mapped.values() if unit), key=lambda unit: unit["id"])
        keys = {unit["id"]: f"F{index}" for index, unit in enumerate(ordered, 1)}

        def func_key(item):
            return keys[by_location[item]["id"]]

        relations = []
        seen_relations = set()
        for call_key, item in call_items:
            caller, callee, call_file, call_line, call_col, call_end, call_end_col = call_key
            if caller not in member_keys or callee not in member_keys:
                continue
            args = [{"index": index, "code": code} for index, code in sorted(item["arguments"].items())]
            relation = {"kind": "direct_call", "from": func_key(caller),
                        "to": func_key(callee), "file": call_file, "line": call_line,
                        "column": call_col, "arguments": args}
            encoded = compact(relation)
            if encoded not in seen_relations:
                seen_relations.add(encoded)
                relations.append(relation)
        relations.sort(key=lambda item: (item["file"], item["line"], item["column"],
                                         item["from"], item["to"]))

        state_decl = declaration(state_name) if state_name else None
        owner_decl = declaration(root_type) if root_type else None
        accesses = []
        for row in field_rows:
            enclosing = key(row["col0"], row["col1"], row["col2"])
            if enclosing not in member_keys:
                continue
            inside_state = bool(state_decl and row["col4"] == state_decl["file"]
                                and state_decl["start_line"] <= int(row["col5"])
                                <= state_decl["end_line"])
            inside_owner = bool(owner_decl and row["col3"] == field_name
                                and row["col4"] == owner_decl["file"]
                                and owner_decl["start_line"] <= int(row["col5"])
                                <= owner_decl["end_line"])
            if not inside_state and not inside_owner:
                continue
            access_code = sources.expr(row["col6"], int(row["col7"]), int(row["col8"]),
                                       int(row["col9"]), int(row["col10"]))
            accesses.append({"function": func_key(enclosing), "field": row["col3"],
                             "field_declaration": {"file": row["col4"], "line": int(row["col5"])},
                             "file": row["col6"], "line": int(row["col7"]),
                             "column": int(row["col8"]), "code": access_code,
                             "syntactic_modification": row["col12"] == "modified"})
        accesses.sort(key=lambda item: (item["file"], item["line"], item["column"],
                                       item["function"], item["field"]))

        conditions = []
        for row in condition_rows:
            enclosing = key(row["col0"], row["col1"], row["col2"])
            if enclosing not in member_keys:
                continue
            code = sources.expr(row["col3"], int(row["col4"]), int(row["col5"]),
                                int(row["col6"]), int(row["col7"]))
            conditions.append({"function": func_key(enclosing), "file": row["col3"],
                               "line": int(row["col4"]), "code": code})
        conditions.sort(key=lambda item: (item["file"], item["line"], item["function"]))

        declarations = supporting_declarations(root_type, state_name)
        macros = supporting_macros(declarations)
        unresolved = []
        for row in unresolved_rows:
            if len(row) != 6:
                continue
            enclosing = key(row[0], row[1], row[2])
            if enclosing not in member_keys:
                continue
            unresolved.append({"function": func_key(enclosing), "file": row[3],
                               "start_line": int(row[4]), "end_line": int(row[5]),
                               "code": sources.lines_span(row[3], int(row[4]), int(row[5]))})
        unresolved.sort(key=lambda item: (item["file"], item["start_line"], item["function"]))

        state = {
            "operation": {
                "entry": func_key(entry_key),
                "owner_type": owner_type,
                "state_expression": f"{owner_name}->{field_name}",
                "state_parameter_types": sorted(state_types),
                "possible_outputs": [value for index, value in sorted(params[entry_key].items())
                                     if index > 0 and "*" in value["type"]
                                     and not value["type"].lstrip().startswith("const ")],
            },
            "functions": [{"key": keys[unit["id"]], "file": unit["file"],
                           "start_line": unit["start_line"], "end_line": unit["end_line"],
                           "symbol": unit["name"], "code": unit["code"]} for unit in ordered],
            "supporting_declarations": declarations,
            "supporting_macros": macros,
            "relations": relations,
            "state_field_accesses": accesses,
            "if_conditions": conditions,
            "unresolved_calls": unresolved,
        }
        encoded = compact(state)
        candidate_id = sha(revision.encode() + b"\0" + encoded)
        candidate = {"candidate_id": candidate_id, "state_sha256": sha(encoded),
                     "state_bytes": len(encoded), "state": state}
        candidates.append(candidate)
        origins.append({"candidate_id": candidate_id, "origin_id": entry["id"],
                        "first_pass_rank": rank, "first_pass_score": selected[rank - 1]["score"],
                        "state_field": field_name, "member_ids": [unit["id"] for unit in ordered],
                        "root_call_count": len(roots), "forwarded_call_count": len(forwarding)})

    if not candidates:
        raise ValueError("pilot produced no candidates")
    if OUTPUT.exists():
        raise ValueError("output directory already exists")
    OUTPUT.mkdir(parents=True)
    facts_hashes = {name: sha(fact_path(name).read_bytes()) for name in FACT_NAMES}
    manifest = {"rule_version": RULE, "status": "pilot_input_no_jev_calls",
                "source_revision": revision, "source_root": str(SOURCE_ROOT.resolve()),
                "first_pass_functions_sha256": first_manifest["functions_sha256"],
                "first_pass_selected_sha256": sha((FIRST_RUN / "selected.jsonl").read_bytes()),
                "fact_csv_sha256": facts_hashes, "selection_rule":
                "highest-ranked first-pass function in C/XzDec.c; one candidate per address-taken field of its first parameter",
                "size_policy": "record_only_never_exclude_functions"}
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    def write_jsonl(name, rows):
        (OUTPUT / name).write_text("".join(compact(row).decode() + "\n" for row in rows))

    write_jsonl("states.jsonl", candidates)
    write_jsonl("origins.jsonl", origins)
    write_jsonl("unresolved.jsonl", unresolved_report)
    summary = {"entry_id": entry["id"], "entry_first_pass_rank": rank,
               "candidate_count": len(candidates),
               "state_fields": [row["state_field"] for row in origins],
               "state_bytes": {row["state_field"]: next(candidate["state_bytes"]
                                                    for candidate in candidates
                                                    if candidate["candidate_id"] == row["candidate_id"])
                               for row in origins},
               "unresolved_candidate_count": len(unresolved_report)}
    (OUTPUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
