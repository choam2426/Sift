"""Pinned source and CodeQL fact access shared by second-pass view builders."""

from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


class FactSnapshot:
    def __init__(self, facts, source_root, functions, first_manifest, selected):
        self.facts = facts.resolve()
        self.source_root = source_root.resolve()
        self.manifest = json.loads((self.facts / "manifest.json").read_text())
        self.fact_hash = sha((self.facts / "manifest.json").read_bytes())
        first = json.loads(first_manifest.read_text())
        revision = subprocess.check_output(
            ["git", "-C", str(self.source_root), "rev-parse", "HEAD"], text=True).strip()
        if (self.manifest["status"] != "neutral_facts_no_model_calls" or
                self.manifest["source_revision"] != revision or
                first["source_revision"] != revision or
                first["functions_sha256"] != sha(functions.read_bytes())):
            raise ValueError("CodeQL, source, and first-pass snapshots differ")
        if subprocess.run(["git", "-C", str(self.source_root), "diff", "--quiet", "HEAD", "--"],
                          check=False).returncode:
            raise ValueError("source has tracked changes")
        self.revision = revision
        self.units = jsonl(functions)
        self.by_id = {unit["id"]: unit for unit in self.units}
        if len(self.by_id) != len(self.units):
            raise ValueError("duplicate first-pass function ID")
        self.by_file_name = defaultdict(list)
        for unit in self.units:
            self.by_file_name[(unit["file"], unit["name"])].append(unit)
        self.selected = jsonl(selected)
        if len({row["unit_id"] for row in self.selected}) != len(self.selected):
            raise ValueError("duplicate selected origin")
        for row in self.selected:
            if row["unit_id"] not in self.by_id or row["source_revision"] != revision:
                raise ValueError("selected origin mismatches source")
        self.lines = {}
        self.macros_by_file = {}
        self.invalid_type_rows = []
        self.type_declarations = self._types()

    def rows(self, name):
        info = self.manifest["files"][name]
        path = self.facts / f"{name}.csv"
        if sha(path.read_bytes()) != info["csv_sha256"]:
            raise ValueError(f"fact CSV hash mismatch: {name}")
        with path.open(newline="") as stream:
            return list(csv.DictReader(stream))

    def unit(self, file, line, name):
        options = [unit for unit in self.by_file_name[(file, name)]
                   if unit["start_line"] <= int(line) <= unit["end_line"]]
        if len(options) > 1:
            raise ValueError(f"ambiguous function location: {file}:{line}:{name}")
        return options[0] if options else None

    def source_lines(self, relative):
        if relative not in self.lines:
            path = (self.source_root / relative).resolve()
            if not path.is_relative_to(self.source_root) or not path.is_file():
                raise ValueError(f"source path outside pinned root: {relative}")
            self.lines[relative] = path.read_text(errors="replace").splitlines()
        return self.lines[relative]

    def span(self, relative, first, last):
        lines = self.source_lines(relative)
        first, last = int(first), int(last)
        if not 1 <= first <= last <= len(lines):
            raise ValueError(f"invalid source span: {relative}:{first}-{last}")
        return "\n".join(lines[first - 1:last])

    def expr(self, relative, start_line, start_col, end_line, end_col):
        lines = self.source_lines(relative)
        a, b, c, d = map(int, (start_line, start_col, end_line, end_col))
        if not 1 <= a <= c <= len(lines) or b < 1 or d < 1:
            raise ValueError(f"invalid expression span: {relative}:{a}-{c}")
        if a == c:
            return lines[a - 1][b - 1:d]
        return "\n".join([lines[a - 1][b - 1:]] + lines[a:c - 1] + [lines[c - 1][:d]])

    def _types(self):
        by_name = defaultdict(list)
        for row in self.rows("type_declarations"):
            name, file, declaration_start, end = row["col0"], row["col1"], int(row["col2"]), int(row["col4"])
            if end < declaration_start:
                self.invalid_type_rows.append({"name": name, "file": file,
                                               "start_line": declaration_start, "end_line": end})
                continue  # A separate valid location row may describe this typedef.
            start = int(row["col8"]) if row["col7"] == file else declaration_start
            if start > end:
                start = declaration_start
            if not 1 <= start <= end <= len(self.source_lines(file)):
                self.invalid_type_rows.append({"name": name, "file": file,
                                               "start_line": start, "end_line": end})
                continue  # Macro locations can combine lines from different files.
            by_name[name].append({"name": name, "file": file, "start_line": start,
                                  "end_line": end})
        return by_name

    def declarations(self, member_ids):
        code = "\n".join(self.by_id[unit_id]["code"] for unit_id in sorted(member_ids))
        names = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", code)) & self.type_declarations.keys()
        result = {}
        queue = list(names)
        while queue:
            name = queue.pop()
            for item in self.type_declarations[name]:
                key = (item["file"], item["start_line"], item["end_line"])
                if key in result:
                    continue
                declaration = {**item, "code": self.span(item["file"], item["start_line"], item["end_line"])}
                result[key] = declaration
                tokens = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", declaration["code"]))
                queue.extend(sorted(tokens & self.type_declarations.keys() - names))
                names |= tokens & self.type_declarations.keys()
        return [result[key] for key in sorted(result)]

    def macros(self, declarations):
        result = {}
        for declaration in declarations:
            file = declaration["file"]
            if file not in self.macros_by_file:
                definitions = defaultdict(list)
                lines = self.source_lines(file)
                index = 0
                while index < len(lines):
                    match = re.match(r"\s*#\s*define\s+([A-Za-z_]\w*)\b", lines[index])
                    if match:
                        start = index + 1
                        while index < len(lines) - 1 and lines[index].rstrip().endswith("\\"):
                            index += 1
                        definitions[match.group(1)].append({"name": match.group(1),
                                                              "file": file, "start_line": start,
                                                              "end_line": index + 1,
                                                              "code": self.span(file, start, index + 1)})
                    index += 1
                self.macros_by_file[file] = definitions
            tokens = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", declaration["code"]))
            for name in tokens:
                for macro in self.macros_by_file[file].get(name, []):
                    result[(file, macro["start_line"], name)] = macro
        return [result[key] for key in sorted(result)]

    def function_payload(self, member_ids):
        ordered = sorted(member_ids)
        keys = {unit_id: f"F{index}" for index, unit_id in enumerate(ordered, 1)}
        functions = []
        for unit_id in ordered:
            unit = self.by_id[unit_id]
            if self.span(unit["file"], unit["start_line"], unit["end_line"]) != unit["code"].replace("\r\n", "\n"):
                raise ValueError(f"function source changed: {unit_id}")
            functions.append({"key": keys[unit_id], "file": unit["file"],
                              "start_line": unit["start_line"], "end_line": unit["end_line"],
                              "symbol": unit["name"], "code": unit["code"]})
        return keys, functions


def write_view(output, view, rule, facts, candidates, origins, unresolved):
    if output.exists():
        raise ValueError("output exists; use a new run ID")
    output.mkdir(parents=True)
    manifest = {"status": "prepared_no_model_calls", "view": view,
                "rule_version": rule, "source_revision": facts.revision,
                "fact_snapshot_sha256": facts.fact_hash,
                "candidate_count": len(candidates), "origin_count": len({x["origin_id"] for x in origins}),
                "invalid_type_location_rows": len(facts.invalid_type_rows),
                "size_policy": "record_only_never_exclude_functions"}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    for filename, records in (("states.jsonl", candidates), ("origins.jsonl", origins),
                              ("unresolved.jsonl", unresolved)):
        (output / filename).write_text("".join(canonical(record).decode() + "\n" for record in records))
